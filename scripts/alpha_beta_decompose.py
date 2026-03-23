#!/usr/bin/env python3
"""
alpha_beta_decompose.py
─────────────────────────────────────────────────────────
把宝典V4的回报拆解为：
  V4_return(t) = alpha + beta × SPY_return(t) + ε(t)

分析维度：
  - 全期（2020-2024 所有 WF 测试窗口合并）
  - 分窗口（W1~W6 单独回归）
  - 分 Regime（bull / bear / bear_recovery 子集回归）

输出：
  - 终端报告
  - Supabase alpha_beta_results 表
  - GitHub Step Summary
  - 本地 JSON

用法：
  python scripts/alpha_beta_decompose.py
  python scripts/alpha_beta_decompose.py --top-n 3 --holding-bonus 0.5
"""

import asyncio
import argparse
import json
import os
import sys
import datetime
from pathlib import Path
from typing import Optional

import numpy as np

# ── 确保 repo 根目录在 Python 路径中 ────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── WF 窗口定义（对齐 walk_forward_v5_full.py）───────────────────────────
WINDOWS = [
    {"name": "W1", "test_start": "2020-01-01", "test_end": "2020-12-31", "regime": "bear_recovery"},
    {"name": "W2", "test_start": "2021-01-01", "test_end": "2021-12-31", "regime": "bull"},
    {"name": "W3", "test_start": "2022-01-01", "test_end": "2022-12-31", "regime": "bear"},
    {"name": "W4", "test_start": "2023-01-01", "test_end": "2023-12-31", "regime": "bull"},
    {"name": "W5", "test_start": "2024-01-01", "test_end": "2024-12-31", "regime": "bull"},
    {"name": "W6", "test_start": "2025-01-01", "test_end": "2025-12-31", "regime": "bull"},
]

# ── OLS 回归核心 ─────────────────────────────────────────────────────────────

def compute_alpha_beta(v4_returns: list, spy_returns: list, period: str = "") -> Optional[dict]:
    """
    OLS: V4_weekly = alpha_weekly + beta × SPY_weekly + ε
    返回年化统计指标。
    """
    if len(v4_returns) < 8:
        return None

    v4  = np.array(v4_returns, dtype=float)
    spy = np.array(spy_returns, dtype=float)

    # OLS via numpy lstsq
    A = np.vstack([np.ones(len(spy)), spy]).T
    coeffs, _, _, _ = np.linalg.lstsq(A, v4, rcond=None)
    alpha_weekly, beta = float(coeffs[0]), float(coeffs[1])

    # 预测 & 残差
    y_pred   = alpha_weekly + beta * spy
    residuals = v4 - y_pred

    # R²
    ss_res  = float(np.sum(residuals ** 2))
    ss_tot  = float(np.sum((v4 - np.mean(v4)) ** 2))
    r_sq    = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # 年化 alpha（复利）
    alpha_ann = float((1 + alpha_weekly) ** 52 - 1)

    # Tracking Error（残差年化标准差）
    te = float(np.std(residuals) * np.sqrt(52))

    # Information Ratio（超额收益 / 超额波动，年化）
    excess = v4 - spy
    ir = float(np.mean(excess) / np.std(excess) * np.sqrt(52)) if np.std(excess) > 0 else 0.0

    # 年化收益
    v4_ann  = float((1 + np.mean(v4))  ** 52 - 1)
    spy_ann = float((1 + np.mean(spy)) ** 52 - 1)

    return {
        "period":          period,
        "n_weeks":         len(v4_returns),
        "alpha_ann":       round(alpha_ann,      4),
        "beta":            round(beta,           4),
        "r_squared":       round(r_sq,           4),
        "tracking_error":  round(te,             4),
        "info_ratio":      round(ir,             4),
        "v4_ann_return":   round(v4_ann,         4),
        "spy_ann_return":  round(spy_ann,        4),
        "excess_return":   round(v4_ann - spy_ann, 4),
    }


# ── 回测执行 ─────────────────────────────────────────────────────────────────

async def run_window_backtest(window: dict, top_n: int, holding_bonus: float) -> Optional[dict]:
    """跑单个窗口的 V4 回测，返回 weekly_details。"""
    try:
        from app.services.rotation_service import run_rotation_backtest
        result = await run_rotation_backtest(
            start_date=window["test_start"],
            end_date=window["test_end"],
            top_n=top_n,
            holding_bonus=holding_bonus,
        )
        if "error" in result:
            print(f"  ⚠️  {window['name']}: {result['error']}")
            return None
        return result
    except Exception as e:
        print(f"  ❌ {window['name']} 回测失败: {e}")
        return None


# ── 主分析 ───────────────────────────────────────────────────────────────────

