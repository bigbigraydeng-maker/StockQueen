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
                   choices=["all", "midcap", "largecap", "dynamic", "quality"],
                   help="股票池范围：quality=动态池+基本面质量门控（EPS+CF筛选）")
    p.add_argument("--sector",   default=None,
                   help="板块过滤，例如 tech / bio / energy / financials")
    return p.parse_args()


def _passes_quality_gate(ticker: str, cache_dir: Path) -> bool:
    """
    质量门控：
    1. 最近4个季度中，至少2个季度 EPS（basic_earnings_per_share）> 0
    2. 最近2个季度中，至少1个季度 operating_cashflow > 0
    任意条件缺少数据 → 排除（保守原则）
    """
    e_path = cache_dir / f"earnings_{ticker}.json"
    c_path = cache_dir / f"cashflow_{ticker}.json"

    if not e_path.exists() or not c_path.exists():
        return False  # 无基本面数据 → 排除

    try:
        with open(e_path, encoding="utf-8") as f:
            e_raw = json.load(f)
        with open(c_path, encoding="utf-8") as f:
            c_raw = json.load(f)

        e_quarters = (e_raw.get("data") or {}).get("quarterly", [])
        c_quarters = (c_raw.get("data") or {}).get("quarterly", [])

        # 条件1：最近4季中至少2季 EPS > 0
        eps_vals = [q.get("reported_eps") for q in e_quarters[:4]]
        eps_pos  = sum(1 for v in eps_vals if v is not None and v > 0)
        if eps_pos < 2:
            return False

        # 条件2：最近2季中至少1季 operating_cashflow > 0
        cf_vals = [q.get("operating_cashflow") for q in c_quarters[:2]]
        cf_pos  = sum(1 for v in cf_vals if v is not None and v > 0)
        if cf_pos < 1:
            return False

        return True

    except Exception:
        return False


def _load_dynamic_histories(start_date: str, end_date: str) -> dict:
    """
    从磁盘缓存直接加载全量动态池的 OHLCV，返回与 _fetch_backtest_data 相同格式的
    histories dict：{ticker: {dates, open, high, low, close, volume}}
    """
    cache_dir = PROJECT_ROOT / ".cache" / "av"
    start_ts = start_date
    end_ts   = end_date

    histories = {}
    files = list(cache_dir.glob("daily_*_full.json"))
    print(f"磁盘 OHLCV 缓存: {len(files)} 个文件，正在加载...")

    for fp in files:
        ticker = fp.stem.replace("daily_", "").replace("_full", "")
        try:
            with open(fp, encoding="utf-8") as f:
                raw = json.load(f)
            rows = raw.get("rows", [])
            if not rows:
                continue
            # 按日期范围过滤
            filtered = [r for r in rows if start_ts <= r[0] <= end_ts]
            if len(filtered) < 100:      # 数据太少的跳过
                continue
            histories[ticker] = {
                "dates":  [r[0] for r in filtered],
                "open":   [r[1] for r in filtered],
                "high":   [r[2] for r in filtered],
                "low":    [r[3] for r in filtered],
                "close":  [r[4] for r in filtered],
                "volume": [r[5] for r in filtered],
            }
        except Exception:
            continue

    print(f"加载完成: {len(histories)} 支股票有 {start_date}~{end_date} 数据")
    return histories


def _load_quality_histories(start_date: str, end_date: str) -> tuple:
    """
    在 _load_dynamic_histories 基础上，额外应用质量门控。
    返回 (histories, passed_count, total_count)
    """
    cache_dir = PROJECT_ROOT / ".cache" / "av"
    all_histories = _load_dynamic_histories(start_date, end_date)

    passed  = {}
    total   = 0
    n_pass  = 0
    n_no_data = 0

    for ticker, hist in all_histories.items():
        if ticker == "SPY":
            passed[ticker] = hist
            continue
        total += 1
        ok = _passes_quality_gate(ticker, cache_dir)
        if ok:
            passed[ticker] = hist
            n_pass += 1
        else:
            n_no_data += 1

    print(f"质量门控: {total} 支个股 → 通过 {n_pass} / 排除 {n_no_data}")
    print(f"  条件: EPS>0 in 2/4季 + OperatingCF>0 in 1/2季")
    return passed


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

    # ── dynamic / quality 模式: 直接读磁盘缓存 ──
    if universe == "quality":
        histories = _load_quality_histories(start_date, end_date)
        bt_fund   = {}
    elif universe == "dynamic":
        histories = _load_dynamic_histories(start_date, end_date)
        bt_fund   = {}
    else:
        data = await _fetch_backtest_data(start_date, end_date)
        if "error" in data:
            print(f"数据获取失败: {data['error']}")
            return None
        histories = data.get("histories", {})
        bt_fund   = data.get("bt_fundamentals", {})

    spy_hist = histories.get("SPY", {})
    print(f"基本面数据覆盖: {len(bt_fund)} 支股票")

    # 从本地预拉取缓存加载基本面数据
    fund_cache_path = PROJECT_ROOT / "scripts" / "stress_test_results" / "fundamentals_cache.json"
    if len(bt_fund) == 0 and fund_cache_path.exists():
        with open(fund_cache_path, encoding="utf-8") as f:
            cached = json.load(f)
        bt_fund = cached.get("fundamentals", {})
        print(f"从本地缓存加载基本面: {len(bt_fund)} 支股票"
              f"  (更新时间: {cached.get('updated_at', '未知')[:10]})")
    elif len(bt_fund) == 0:
        print("[提示] 未找到基本面缓存，请先运行: python scripts/prefetch_all_data.py")

    # ── 按 universe 过滤股票池 ──
    if universe in ("dynamic", "quality"):
        # 取所有有 OHLCV 的 ticker（SPY除外），基本面有就用，没有就跳过
        tickers = [t for t in histories if t != "SPY"]
    elif universe == "midcap":
        pool = MIDCAP_STOCKS
        if sector:
            pool = [s for s in pool if s.get("sector") == sector]
        allowed_tickers = {s["ticker"] for s in pool}
        tickers = [t for t in histories if t != "SPY" and t in allowed_tickers]
    elif universe == "largecap":
        pool = LARGECAP_STOCKS
        if sector:
            pool = [s for s in pool if s.get("sector") == sector]
        allowed_tickers = {s["ticker"] for s in pool}
        tickers = [t for t in histories if t != "SPY" and t in allowed_tickers]
    else:  # all
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

    # 日历基准：优先用 SPY（最完整），其次用第一支个股
    if spy_dates:
        all_dates = spy_dates
    else:
        all_dates = histories[tickers[0]].get("dates", [])

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
