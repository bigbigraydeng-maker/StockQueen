"""
因子 IC 分析 — StockQueen 宝典V4
====================================
Information Coefficient (IC) = 因子值 vs 未来N周收益的 Spearman 相关系数

用来回答：9个因子中哪些真的有预测力，哪些只是噪音？

指标说明：
  IC       — 单期截面 Spearman 相关，>0.05 算有效
  ICIR     — IC / std(IC)，>0.5 才算稳定因子
  IC>0 %   — IC为正的期数占比
  t-stat   — 检验均值是否显著异于零

使用方式：
  cd StockQueen
  pip install scipy pandas

  # 全部股票（基本面因子会N/A）
  python scripts/factor_ic_analysis.py

  # 只测中盘股（有完整基本面数据）
  python scripts/factor_ic_analysis.py --universe midcap

  # 只测大盘股
  python scripts/factor_ic_analysis.py --universe largecap

  # 按板块过滤（在midcap范围内）
  python scripts/factor_ic_analysis.py --universe midcap --sector tech
  python scripts/factor_ic_analysis.py --universe midcap --sector bio
  python scripts/factor_ic_analysis.py --universe midcap --sector energy

  可用sector：tech, bio, energy, financials, healthcare, industrials,
              consumer_lc, consumer_disc, semi, defense, crypto, realestate
"""

import asyncio
import sys
import argparse
import json
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from scipy import stats

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows GBK 终端兼容
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import logging
logging.basicConfig(level=logging.WARNING)  # 静默日志，只看结果


# ─────────────────────────────────────────────
# 参数
# ─────────────────────────────────────────────
DEFAULT_START = "2022-01-01"
DEFAULT_END   = "2025-01-01"
FORWARD_WEEKS = [1, 2, 4]   # 计算未来1周/2周/4周的预测力


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--start",    default=DEFAULT_START)
    p.add_argument("--end",      default=DEFAULT_END)
    p.add_argument("--universe", default="all",
                   choices=["all", "midcap", "largecap"],
                   help="股票池范围（midcap才有完整基本面数据）")
    p.add_argument("--sector",   default=None,
                   help="板块过滤，例如 tech / bio / energy / financials")
    return p.parse_args()


# ─────────────────────────────────────────────
# 核心：按周滚动，计算截面 IC
# ─────────────────────────────────────────────