async def analyze(top_n: int = 3, holding_bonus: float = 0.5) -> dict:
    print(f"\n🔍 Alpha/Beta 拆解分析 (top_n={top_n}, holding_bonus={holding_bonus})")
    print("=" * 60)

    all_v4, all_spy, all_regime = [], [], []
    window_results = []

    for w in WINDOWS:
        print(f"\n  运行 {w['name']} ({w['test_start']} ~ {w['test_end']}) ...")
        bt = await run_window_backtest(w, top_n, holding_bonus)
        if not bt:
            continue

        details = bt.get("weekly_details", [])
        if not details:
            print(f"  ⚠️  {w['name']}: 无 weekly_details")
            continue

        v4_rets  = [d["return_pct"] / 100.0     for d in details]
        spy_rets = [d["spy_return_pct"] / 100.0 for d in details]
        regimes  = [d.get("regime", w["regime"]) for d in details]

        all_v4.extend(v4_rets)
        all_spy.extend(spy_rets)
        all_regime.extend(regimes)

        stats = compute_alpha_beta(v4_rets, spy_rets, period=f"{w['test_start']}~{w['test_end']}")
        if stats:
            stats["scope"] = w["name"]
            stats["wf_regime"] = w["regime"]
            window_results.append(stats)
            print(f"  ✓  alpha={stats['alpha_ann']:+.1%}  beta={stats['beta']:.2f}  "
                  f"R²={stats['r_squared']:.2f}  IR={stats['info_ratio']:.2f}")

    if not all_v4:
        print("❌ 无有效数据")
        sys.exit(1)

    # 全期回归
    full = compute_alpha_beta(all_v4, all_spy, period="2020-2025 全期")
    full["scope"] = "full"

    # 分 Regime 回归
    regime_results = []
    for regime_label in ["bull", "bear", "bear_recovery"]:
        idx = [i for i, r in enumerate(all_regime) if r == regime_label]
        if len(idx) < 8:
            continue
        v4_sub  = [all_v4[i]  for i in idx]
        spy_sub = [all_spy[i] for i in idx]
        stats = compute_alpha_beta(v4_sub, spy_sub,
                                   period=f"regime={regime_label}({len(idx)}周)")
        if stats:
            stats["scope"] = regime_label
            regime_results.append(stats)

    return {
        "full":           full,
        "by_window":      window_results,
        "by_regime":      regime_results,
        "analysis_timestamp": datetime.datetime.utcnow().isoformat(),
    }


# ── 报告打印 ─────────────────────────────────────────────────────────────────

def print_report(result: dict):
    SEP = "=" * 68
    full = result["full"]

    print(f"\n{SEP}")
    print("📊  Alpha / Beta 拆解报告  —  宝典V4 vs SPY")
    print(SEP)

    print("\n【全期（2020-2025 所有 WF 测试窗口）】")
    print(f"  样本周数:      {full['n_weeks']}")
    print(f"  年化 Alpha:    {full['alpha_ann']:>+.2%}  ← 不依赖市场的纯超额收益")
    print(f"  市场 Beta:     {full['beta']:>+.3f}      ← 和 SPY 的同步程度")
    print(f"  R²:            {full['r_squared']:>.3f}      ← 多少回报由 SPY 解释")
    print(f"  Tracking Err:  {full['tracking_error']:.2%}  (年化)")
    print(f"  Info Ratio:    {full['info_ratio']:>+.3f}")
    print(f"  V4 年化回报:   {full['v4_ann_return']:>+.2%}")
    print(f"  SPY 年化回报:  {full['spy_ann_return']:>+.2%}")
    print(f"  年化超额:      {full['excess_return']:>+.2%}")

    # 解读
    print("\n【解读】")
    beta = full["beta"]
    r2   = full["r_squared"]
    a    = full["alpha_ann"]
    if beta > 1.2:
        print(f"  ⚠️  Beta={beta:.2f} > 1.2：策略对市场有放大效应（杠杆 beta），涨跌均放大")
    elif beta > 0.8:
        print(f"  🔶 Beta={beta:.2f}：接近市场，部分收益由市场驱动")
    else:
        print(f"  ✅ Beta={beta:.2f}：低市场相关性，选股驱动为主")
    if r2 > 0.5:
        print(f"  ⚠️  R²={r2:.2f}：超过50%的回报可被 SPY 解释，市场 Beta 影响显著")
    else:
        print(f"  ✅ R²={r2:.2f}：SPY 解释力弱，策略独立性强")
    if a > 0.05:
        print(f"  ✅ 年化 Alpha={a:+.2%}：策略存在显著正 Alpha")
    elif a > 0:
        print(f"  🔶 年化 Alpha={a:+.2%}：Alpha 为正但偏小")
    else:
        print(f"  ❌ 年化 Alpha={a:+.2%}：Alpha 为负，超额收益主要来自 Beta 暴露")

    # 分窗口
    print("\n【分窗口回归】")
    print(f"  {'窗口':<5} {'Alpha':>8} {'Beta':>7} {'R²':>6} {'IR':>7} {'Regime'}")
    print("  " + "-" * 52)
    for w in result["by_window"]:
        print(f"  {w['scope']:<5} {w['alpha_ann']:>+8.1%} {w['beta']:>7.3f} "
              f"{w['r_squared']:>6.3f} {w['info_ratio']:>7.3f}  {w.get('wf_regime','')}")

    # 分 Regime
    if result["by_regime"]:
        print("\n【分 Regime 回归】")
        print(f"  {'Regime':<16} {'周数':>5} {'Alpha':>8} {'Beta':>7} {'R²':>6} {'IR':>7}")
        print("  " + "-" * 56)
        for r in result["by_regime"]:
            print(f"  {r['scope']:<16} {r['n_weeks']:>5} {r['alpha_ann']:>+8.1%} "
                  f"{r['beta']:>7.3f} {r['r_squared']:>6.3f} {r['info_ratio']:>7.3f}")

    print(f"\n{SEP}\n")


