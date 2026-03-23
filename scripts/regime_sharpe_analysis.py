#!/usr/bin/env python3
"""
regime_sharpe_analysis.py
─────────────────────────
分析 Walk-Forward 各窗口在不同 Regime 下的 Sharpe 表现
结果写入 Supabase regime_sharpe_results 表，可在后台历史记录中查询

用法：
  python scripts/regime_sharpe_analysis.py
  python scripts/regime_sharpe_analysis.py --file scripts/stress_test_results/walk_forward_v5_full_20260322_004937.json
"""

import json
import os
import sys
import datetime
import statistics
import argparse
from pathlib import Path
from typing import Optional

# ── Regime 标注（基于 SPY 年度表现 + 宏观背景）──────────────────────────────
# 规则：年度回报 < -10% → bear；> +10% → bull；其余 → sideways
# W1 特殊：全年+18% 但 Q1 崩盘 -34%，标注为 bear_recovery
WINDOW_REGIMES = {
    "W1": {
        "test_period": "2020",
        "regime": "bear_recovery",
        "spy_annual_return": 0.184,
        "vix_avg": 29.0,
        "description": "COVID崩盘+V型反弹（Q1熊市-34%，Q2-Q4强牛）",
    },
    "W2": {
        "test_period": "2021",
        "regime": "bull",
        "spy_annual_return": 0.287,
        "vix_avg": 19.7,
        "description": "超级牛市（流动性泛滥+疫后复苏）",
    },
    "W3": {
        "test_period": "2022",
        "regime": "bear",
        "spy_annual_return": -0.183,
        "vix_avg": 25.6,
        "description": "熊市（联储激进加息，通胀危机）",
    },
    "W4": {
        "test_period": "2023",
        "regime": "bull",
        "spy_annual_return": 0.265,
        "vix_avg": 17.0,
        "description": "牛市（AI元年，通胀回落）",
    },
    "W5": {
        "test_period": "2024",
        "regime": "bull",
        "spy_annual_return": 0.253,
        "vix_avg": 15.5,
        "description": "牛市（AI加速，降息预期）",
    },
    "W6": {
        "test_period": "2025",
        "regime": "bull",
        "spy_annual_return": 0.230,  # 估计值，2025全年
        "vix_avg": 18.0,
        "description": "牛市（AI普及+降息落地）",
    },
}

STRATEGIES = ["v4", "mr", "ed", "portfolio"]


# ── 数据加载 ────────────────────────────────────────────────────────────────

def find_latest_wf_file() -> Optional[Path]:
    base = Path(__file__).parent / "stress_test_results"
    files = sorted(base.glob("walk_forward_v5_full_*.json"), reverse=True)
    if not files:
        files = sorted(base.glob("walk_forward_v5*.json"), reverse=True)
    return files[0] if files else None


