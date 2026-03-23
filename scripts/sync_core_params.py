#!/usr/bin/env python3
"""
自动从代码提取关键参数 → 写入 Obsidian CORE/PARAMS-SNAPSHOT.md
用途：每次改动核心服务后运行，确保 CORE 文档不腐烂。

运行方式：
  python scripts/sync_core_params.py          # 提取 + 写入 Obsidian
  python scripts/sync_core_params.py --check   # 仅对比，不写入（CI 用）
"""

import sys
import os
import json
import urllib.request
import ssl
from datetime import datetime

# 让 import 能找到 app/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OBSIDIAN_BASE = "https://127.0.0.1:28000"
OBSIDIAN_TOKEN = "266d6f82c9a9c630dd313b091b772ee13c747b5698fb6c105e559f2109a2819d"
SNAPSHOT_PATH = "04-StockQueen/CORE/PARAMS-SNAPSHOT.md"
SNAPSHOT_JSON = "scripts/params_snapshot.json"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def extract_all_params():
    """从代码提取所有关键参数，返回结构化字典"""
    params = {}

    # --- 1. RotationConfig ---
    from app.config.rotation_watchlist import RotationConfig
    rc = RotationConfig()
    params["rotation"] = {
        "TOP_N": rc.TOP_N,
        "HOLDING_BONUS": rc.HOLDING_BONUS,
        "VOL_PENALTY": rc.VOL_PENALTY,
        "SCORE_WEIGHTED_ALLOC": rc.SCORE_WEIGHTED_ALLOC,
        "MAX_SECTOR_CONCENTRATION": rc.MAX_SECTOR_CONCENTRATION,
        "MOMENTUM_WEIGHTS": {k: list(v) for k, v in rc.MOMENTUM_WEIGHTS.items()},
        "MIN_SCORE_BY_REGIME": rc.MIN_SCORE_BY_REGIME,
        "REGIME_CONFIRM_DAYS": rc.REGIME_CONFIRM_DAYS,
        "ENTRY_MA_PERIOD": rc.ENTRY_MA_PERIOD,
        "ENTRY_VOL_PERIOD": rc.ENTRY_VOL_PERIOD,
        "ENTRY_MAX_WAIT_DAYS": rc.ENTRY_MAX_WAIT_DAYS,
        "ATR_PERIOD": rc.ATR_PERIOD,
        "ATR_TARGET_BY_REGIME": rc.ATR_TARGET_BY_REGIME,
        "ATR_STOP_BY_REGIME": rc.ATR_STOP_BY_REGIME,
        "TRAILING_STOP_ENABLED": rc.TRAILING_STOP_ENABLED,
        "TRAILING_STOP_ATR_MULT": rc.TRAILING_STOP_ATR_MULT,
        "TRAILING_ACTIVATE_ATR": rc.TRAILING_ACTIVATE_ATR,
        "AUTO_EXECUTE_ORDERS": rc.AUTO_EXECUTE_ORDERS,
        "HEDGE_OVERLAY_ENABLED": rc.HEDGE_OVERLAY_ENABLED,
        "HEDGE_ALLOC_BY_REGIME": rc.HEDGE_ALLOC_BY_REGIME,
        "USE_DYNAMIC_UNIVERSE": rc.USE_DYNAMIC_UNIVERSE,
        "UNIVERSE_MIN_MARKET_CAP": rc.UNIVERSE_MIN_MARKET_CAP,
        "UNIVERSE_QUALITY_GATE": rc.UNIVERSE_QUALITY_GATE,
        "USE_ML_ENHANCE": rc.USE_ML_ENHANCE,
        "ML_RERANK_POOL": rc.ML_RERANK_POOL,
    }

    # --- 2. Factor Weights ---
    from app.services.multi_factor_scorer import FACTOR_WEIGHTS, LARGECAP_FACTOR_WEIGHTS
    params["factor_weights"] = {
        "default": FACTOR_WEIGHTS,
        "largecap": LARGECAP_FACTOR_WEIGHTS,
    }

    # --- 3. Allocation Matrix ---
    from app.services.portfolio_manager import ALLOCATION_MATRIX, VIX_DELEVERAGE_LEVELS
    params["portfolio"] = {
        "ALLOCATION_MATRIX": ALLOCATION_MATRIX,
        "VIX_DELEVERAGE_LEVELS": [[t, m] for t, m in VIX_DELEVERAGE_LEVELS],
    }

    # --- 4. Mean Reversion ---
    from app.services.mean_reversion_service import MRC
    params["mean_reversion"] = {
        "RSI_ENTRY_THRESHOLD": MRC.RSI_ENTRY_THRESHOLD,
        "BB_ENTRY_THRESHOLD": MRC.BB_ENTRY_THRESHOLD,
        "VOLUME_FACTOR": MRC.VOLUME_FACTOR,
        "RSI_EXIT_THRESHOLD": MRC.RSI_EXIT_THRESHOLD,
        "BB_EXIT_THRESHOLD": MRC.BB_EXIT_THRESHOLD,
        "MAX_HOLD_DAYS": MRC.MAX_HOLD_DAYS,
        "ATR_STOP_MULT": MRC.ATR_STOP_MULT,
        "MAX_POSITIONS": MRC.MAX_POSITIONS,
        "ACTIVE_REGIMES": sorted(MRC.ACTIVE_REGIMES),
    }

    # --- 5. Event Driven ---
    from app.services.event_driven_service import EDC
    params["event_driven"] = {
        "ENTRY_DAYS_BEFORE_EARNINGS": EDC.ENTRY_DAYS_BEFORE_EARNINGS,
        "MIN_BEAT_RATE": EDC.MIN_BEAT_RATE,
        "MIN_QUARTERS_DATA": EDC.MIN_QUARTERS_DATA,
        "MIN_EPS_SURPRISE_PCT": EDC.MIN_EPS_SURPRISE_PCT,
        "ATR_STOP_MULT": EDC.ATR_STOP_MULT,
        "MAX_POSITIONS": EDC.MAX_POSITIONS,
        "ACTIVE_REGIMES": sorted(EDC.ACTIVE_REGIMES),
    }

    return params