async def compute_ic_series(start_date: str, end_date: str,
                            universe: str = "all", sector: str = None):
    """
    逐周滚动：
    1. 在每个"评分时点 t"，计算所有股票的各因子得分
    2. 计算股票在 t+N 周的实际收益
    3. IC = spearmanr(因子得分, 实际收益)
    """
    from app.services.rotation_service import _fetch_backtest_data
    from app.services.multi_factor_scorer import (
        score_momentum, score_technical, score_trend,
        score_relative_strength, score_fundamental,
        score_earnings, score_cashflow,
    )
    from app.config.rotation_watchlist import (
        MIDCAP_STOCKS, LARGECAP_STOCKS, OFFENSIVE_ETFS, DEFENSIVE_ETFS,
    )

    print(f"\n获取数据中 ({start_date} ~ {end_date})...")
    data = await _fetch_backtest_data(start_date, end_date)
    if "error" in data:
        print(f"数据获取失败: {data['error']}")
        return None

    histories    = data.get("histories", {})
    bt_fund      = data.get("bt_fundamentals", {})
    spy_hist     = histories.get("SPY", {})          # SPY 在 histories 里
    print(f"基本面数据覆盖: {len(bt_fund)} 支股票")

    # 优先从本地预拉取缓存加载基本面数据
    fund_cache_path = PROJECT_ROOT / "scripts" / "stress_test_results" / "fundamentals_cache.json"
    if len(bt_fund) == 0 and fund_cache_path.exists():
        with open(fund_cache_path, encoding="utf-8") as f:
            cached = json.load(f)
        bt_fund = cached.get("fundamentals", {})
        print(f"从本地缓存加载基本面: {len(bt_fund)} 支股票"
              f"  (更新时间: {cached.get('updated_at', '未知')[:10]})")
    elif len(bt_fund) == 0:
        print("[提示] 未找到基本面缓存，请先运行: python scripts/prefetch_fundamentals.py")

    # ── 按 universe 过滤股票池 ──
    if universe == "midcap":
        pool = MIDCAP_STOCKS
    elif universe == "largecap":
        pool = LARGECAP_STOCKS
    else:
        pool = MIDCAP_STOCKS + LARGECAP_STOCKS + OFFENSIVE_ETFS + DEFENSIVE_ETFS

    if sector:
        pool = [s for s in pool if s.get("sector") == sector]
        if not pool:
            print(f"[警告] sector='{sector}' 未找到任何股票，检查拼写")
            return None

    allowed_tickers = {s["ticker"] for s in pool}
    tickers = [t for t in histories if t != "SPY" and t in allowed_tickers]

    print(f"universe={universe}" + (f" sector={sector}" if sector else "") +
          f" → 有效股票数: {len(tickers)}")

    spy_closes = np.array(spy_hist.get("close", []))
    spy_dates  = spy_hist.get("dates", [])

    print(f"股票数: {len(tickers)}, SPY数据点: {len(spy_closes)}")

    # 把 SPY 日期映射到索引（按日期定位切片）
    spy_date_idx = {d: i for i, d in enumerate(spy_dates)}

    # 全部股票的日期 → 用第一支有数据的股票作为日历基准
    sample_ticker = tickers[0]
    all_dates = histories[sample_ticker].get("dates", [])

    # 按周采样（每5个交易日取一个截面）
    step = 5  # 每周
    max_fwd = max(FORWARD_WEEKS) * step + 5  # 预留缓冲

    # 每个因子的 IC 时间序列：{factor_name: {fwd_week: [ic1, ic2, ...]}}
    ic_series = {
        fname: {fw: [] for fw in FORWARD_WEEKS}
        for fname in ["momentum", "technical", "trend",
                      "relative_strength", "fundamental",
                      "earnings", "cashflow"]
    }
    dates_used = []

    # 滚动截面
    for t_idx in range(63, len(all_dates) - max_fwd, step):
        score_date = all_dates[t_idx]

        cross_section = {}  # ticker → {factor: score, fwd_ret_1w: ...}

        for ticker in tickers:
            h = histories[ticker]
            t_closes  = np.array(h["close"])
            t_volumes = np.array(h.get("volume", [1]*len(h["close"])))
            t_highs   = np.array(h.get("high",  t_closes))
            t_lows    = np.array(h.get("low",   t_closes))
            t_dates   = h["dates"]

            # 找到 score_date 在该股票数据中的位置
            if score_date not in {d: i for i, d in enumerate(t_dates)}:
                continue
            local_date_idx = {d: i for i, d in enumerate(t_dates)}
            pos = local_date_idx.get(score_date)
            if pos is None or pos < 63:
                continue

            closes_slice  = t_closes[:pos+1]
            volumes_slice = t_volumes[:pos+1]
            highs_slice   = t_highs[:pos+1]
            lows_slice    = t_lows[:pos+1]

            # SPY 切片
            spy_pos = spy_date_idx.get(score_date, -1)
            spy_slice = spy_closes[:spy_pos+1] if spy_pos >= 22 else spy_closes[:22]

            # 获取基本面数据（带 as_of_date 防未来数据泄漏）
            # 注：overview 因 look-ahead bias 已被跳过，fundamental 因子将为 N/A
            fund = bt_fund.get(ticker, {})
            overview_data = None  # overview 不用于回测（非点位数据）
            earnings_data = fund.get("earnings_data")
            cashflow_data = fund.get("cashflow_data")

            # as_of_date 必须是字符串（score_earnings/cashflow 做字符串比较）
            as_of_str = str(score_date)[:10]

            # 计算各因子得分，同时记录 available 状态
            scores = {}
            available = {}
            try:
                r = score_momentum(closes_slice)
                scores["momentum"] = r["score"]; available["momentum"] = True

                r = score_technical(closes_slice, volumes_slice, highs_slice, lows_slice)
                scores["technical"] = r["score"]; available["technical"] = True

                r = score_trend(closes_slice)
                scores["trend"] = r["score"]; available["trend"] = True

                r = score_relative_strength(closes_slice, spy_slice)
                scores["relative_strength"] = r["score"]; available["relative_strength"] = True

                r = score_fundamental(overview_data)
                scores["fundamental"] = r["score"]; available["fundamental"] = r.get("available", False)

                r = score_earnings(earnings_data, as_of_date=as_of_str)
                scores["earnings"] = r["score"]; available["earnings"] = r.get("available", False)

                r = score_cashflow(cashflow_data, as_of_date=as_of_str)
                scores["cashflow"] = r["score"]; available["cashflow"] = r.get("available", False)

            except Exception:
                continue

            # 计算未来 N 周实际收益（防数据泄漏：用 pos+1 之后的数据）
            fwd_rets = {}
            for fw in FORWARD_WEEKS:
                future_pos = pos + fw * step
                if future_pos < len(t_closes):
                    fwd_rets[fw] = float(t_closes[future_pos] / t_closes[pos] - 1)
                else:
                    fwd_rets[fw] = None

            cross_section[ticker] = {"scores": scores, "available": available, "fwd_rets": fwd_rets}

        if len(cross_section) < 5:
            continue  # 截面太少，跳过

        # 计算当期 IC（每个因子 vs 每个预测窗口）
        # 价格因子：用全截面；基本面因子：只用 available=True 的股票
        PRICE_FACTORS = {"momentum", "technical", "trend", "relative_strength"}
        dates_used.append(score_date)
        for fname in ic_series:
            for fw in FORWARD_WEEKS:
                factor_vals = []
                fwd_ret_vals = []
                for ticker, d in cross_section.items():
                    # 基本面因子只用有数据的股票，避免 available=False 的 0 值稀释
                    if fname not in PRICE_FACTORS and not d["available"].get(fname, False):
                        continue
                    fv = d["scores"].get(fname)
                    rv = d["fwd_rets"].get(fw)
                    if fv is not None and rv is not None:
                        factor_vals.append(fv)
                        fwd_ret_vals.append(rv)

                if len(factor_vals) >= 5:
                    if len(set(factor_vals)) < 3:
                        continue
                    ic, _ = stats.spearmanr(factor_vals, fwd_ret_vals)
                    if not np.isnan(ic):
                        ic_series[fname][fw].append(ic)

    return ic_series, dates_used