def load_wf_data(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── 分析核心 ────────────────────────────────────────────────────────────────

def analyze_regime_sharpe(wf_data: dict) -> dict:
    window_results = wf_data.get("window_results", [])

    records = []
    for wr in window_results:
        wname = wr["window"]
        regime_info = WINDOW_REGIMES.get(wname, {})
        regime = regime_info.get("regime", "unknown")

        for strategy in STRATEGIES:
            s = wr.get("strategies", {}).get(strategy)
            if not s:
                continue
            records.append({
                "window": wname,
                "test_period": wr.get("test_period", regime_info.get("test_period", "")),
                "strategy": strategy,
                "regime": regime,
                "spy_annual_return": regime_info.get("spy_annual_return"),
                "vix_avg": regime_info.get("vix_avg"),
                "regime_description": regime_info.get("description", ""),
                "oos_sharpe": s.get("oos_sharpe"),
                "oos_cumulative_return": s.get("oos_cumulative_return"),
                "oos_max_drawdown": s.get("oos_max_drawdown"),
                "is_sharpe": s.get("is_sharpe"),
                "overfitting_ratio": s.get("overfitting_ratio"),
            })

    # 分组汇总：strategy × regime
    summary = {}
    regime_groups: dict[tuple, list] = {}
    for r in records:
        key = (r["strategy"], r["regime"])
        regime_groups.setdefault(key, []).append(r)

    for (strategy, regime), rows in regime_groups.items():
        sharpes  = [r["oos_sharpe"]            for r in rows if r["oos_sharpe"] is not None]
        returns  = [r["oos_cumulative_return"]  for r in rows if r["oos_cumulative_return"] is not None]
        drawdowns= [r["oos_max_drawdown"]       for r in rows if r["oos_max_drawdown"] is not None]

        summary[f"{strategy}_{regime}"] = {
            "strategy": strategy,
            "regime": regime,
            "n_windows": len(rows),
            "avg_oos_sharpe":    round(statistics.mean(sharpes),   4) if sharpes   else None,
            "min_oos_sharpe":    round(min(sharpes),               4) if sharpes   else None,
            "max_oos_sharpe":    round(max(sharpes),               4) if sharpes   else None,
            "avg_oos_return":    round(statistics.mean(returns),   4) if returns   else None,
            "avg_max_drawdown":  round(statistics.mean(drawdowns), 4) if drawdowns else None,
            "windows": [r["window"] for r in rows],
        }

    # Alpha 判断
    bull_s    = summary.get("v4_bull",          {}).get("avg_oos_sharpe")
    bear_s    = summary.get("v4_bear",          {}).get("avg_oos_sharpe")
    recov_s   = summary.get("v4_bear_recovery", {}).get("avg_oos_sharpe")

    verdict = "insufficient_data"
    bull_bear_ratio = None
    if bull_s is not None and bear_s is not None and bear_s != 0:
        bull_bear_ratio = round(bull_s / bear_s, 2)
        if bull_bear_ratio > 3:
            verdict = "regime_dependent"       # 主要吃牛市 Beta
        elif bull_bear_ratio > 1.5:
            verdict = "moderate_regime_bias"   # 有 Alpha，牛市加成
        else:
            verdict = "robust_alpha"           # 跨 Regime 均稳定

    return {
        "records": records,
        "summary": summary,
        "alpha_verdict": verdict,
        "bull_bear_ratio": bull_bear_ratio,
        "analysis_timestamp": datetime.datetime.utcnow().isoformat(),
        "source_file": "",
    }


# ── 报告打印 ────────────────────────────────────────────────────────────────

def print_report(result: dict):
    SEP = "=" * 72
    print(f"\n{SEP}")
    print("📊  Regime 分段 Sharpe 分析报告")
    print(SEP)

    # 窗口标注
    print("\n【窗口 Regime 标注】")
    print(f"  {'窗口':<5} {'测试期':<7} {'Regime':<16} {'SPY年回报':>10}  描述")
    print("  " + "-" * 68)
    for wname, info in WINDOW_REGIMES.items():
        if wname not in {r["window"] for r in result["records"]}:
            continue
        print(f"  {wname:<5} {info['test_period']:<7} {info['regime']:<16} "
              f"{info['spy_annual_return']:>+9.1%}  {info['description']}")

    # 各策略 × Regime 汇总
    regimes_order = ["bull", "bear_recovery", "bear"]
    print()
    for strategy in STRATEGIES:
        rows = []
        for regime in regimes_order:
            s = result["summary"].get(f"{strategy}_{regime}")
            if s:
                rows.append(s)
        if not rows:
            continue
        print(f"\n── {strategy.upper()} ──")
        print(f"  {'Regime':<16} {'窗口':<14} {'均值Sharpe':>11} {'最低':>8} {'最高':>8} {'均值回报':>9}")
        print("  " + "-" * 68)
        for s in rows:
            ret_str = f"{s['avg_oos_return']:>+.1%}" if s["avg_oos_return"] is not None else "   N/A"
            print(f"  {s['regime']:<16} {str(s['windows']):<14} "
                  f"{s['avg_oos_sharpe']:>+11.3f} "
                  f"{s['min_oos_sharpe']:>+8.3f} "
                  f"{s['max_oos_sharpe']:>+8.3f} "
                  f"{ret_str:>9}")

    # Alpha 判断
    print(f"\n{'─'*72}")
    verdict_map = {
        "regime_dependent":     "⚠️   高度 Regime 依赖 — 主要吃牛市 Beta，需加 Regime Filter",
        "moderate_regime_bias": "🔶  中度 Regime 依赖 — 有 Alpha，牛市有额外加成",
        "robust_alpha":         "✅  策略稳健 — 跨 Regime 均有表现，真实 Alpha 较高",
        "insufficient_data":    "❓  数据不足，无法判断",
    }
    v = result["alpha_verdict"]
    ratio = result["bull_bear_ratio"]
    print(f"【Alpha / Beta 判断】 {verdict_map.get(v, v)}")
    if ratio is not None:
        print(f"  牛市均值 Sharpe / 熊市均值 Sharpe = {ratio:.2f}x")
    print(SEP + "\n")


# ── Supabase 写入 ───────────────────────────────────────────────────────────

def save_to_supabase(result: dict, source_file: str):
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        print("⚠️  未配置 Supabase 环境变量，跳过写入")
        return

    try:
        from supabase import create_client
        sb = create_client(supabase_url, supabase_key)

        run_id = os.environ.get("GITHUB_RUN_ID", f"local_{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
        now    = datetime.datetime.utcnow().isoformat()

        rows = []
        for s in result["summary"].values():
            rows.append({
                "run_id":           run_id,
                "strategy":         s["strategy"],
                "regime":           s["regime"],
                "n_windows":        s["n_windows"],
                "avg_oos_sharpe":   s["avg_oos_sharpe"],
                "min_oos_sharpe":   s["min_oos_sharpe"],
                "max_oos_sharpe":   s["max_oos_sharpe"],
                "avg_oos_return":   s["avg_oos_return"],
                "avg_max_drawdown": s["avg_max_drawdown"],
                "windows":          s["windows"],
                "source_file":      source_file,
                "created_at":       now,
            })

        sb.table("regime_sharpe_results").insert(rows).execute()
        print(f"✅ Supabase 写入成功：{len(rows)} 条记录 (run_id={run_id})")

    except Exception as e:
        print(f"❌ Supabase 写入失败: {e}")
        raise


# ── GitHub Step Summary ─────────────────────────────────────────────────────

def write_step_summary(result: dict):
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return

    bull     = result["summary"].get("v4_bull",          {})
    bear     = result["summary"].get("v4_bear",          {})
    recovery = result["summary"].get("v4_bear_recovery", {})

    lines = [
        "## 📊 Regime 分段 Sharpe 分析",
        "",
        "### 宝典 V4（v4）各市场环境表现",
        "",
        "| Regime | 覆盖窗口 | 均值 OOS Sharpe | 最低 | 最高 | 均值回报 |",
        "|--------|---------|----------------|------|------|---------|",
    ]
    for label, data in [("🐂 牛市 (bull)", bull), ("🐻 熊市 (bear)", bear), ("⚡ 熊转牛 (bear_recovery)", recovery)]:
        if data:
            ret = f"{data['avg_oos_return']:+.1%}" if data.get("avg_oos_return") is not None else "N/A"
            lines.append(
                f"| {label} | {data.get('windows',[])} | "
                f"{data.get('avg_oos_sharpe','N/A'):+.3f} | "
                f"{data.get('min_oos_sharpe','N/A'):+.3f} | "
                f"{data.get('max_oos_sharpe','N/A'):+.3f} | {ret} |"
            )

    verdict_map = {
        "regime_dependent":     "⚠️ 高度 Regime 依赖 — 建议优先开发 Regime Filter",
        "moderate_regime_bias": "🔶 中度 Regime 依赖 — 有 Alpha，牛市有额外加成",
        "robust_alpha":         "✅ 策略稳健 — 真实 Alpha 较高",
    }
    v = result["alpha_verdict"]
    ratio = result["bull_bear_ratio"]
    lines.extend([
        "",
        f"### Alpha 判断：{verdict_map.get(v, v)}",
        f"牛/熊 Sharpe 比 = **{ratio}x**" if ratio else "",
    ])

    with open(summary_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ── 主入口 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Regime 分段 Sharpe 分析")
    parser.add_argument("--file", help="指定 WF JSON 文件路径（默认自动取最新）")
    args = parser.parse_args()

    # 加载数据
    if args.file:
        wf_path = Path(args.file)
    else:
        wf_path = find_latest_wf_file()
    if not wf_path or not wf_path.exists():
        print("❌ 未找到 WF 结果文件")
        sys.exit(1)

    print(f"📂 加载: {wf_path.name}")
    wf_data = load_wf_data(wf_path)

    # 分析
    result = analyze_regime_sharpe(wf_data)
    result["source_file"] = wf_path.name

    # 报告
    print_report(result)

    # 保存本地 JSON
    out_path = wf_path.parent / f"regime_sharpe_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"💾 本地保存: {out_path.name}")

    # 写入 Supabase
    save_to_supabase(result, wf_path.name)

    # GitHub Step Summary
    write_step_summary(result)


if __name__ == "__main__":
    main()