def params_to_markdown(params):
    """将参数字典转为 Markdown 表格"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "---",
        'title: "参数快照（代码自动生成）"',
        f"generated: {now}",
        "status: AUTO_GENERATED",
        "tags: [core, params, auto]",
        "---",
        "",
        "# 参数快照（代码自动提取）",
        "",
        f"> 自动生成于 {now}，来源：`python scripts/sync_core_params.py`",
        "> **本文件由脚本覆盖，不要手动编辑。**",
        "> AI 读取 CORE 文档时，以本文件数值为准。若 CORE 文档与此处不一致，CORE 文档已过时。",
        "",
    ]

    # --- Rotation ---
    r = params["rotation"]
    lines += [
        "## 宝典 V4 核心参数",
        "",
        "| 参数 | 值 |",
        "|------|-----|",
        f"| TOP_N | {r['TOP_N']} |",
        f"| HOLDING_BONUS | {r['HOLDING_BONUS']} |",
        f"| MAX_SECTOR_CONCENTRATION | {r['MAX_SECTOR_CONCENTRATION']} |",
        f"| SCORE_WEIGHTED_ALLOC | {r['SCORE_WEIGHTED_ALLOC']} |",
        f"| REGIME_CONFIRM_DAYS | {r['REGIME_CONFIRM_DAYS']} |",
        f"| ENTRY_MA_PERIOD | {r['ENTRY_MA_PERIOD']} |",
        f"| ENTRY_VOL_PERIOD | {r['ENTRY_VOL_PERIOD']} |",
        f"| ENTRY_MAX_WAIT_DAYS | {r['ENTRY_MAX_WAIT_DAYS']} |",
        f"| AUTO_EXECUTE_ORDERS | {r['AUTO_EXECUTE_ORDERS']} |",
        f"| HEDGE_OVERLAY_ENABLED | {r['HEDGE_OVERLAY_ENABLED']} |",
        f"| USE_DYNAMIC_UNIVERSE | {r['USE_DYNAMIC_UNIVERSE']} |",
        f"| USE_ML_ENHANCE | {r['USE_ML_ENHANCE']} |",
        f"| ML_RERANK_POOL | {r['ML_RERANK_POOL']} |",
        "",
    ]

    # Momentum weights
    lines += ["### 动量权重（Regime自适应）", "", "| Regime | 1W | 1M | 3M |", "|--------|-----|-----|-----|"]
    for regime, w in r["MOMENTUM_WEIGHTS"].items():
        lines.append(f"| {regime} | {w[0]} | {w[1]} | {w[2]} |")
    lines.append("")

    # Min score
    lines += ["### 入场最低分门控", "", "| Regime | 最低分 |", "|--------|-------|"]
    for regime, s in r["MIN_SCORE_BY_REGIME"].items():
        lines.append(f"| {regime} | {s} |")
    lines.append("")

    # ATR
    lines += ["### ATR 止盈止损", "", "| Regime | 止损倍数 | 止盈倍数 |", "|--------|---------|---------|"]
    for regime in r["ATR_STOP_BY_REGIME"]:
        lines.append(f"| {regime} | {r['ATR_STOP_BY_REGIME'][regime]} | {r['ATR_TARGET_BY_REGIME'][regime]} |")
    lines += [
        "",
        f"| Trailing 激活 | {r['TRAILING_ACTIVATE_ATR']} x ATR |",
        f"| Trailing 距离 | {r['TRAILING_STOP_ATR_MULT']} x ATR |",
        "",
    ]

    # Hedge
    lines += ["### Hedge Overlay", "", "| Regime | 对冲比例 |", "|--------|---------|"]
    for regime, h in r["HEDGE_ALLOC_BY_REGIME"].items():
        lines.append(f"| {regime} | {h:.0%} |")
    lines.append("")

    # --- Factor Weights ---
    fw = params["factor_weights"]
    lines += ["## 多因子评分权重", "", "| 因子 | 中盘股 | 大盘股 |", "|------|--------|--------|"]
    for f in fw["default"]:
        lines.append(f"| {f} | {fw['default'][f]} | {fw['largecap'].get(f, '-')} |")
    lines.append("")

    # --- Allocation Matrix ---
    p = params["portfolio"]
    lines += ["## 资金分配矩阵", "", "| Regime | V4 | MR | ED |", "|--------|-----|-----|-----|"]
    for regime, alloc in p["ALLOCATION_MATRIX"].items():
        lines.append(f"| {regime} | {alloc['v4']:.0%} | {alloc['mean_reversion']:.0%} | {alloc['event_driven']:.0%} |")
    lines.append("")

    lines += ["### VIX 降杠杆", "", "| VIX阈值 | 乘数 |", "|---------|------|"]
    for t, m in p["VIX_DELEVERAGE_LEVELS"]:
        lines.append(f"| > {t} | x{m} |")
    lines.append("")

    # --- MR ---
    mr = params["mean_reversion"]
    lines += [
        "## 均值回归参数", "",
        "| 参数 | 值 |", "|------|-----|",
        f"| RSI_ENTRY | {mr['RSI_ENTRY_THRESHOLD']} |",
        f"| BB_ENTRY | {mr['BB_ENTRY_THRESHOLD']} |",
        f"| VOLUME_FACTOR | {mr['VOLUME_FACTOR']} |",
        f"| RSI_EXIT | {mr['RSI_EXIT_THRESHOLD']} |",
        f"| MAX_HOLD_DAYS | {mr['MAX_HOLD_DAYS']} |",
        f"| ATR_STOP_MULT | {mr['ATR_STOP_MULT']} |",
        f"| MAX_POSITIONS | {mr['MAX_POSITIONS']} |",
        f"| ACTIVE_REGIMES | {mr['ACTIVE_REGIMES']} |",
        "",
    ]

    # --- ED ---
    ed = params["event_driven"]
    lines += [
        "## 事件驱动参数", "",
        "| 参数 | 值 |", "|------|-----|",
        f"| ENTRY_DAYS_BEFORE | {ed['ENTRY_DAYS_BEFORE_EARNINGS']} |",
        f"| MIN_BEAT_RATE | {ed['MIN_BEAT_RATE']} |",
        f"| MIN_SURPRISE | {ed['MIN_EPS_SURPRISE_PCT']} |",
        f"| ATR_STOP_MULT | {ed['ATR_STOP_MULT']} |",
        f"| MAX_POSITIONS | {ed['MAX_POSITIONS']} |",
        f"| ACTIVE_REGIMES | {ed['ACTIVE_REGIMES']} |",
        "",
    ]

    return "\n".join(lines)


def write_to_obsidian(content):
    url = f"{OBSIDIAN_BASE}/vault/{SNAPSHOT_PATH}"
    data = content.encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Authorization", f"Bearer {OBSIDIAN_TOKEN}")
    req.add_header("Content-Type", "text/markdown")
    resp = urllib.request.urlopen(req, context=ctx)
    print(f"  Written to Obsidian: {SNAPSHOT_PATH} ({resp.status})")


def check_drift(params):
    """对比当前参数与上次快照，报告变化"""
    if not os.path.exists(SNAPSHOT_JSON):
        print("  No previous snapshot found, first run.")
        return []

    with open(SNAPSHOT_JSON, "r") as f:
        old = json.load(f)

    diffs = []
    for section in params:
        if section not in old:
            diffs.append(f"NEW section: {section}")
            continue
        for key in params[section]:
            old_val = old[section].get(key)
            new_val = params[section][key]
            if old_val != new_val:
                diffs.append(f"  CHANGED {section}.{key}: {old_val} → {new_val}")
    return diffs


def main():
    check_only = "--check" in sys.argv

    print("Extracting parameters from code...")
    params = extract_all_params()

    # Check drift
    diffs = check_drift(params)
    if diffs:
        print(f"\n[!] {len(diffs)} parameter(s) changed since last snapshot:")
        for d in diffs:
            print(d)
    else:
        print("\n[OK] No parameter drift detected.")

    if check_only:
        if diffs:
            print("\n[FAIL] Drift detected. Run without --check to update snapshot.")
            sys.exit(1)
        sys.exit(0)

    # Save JSON snapshot
    with open(SNAPSHOT_JSON, "w") as f:
        json.dump(params, f, indent=2, default=str)
    print(f"  Saved JSON: {SNAPSHOT_JSON}")

    # Generate and write Markdown
    md = params_to_markdown(params)
    try:
        write_to_obsidian(md)
    except Exception as e:
        print(f"  [WARN] Obsidian write failed (offline?): {e}")
        # Still save the markdown locally
        local_path = "scripts/params_snapshot.md"
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"  Saved local fallback: {local_path}")

    print("\n[OK] Done. CORE/PARAMS-SNAPSHOT.md updated.")


if __name__ == "__main__":
    main()