# ── Supabase 写入 ─────────────────────────────────────────────────────────────

def save_to_supabase(result: dict, run_id: str):
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("⚠️  未配置 Supabase，跳过写入")
        return

    try:
        from supabase import create_client
        sb   = create_client(url, key)
        now  = datetime.datetime.utcnow().isoformat()

        rows = []
        for entry in [result["full"]] + result["by_window"] + result["by_regime"]:
            rows.append({
                "run_id":         run_id,
                "scope":          entry["scope"],
                "period":         entry.get("period", ""),
                "n_weeks":        entry["n_weeks"],
                "alpha_ann":      entry["alpha_ann"],
                "beta":           entry["beta"],
                "r_squared":      entry["r_squared"],
                "tracking_error": entry["tracking_error"],
                "info_ratio":     entry["info_ratio"],
                "v4_ann_return":  entry["v4_ann_return"],
                "spy_ann_return": entry["spy_ann_return"],
                "excess_return":  entry["excess_return"],
                "created_at":     now,
            })

        sb.table("alpha_beta_results").insert(rows).execute()
        print(f"✅ Supabase 写入成功：{len(rows)} 条 (run_id={run_id})")
    except Exception as e:
        print(f"❌ Supabase 写入失败: {e}")
        raise


# ── GitHub Step Summary ───────────────────────────────────────────────────────

def write_step_summary(result: dict):
    sf = os.environ.get("GITHUB_STEP_SUMMARY")
    if not sf:
        return

    full = result["full"]
    beta = full["beta"]
    r2   = full["r_squared"]
    a    = full["alpha_ann"]

    if beta > 1.2:
        verdict = "⚠️ 高 Beta（放大市场）"
    elif r2 > 0.5:
        verdict = "🔶 中度市场依赖"
    elif a > 0.05:
        verdict = "✅ 存在显著正 Alpha"
    else:
        verdict = "🔶 Alpha 偏弱"

    lines = [
        "## 📊 Alpha / Beta 拆解报告",
        "",
        f"**判断：{verdict}**",
        "",
        "| 指标 | 全期值 | 说明 |",
        "|------|--------|------|",
        f"| 年化 Alpha | {a:+.2%} | 不依赖市场的纯超额 |",
        f"| 市场 Beta  | {beta:.3f}  | vs SPY 的同步度 |",
        f"| R²         | {r2:.3f}  | SPY 对收益的解释力 |",
        f"| Info Ratio | {full['info_ratio']:.3f}  | 超额收益稳定性 |",
        f"| 年化超额   | {full['excess_return']:+.2%} | V4 - SPY |",
        "",
        "### 分窗口 Alpha",
        "",
        "| 窗口 | Alpha | Beta | R² | Regime |",
        "|------|-------|------|-----|--------|",
    ]
    for w in result["by_window"]:
        lines.append(f"| {w['scope']} | {w['alpha_ann']:+.1%} | {w['beta']:.2f} | {w['r_squared']:.2f} | {w.get('wf_regime','')} |")

    with open(sf, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ── 主入口 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Alpha/Beta 拆解分析")
    parser.add_argument("--top-n",         type=int,   default=3,   help="V4 top_n 参数")
    parser.add_argument("--holding-bonus", type=float, default=0.5, help="holding_bonus 参数")
    args = parser.parse_args()

    result = asyncio.run(analyze(top_n=args.top_n, holding_bonus=args.holding_bonus))

    print_report(result)

    # 保存本地 JSON
    out_dir = Path(__file__).parent / "stress_test_results"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"alpha_beta_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"💾 本地保存: {out_path.name}")

    run_id = os.environ.get("GITHUB_RUN_ID", f"local_{ts}")
    save_to_supabase(result, run_id)
    write_step_summary(result)


if __name__ == "__main__":
    main()