# ─────────────────────────────────────────────
# 汇总统计
# ─────────────────────────────────────────────

def summarize_ic(ic_series: dict):
    """打印 IC 汇总表"""
    print("\n" + "=" * 72)
    print(f"{'因子':20s}  {'预测窗口':8s}  {'均值IC':>8s}  {'ICIR':>7s}  "
          f"{'IC>0%':>7s}  {'t-stat':>7s}  {'n':>5s}  {'结论':8s}")
    print("=" * 72)

    results = {}
    for fname in ["momentum", "technical", "trend", "relative_strength",
                  "fundamental", "earnings", "cashflow"]:
        row = {}
        for fw in FORWARD_WEEKS:
            ics = ic_series[fname][fw]
            if not ics:
                print(f"{fname:20s}  {fw}W        {'N/A':>8s}")
                continue
            arr = np.array(ics)
            mean_ic  = float(np.mean(arr))
            std_ic   = float(np.std(arr)) if len(arr) > 1 else 1e-9
            icir     = mean_ic / std_ic if std_ic > 0 else 0
            pct_pos  = float(np.mean(arr > 0))
            t_stat, p_val = stats.ttest_1samp(arr, 0)

            # 结论
            if abs(mean_ic) >= 0.05 and abs(icir) >= 0.5 and p_val < 0.05:
                verdict = "★ 强"
            elif abs(mean_ic) >= 0.03 and p_val < 0.1:
                verdict = "○ 弱"
            else:
                verdict = "✗ 无效"

            print(f"{fname:20s}  {fw}W        "
                  f"{mean_ic:>+8.4f}  {icir:>7.3f}  "
                  f"{pct_pos:>7.1%}  {t_stat:>7.2f}  "
                  f"{len(arr):>5d}  {verdict}")
            row[fw] = {
                "mean_ic": round(mean_ic, 4),
                "icir": round(icir, 3),
                "pct_positive": round(pct_pos, 3),
                "t_stat": round(float(t_stat), 2),
                "p_value": round(float(p_val), 4),
                "n": len(arr),
                "verdict": verdict,
            }
        results[fname] = row
        print()

    print("=" * 72)
    print("\n判断标准：")
    print("  均值IC ≥ 0.05 + ICIR ≥ 0.5 + p < 0.05 → ★ 强有效因子")
    print("  均值IC ≥ 0.03 + p < 0.10             → ○ 弱有效因子")
    print("  其他                                  → ✗ 噪音，考虑降权")

    return results


