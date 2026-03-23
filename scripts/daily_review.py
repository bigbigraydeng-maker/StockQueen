"""
盘后自动复盘脚本
从 Supabase + Tiger 拉取当日数据，生成复盘 Markdown，写入 Obsidian DAILY/

用法：
  python scripts/daily_review.py              # 今天
  python scripts/daily_review.py 2026-03-24   # 指定日期
"""

import os
import sys
import json
import ssl
import urllib.request
from datetime import datetime, timedelta

# ── 配置 ─────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SERVICE_KEY")
OBS_URL = "https://127.0.0.1:28000"
OBS_TOKEN = "266d6f82c9a9c630dd313b091b772ee13c747b5698fb6c105e559f2109a2819d"

WEEKDAY_MAP = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


# ── Supabase REST 查询 ───────────────────────────────
def sb_query(table: str, params: str = "") -> list:
    url = f"{SB_URL}/rest/v1/{table}?{params}"
    req = urllib.request.Request(url, headers={
        "apikey": SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [WARN] {table} 查询失败: {e}")
        return []


# ── 数据拉取 ─────────────────────────────────────────
def fetch_regime(date_str: str) -> dict:
    """最近的 regime 记录"""
    rows = sb_query("regime_history", f"date=lte.{date_str}&order=date.desc&limit=1")
    return rows[0] if rows else {}


def fetch_rotation_trades(date_str: str) -> dict:
    """当日宝典操作：新建仓 + 平仓 + 当前活跃"""
    # 当日入场的
    entries = sb_query("rotation_positions",
        f"entry_date=eq.{date_str}&order=updated_at.desc")
    # 当日出场的
    exits = sb_query("rotation_positions",
        f"exit_date=eq.{date_str}&order=updated_at.desc")
    # 当前所有活跃
    active = sb_query("rotation_positions",
        "status=eq.active&order=entry_date.desc")
    # 待入场
    pending = sb_query("rotation_positions",
        "status=eq.pending_entry&order=updated_at.desc")
    return {"entries": entries, "exits": exits, "active": active, "pending": pending}


def fetch_ed_trades(date_str: str) -> dict:
    entries = sb_query("event_driven_positions",
        f"entry_date=eq.{date_str}&order=updated_at.desc")
    exits = sb_query("event_driven_positions",
        f"exit_date=eq.{date_str}&order=updated_at.desc")
    active = sb_query("event_driven_positions",
        "status=eq.active&order=entry_date.desc")
    return {"entries": entries, "exits": exits, "active": active}


def fetch_order_audit(date_str: str) -> list:
    return sb_query("order_audit_log",
        f"created_at=gte.{date_str}&order=created_at.desc&limit=50")


def fetch_scheduler_runs(date_str: str) -> list:
    return sb_query("scheduler_runs",
        f"started_at=gte.{date_str}&order=started_at.desc&limit=50")


def fetch_event_signals(date_str: str) -> list:
    return sb_query("event_signals",
        f"created_at=gte.{date_str}&order=created_at.desc&limit=20")


# ── 格式化 ───────────────────────────────────────────
def fmt_regime(r: dict) -> str:
    if not r:
        return "— (无数据)"
    regime = r.get("regime", "?")
    score = r.get("score", "?")
    spy = r.get("spy_price", "?")
    signals = r.get("signals") or []
    sig_txt = ""
    if signals:
        parts = []
        for s in signals:
            parts.append(f"{s['name']}: {s['value']}{s.get('unit','')} (贡献 {s['contribution']:+d})")
        sig_txt = "\n".join(f"  - {p}" for p in parts)
    return f"**{regime.upper()}** (score={score}, SPY=${spy})" + (f"\n{sig_txt}" if sig_txt else "")


def fmt_position_table(positions: list, show_pnl=False) -> str:
    if not positions:
        return "| — | — | — | — | — |\n"
    lines = []
    for p in positions:
        ticker = p.get("ticker", "?")
        direction = p.get("direction", "long")
        entry_px = p.get("entry_price", "")
        qty = p.get("quantity", "")
        pos_type = p.get("position_type", "alpha")

        if show_pnl and p.get("exit_price"):
            pnl = (p["exit_price"] - p["entry_price"]) / p["entry_price"] * 100
            reason = p.get("exit_reason", "")
            lines.append(f"| {ticker} | {direction} | ${entry_px} → ${p['exit_price']} | {pnl:+.1f}% | {reason} |")
        else:
            sl = p.get("stop_loss", "")
            tp = p.get("take_profit", "")
            lines.append(f"| {ticker} | {direction} | ${entry_px} | qty={qty} | SL={sl} TP={tp} [{pos_type}] |")
    return "\n".join(lines) + "\n"


def fmt_scheduler(runs: list) -> str:
    if not runs:
        return "今日无调度运行记录（盘前或 Render 未触发）\n"
    lines = []
    errors = []
    for r in runs:
        name = r.get("job_name", "?")
        status = r.get("status", "?")
        duration = r.get("duration_sec", "?")
        summary = (r.get("summary") or "")[:80]
        icon = "✅" if status == "success" else "❌" if status == "error" else "🔄"
        lines.append(f"| {icon} {name} | {status} | {duration}s | {summary} |")
        if status == "error":
            errors.append(f"- **{name}**: {(r.get('error') or 'unknown')[:200]}")
    table = "| Job | Status | Duration | Summary |\n|-----|--------|----------|---------|\n"
    table += "\n".join(lines) + "\n"
    if errors:
        table += "\n**错误详情:**\n" + "\n".join(errors) + "\n"
    return table


# ── 生成复盘 Markdown ────────────────────────────────
def generate_review(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = WEEKDAY_MAP[dt.weekday()]

    print(f"📅 生成 {date_str} ({weekday}) 盘后复盘...")

    # 拉取数据
    print("  拉取 regime...")
    regime = fetch_regime(date_str)
    print("  拉取宝典操作...")
    rot = fetch_rotation_trades(date_str)
    print("  拉取 ED 操作...")
    ed = fetch_ed_trades(date_str)
    print("  拉取下单审计...")
    orders = fetch_order_audit(date_str)
    print("  拉取调度日志...")
    sched = fetch_scheduler_runs(date_str)
    print("  拉取事件信号...")
    signals = fetch_event_signals(date_str)

    # 统计
    n_entries = len(rot["entries"]) + len(ed.get("entries", []))
    n_exits = len(rot["exits"]) + len(ed.get("exits", []))
    n_active = len(rot["active"]) + len(ed.get("active", []))
    n_pending = len(rot.get("pending", []))
    n_errors = sum(1 for r in sched if r.get("status") == "error")
    n_jobs = len(sched)

    md = f"""---
title: "盘后复盘 {date_str}"
date: {date_str}
market_day: {weekday}
regime: {regime.get('regime', 'unknown')}
status: DONE
tags: [daily, review, 复盘]
stats:
  entries: {n_entries}
  exits: {n_exits}
  active: {n_active}
  pending: {n_pending}
  scheduler_errors: {n_errors}
---

# 盘后复盘 {date_str} ({weekday})

> 自动生成 by `scripts/daily_review.py`

---

## 📊 市场环境 & Regime

{fmt_regime(regime)}

---

## 🔄 宝典（周轮动）操作

### 今日新入场 ({len(rot['entries'])}笔)
| 标的 | 方向 | 入场价 | 数量 | 备注 |
|------|------|--------|------|------|
{fmt_position_table(rot['entries'])}
### 今日平仓 ({len(rot['exits'])}笔)
| 标的 | 方向 | 价格 | 盈亏 | 原因 |
|------|------|------|------|------|
{fmt_position_table(rot['exits'], show_pnl=True)}
### 当前持仓 ({len(rot['active'])}笔)
| 标的 | 方向 | 入场价 | 数量 | 备注 |
|------|------|--------|------|------|
{fmt_position_table(rot['active'])}
### 待入场 ({len(rot.get('pending', []))}笔)
| 标的 | 方向 | 目标价 | 数量 | 备注 |
|------|------|--------|------|------|
{fmt_position_table(rot.get('pending', []))}
---

## 🎯 ED（事件驱动）操作

### 今日新入场 ({len(ed.get('entries', []))}笔)
| 标的 | 方向 | 入场价 | 数量 | 备注 |
|------|------|--------|------|------|
{fmt_position_table(ed.get('entries', []))}
### 今日平仓 ({len(ed.get('exits', []))}笔)
| 标的 | 方向 | 价格 | 盈亏 | 原因 |
|------|------|------|------|------|
{fmt_position_table(ed.get('exits', []), show_pnl=True)}
### ED 活跃持仓 ({len(ed.get('active', []))}笔)
| 标的 | 方向 | 入场价 | 数量 | 备注 |
|------|------|--------|------|------|
{fmt_position_table(ed.get('active', []))}
---

## 📡 事件信号 ({len(signals)}条)
"""
    if signals:
        md += "| 标的 | 类型 | 方向 | 置信度 | 摘要 |\n|------|------|------|--------|------|\n"
        for s in signals:
            ticker = s.get("ticker", "?")
            sig_type = s.get("signal_type", "?")
            direction = s.get("direction", "?")
            confidence = s.get("confidence", "?")
            summary = (s.get("summary") or "")[:60]
            md += f"| {ticker} | {sig_type} | {direction} | {confidence} | {summary} |\n"
    else:
        md += "今日无事件信号\n"

    md += f"""
---

## 🤖 调度任务执行 ({n_jobs}个任务, {n_errors}个错误)

{fmt_scheduler(sched)}
---

## ⚠️ 问题与异常
"""
    # 自动标记异常
    issues = []
    if n_errors > 0:
        issues.append(f"- [ ] 调度任务有 {n_errors} 个错误，需排查")
    for p in rot["active"]:
        if not p.get("tiger_order_id") and p.get("tiger_order_status") != "filled":
            issues.append(f"- [ ] {p['ticker']} 无 Tiger 订单 ID，可能未实际下单")
    if not sched:
        issues.append("- [ ] 今日无调度运行记录，检查 Render 是否正常")

    md += "\n".join(issues) if issues else "无自动检测到的异常\n"

    md += f"""

---

## 👁️ 盘后观察
- **持仓总览**: {n_active} 活跃 + {n_pending} 待入场
- **今日操作**: {n_entries} 入场, {n_exits} 出场
- **明日关注**: —
- **策略改进想法**: —
"""
    return md


# ── 写入 Obsidian ────────────────────────────────────
def write_to_obsidian(date_str: str, content: str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = WEEKDAY_MAP[dt.weekday()]
    filename = f"{date_str}-{weekday}.md"
    url = f"{OBS_URL}/vault/04-StockQueen/DAILY/{filename}"

    data = content.encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        "Authorization": f"Bearer {OBS_TOKEN}",
        "Content-Type": "text/markdown",
    })
    try:
        resp = urllib.request.urlopen(req, context=ssl_ctx, timeout=10)
        print(f"✅ 已写入 Obsidian: DAILY/{filename} (HTTP {resp.status})")
    except Exception as e:
        print(f"❌ 写入 Obsidian 失败: {e}")
        # 降级：写到本地
        fallback = f"output/daily_review_{date_str}.md"
        with open(fallback, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"📄 已降级写入本地: {fallback}")


# ── 主入口 ───────────────────────────────────────────
def main():
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        # 默认：NZT 今天对应的美股交易日
        # NZT 09:00+ → 对应当天美股收盘（前一天 US 日期）
        # 简单起见用当前日期
        date_str = datetime.now().strftime("%Y-%m-%d")

    md = generate_review(date_str)
    write_to_obsidian(date_str, md)
    print("🏁 复盘完成")


if __name__ == "__main__":
    main()
