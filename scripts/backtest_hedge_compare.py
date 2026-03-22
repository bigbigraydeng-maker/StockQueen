"""
scripts/backtest_hedge_compare.py
=================================
对比回测：hedge_overlay=False (基线) vs hedge_overlay=True (带对冲)
重点关注 2022 熊市区间 Max Drawdown 改善和 2023-2024 牛市拖累幅度。

用法:
  python scripts/backtest_hedge_compare.py
"""

import asyncio
import os
import sys
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hedge_compare")


# 回测全程 + 分段区间
FULL_PERIOD = ("2018-01-01", "2026-03-14")
SEGMENTS = {
    "2022 Bear":      ("2022-01-01", "2022-12-31"),
    "2023 Recovery":  ("2023-01-01", "2023-12-31"),
    "2024 Bull":      ("2024-01-01", "2024-12-31"),
    "2025 YTD":       ("2025-01-01", "2026-03-14"),
}


def _fmt_pct(v: float) -> str:
    return f"{v * 100:+.1f}%"


def _print_comparison(label: str, baseline: dict, hedged: dict):
    """Print side-by-side comparison"""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"{'Metric':<25} {'Baseline':>15} {'+ Hedge':>15} {'Delta':>12}")
    print(f"{'-' * 67}")

    metrics = [
        ("Cumulative Return", "cumulative_return"),
        ("Annualized Return", "annualized_return"),
        ("Max Drawdown", "max_drawdown"),
        ("Sharpe Ratio", "sharpe_ratio"),
        ("Win Rate", "win_rate"),
        ("Alpha vs SPY", "alpha_vs_spy"),
    ]

    for name, key in metrics:
        bv = baseline.get(key, 0)
        hv = hedged.get(key, 0)
        delta = hv - bv

        if key == "sharpe_ratio":
            print(f"{name:<25} {bv:>15.2f} {hv:>15.2f} {delta:>+12.2f}")
        else:
            print(f"{name:<25} {_fmt_pct(bv):>15} {_fmt_pct(hv):>15} {_fmt_pct(delta):>12}")


def _print_yearly(label: str, baseline: dict, hedged: dict):
    """Print yearly breakdown comparison"""
    b_yearly = {y["year"]: y for y in baseline.get("yearly_stats", [])}
    h_yearly = {y["year"]: y for y in hedged.get("yearly_stats", [])}

    print(f"\n  {label} - Yearly Breakdown")
    print(f"  {'Year':<12} {'Base Return':>12} {'Hedge Return':>12} {'Base MDD':>10} {'Hedge MDD':>10} {'Base Sharpe':>12} {'Hedge Sharpe':>12}")
    print(f"  {'-' * 82}")

    for year in sorted(set(list(b_yearly.keys()) + list(h_yearly.keys()))):
        by = b_yearly.get(year, {})
        hy = h_yearly.get(year, {})
        print(f"  {year:<12} "
              f"{_fmt_pct(by.get('strategy_return', 0)):>12} "
              f"{_fmt_pct(hy.get('strategy_return', 0)):>12} "
              f"{_fmt_pct(by.get('max_drawdown', 0)):>10} "
              f"{_fmt_pct(hy.get('max_drawdown', 0)):>10} "
              f"{by.get('sharpe', 0):>12.2f} "
              f"{hy.get('sharpe', 0):>12.2f}")


def _print_hedge_activity(hedged: dict):
    """Print hedge activation summary"""
    details = hedged.get("weekly_details", [])
    hedge_weeks = [d for d in details if d.get("hedge_alloc", 0) > 0]
    total_weeks = len(details)

    print(f"\n  Hedge Activity Summary")
    print(f"  Total weeks: {total_weeks}, Hedged weeks: {len(hedge_weeks)} ({len(hedge_weeks)/total_weeks*100:.1f}%)")

    if hedge_weeks:
        # Group by regime
        from collections import Counter
        regime_counts = Counter(d["regime"] for d in hedge_weeks)
        for r, c in sorted(regime_counts.items()):
            print(f"    {r}: {c} weeks")

        # Group by hedge ticker
        ticker_counts = Counter(d.get("hedge_ticker", "?") for d in hedge_weeks)
        print(f"  Hedge ETF usage:")
        for t, c in ticker_counts.most_common():
            print(f"    {t}: {c} weeks")


async def run_comparison():
    from app.services.rotation_service import run_rotation_backtest, _fetch_backtest_data

    # Pre-fetch data once
    logger.info("Fetching backtest data (this may take a while on first run)...")
    prefetched = await _fetch_backtest_data("2017-01-01", "2026-03-14")
    if "error" in prefetched:
        logger.error(f"Data fetch failed: {prefetched['error']}")
        return

    logger.info(f"Data ready: {len(prefetched['histories'])} tickers")

    # ── Full period comparison ──
    print("\n" + "=" * 60)
    print("  HEDGE OVERLAY COMPARISON")
    print("  Full period: 2018-01-01 to 2026-03-14")
    print("=" * 60)

    logger.info("Running baseline (no hedge)...")
    baseline = await run_rotation_backtest(
        start_date=FULL_PERIOD[0], end_date=FULL_PERIOD[1],
        _prefetched=prefetched, hedge_overlay=False,
    )
    if "error" in baseline:
        logger.error(f"Baseline failed: {baseline['error']}")
        return

    logger.info("Running hedged version...")
    hedged = await run_rotation_backtest(
        start_date=FULL_PERIOD[0], end_date=FULL_PERIOD[1],
        _prefetched=prefetched, hedge_overlay=True,
    )
    if "error" in hedged:
        logger.error(f"Hedged failed: {hedged['error']}")
        return

    _print_comparison("FULL PERIOD", baseline, hedged)
    _print_yearly("FULL PERIOD", baseline, hedged)
    _print_hedge_activity(hedged)

    # ── Segment comparisons ──
    for seg_name, (seg_start, seg_end) in SEGMENTS.items():
        logger.info(f"Running segment: {seg_name}...")
        seg_base = await run_rotation_backtest(
            start_date=seg_start, end_date=seg_end,
            _prefetched=prefetched, hedge_overlay=False,
        )
        seg_hedge = await run_rotation_backtest(
            start_date=seg_start, end_date=seg_end,
            _prefetched=prefetched, hedge_overlay=True,
        )
        if "error" not in seg_base and "error" not in seg_hedge:
            _print_comparison(seg_name, seg_base, seg_hedge)

    print("\n" + "=" * 60)
    print("  DONE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_comparison())