# ─────────────────────────────────────────────
# 权重建议
# ─────────────────────────────────────────────

def suggest_weights(results: dict, forward_week: int = 1):
    """根据 ICIR 建议重新分配因子权重"""
    print(f"\n基于 {forward_week}W 预测力的权重建议：")
    print("-" * 50)

    icir_map = {}
    for fname, row in results.items():
        if forward_week in row:
            icir_map[fname] = max(0.0, row[forward_week]["icir"])

    total_icir = sum(icir_map.values())
    if total_icir == 0:
        print("  所有因子 ICIR ≤ 0，数据不足或策略有问题")
        return

    print(f"  {'因子':22s}  {'现有权重':>10s}  {'建议权重(ICIR)':>14s}")
    print(f"  {'-'*22}  {'-'*10}  {'-'*14}")

    from app.services.multi_factor_scorer import FACTOR_WEIGHTS
    for fname in ["momentum", "technical", "trend", "relative_strength",
                  "fundamental", "earnings", "cashflow"]:
        current_w = FACTOR_WEIGHTS.get(fname, 0)
        suggested_w = icir_map.get(fname, 0) / total_icir
        arrow = "↑" if suggested_w > current_w + 0.03 else ("↓" if suggested_w < current_w - 0.03 else " ")
        print(f"  {fname:22s}  {current_w:>10.0%}  {suggested_w:>13.0%} {arrow}")


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

async def main():
    args = parse_args()
    label = args.universe + (f"_{args.sector}" if args.sector else "")
    print("=" * 60)
    print("StockQueen 因子 IC 分析")
    print(f"区间: {args.start} ~ {args.end}")
    print(f"范围: {label}")
    print("=" * 60)

    result = await compute_ic_series(args.start, args.end,
                                     universe=args.universe,
                                     sector=args.sector)
    if result is None:
        return

    ic_series, dates_used = result
    print(f"\n有效截面日期数: {len(dates_used)}")
    if dates_used:
        print(f"首期: {dates_used[0]}  末期: {dates_used[-1]}")

    results = summarize_ic(ic_series)
    suggest_weights(results, forward_week=1)
    suggest_weights(results, forward_week=2)

    # 保存，文件名含 universe/sector 标签
    out_path = (PROJECT_ROOT / "scripts" / "stress_test_results"
                / f"factor_ic_{label}.json")
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "start": args.start,
            "end": args.end,
            "universe": args.universe,
            "sector": args.sector,
            "dates": [str(d)[:10] for d in dates_used],  # Timestamp → str
            "ic_results": results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
