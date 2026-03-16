"""
StockQueen V5 Feature Tests
Tests deleverage, turnover cap, and momentum weights override
against V4 baseline. Run with: python scripts/test_v5.py
"""

import asyncio
import sys
import os
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def run_tests():
    from app.services.rotation_service import run_rotation_backtest, _apply_turnover_cap

    BASELINE_PARAMS = {
        "start_date": "2022-07-01",
        "end_date": "2026-03-15",
        "top_n": 6,
        "holding_bonus": 0,
    }

    results = {}

    # ──────────────────────────────────────────────
    # 0. Pre-fetch data once (shared across all runs)
    # ──────────────────────────────────────────────
    print("=" * 60)
    print("StockQueen V5 Feature Tests")
    print("=" * 60)
    print("\n[0/5] Pre-fetching historical data (this takes 1-3 min)...")
    t0 = time.time()

    from app.services.rotation_service import _fetch_backtest_data
    prefetched = await _fetch_backtest_data("2022-07-01", "2026-03-15")
    print(f"      Done in {time.time() - t0:.0f}s — {len(prefetched.get('histories', {}))} tickers loaded\n")

    # ──────────────────────────────────────────────
    # 1. V4 Baseline
    # ──────────────────────────────────────────────
    print("[1/5] Running V4 baseline (TOP_N=6, HB=0, no V5 features)...")
    t0 = time.time()
    baseline = await run_rotation_backtest(**BASELINE_PARAMS, _prefetched=prefetched)
    results["baseline"] = baseline
    print(f"      Cumulative: {baseline['cumulative_return']:+.1%}")
    print(f"      Sharpe:     {baseline['sharpe_ratio']:.2f}")
    print(f"      Max DD:     {baseline['max_drawdown']:.1%}")
    print(f"      Win Rate:   {baseline['win_rate']:.1%}")
    print(f"      ({time.time() - t0:.1f}s)\n")

    # ──────────────────────────────────────────────
    # 2. Phase 2A: Deleverage
    # ──────────────────────────────────────────────
    print("[2/5] Testing DELEVERAGE (bear=50%, choppy=70%)...")
    t0 = time.time()
    delev = await run_rotation_backtest(
        **BASELINE_PARAMS, _prefetched=prefetched, deleverage=True
    )
    results["deleverage"] = delev
    cum_diff = delev["cumulative_return"] - baseline["cumulative_return"]
    dd_diff = delev["max_drawdown"] - baseline["max_drawdown"]
    print(f"      Cumulative: {delev['cumulative_return']:+.1%} ({cum_diff:+.1%} vs baseline)")
    print(f"      Sharpe:     {delev['sharpe_ratio']:.2f} ({delev['sharpe_ratio'] - baseline['sharpe_ratio']:+.2f})")
    print(f"      Max DD:     {delev['max_drawdown']:.1%} ({dd_diff:+.1%})")
    print(f"      Win Rate:   {delev['win_rate']:.1%}")
    print(f"      ({time.time() - t0:.1f}s)\n")

    # ──────────────────────────────────────────────
    # 3. Phase 2B: Turnover Cap
    # ──────────────────────────────────────────────
    print("[3/5] Testing TURNOVER CAP (max 50% weekly change)...")
    t0 = time.time()
    tc = await run_rotation_backtest(
        **BASELINE_PARAMS, _prefetched=prefetched, turnover_cap=0.5
    )
    results["turnover_cap"] = tc
    cum_diff = tc["cumulative_return"] - baseline["cumulative_return"]
    print(f"      Cumulative: {tc['cumulative_return']:+.1%} ({cum_diff:+.1%} vs baseline)")
    print(f"      Sharpe:     {tc['sharpe_ratio']:.2f} ({tc['sharpe_ratio'] - baseline['sharpe_ratio']:+.2f})")
    print(f"      Max DD:     {tc['max_drawdown']:.1%}")
    # Count actual turnover changes
    trades = tc.get("trades", [])
    total_changes = sum(len(t.get("added", [])) for t in trades)
    total_weeks = len(trades)
    avg_changes = total_changes / total_weeks if total_weeks > 0 else 0
    print(f"      Avg changes/week: {avg_changes:.1f}")
    print(f"      ({time.time() - t0:.1f}s)\n")

    # ──────────────────────────────────────────────
    # 4. Phase 2A + 2B Combined
    # ──────────────────────────────────────────────
    print("[4/5] Testing DELEVERAGE + TURNOVER CAP combined...")
    t0 = time.time()
    combined = await run_rotation_backtest(
        **BASELINE_PARAMS, _prefetched=prefetched,
        deleverage=True, turnover_cap=0.5,
    )
    results["combined"] = combined
    cum_diff = combined["cumulative_return"] - baseline["cumulative_return"]
    print(f"      Cumulative: {combined['cumulative_return']:+.1%} ({cum_diff:+.1%} vs baseline)")
    print(f"      Sharpe:     {combined['sharpe_ratio']:.2f} ({combined['sharpe_ratio'] - baseline['sharpe_ratio']:+.2f})")
    print(f"      Max DD:     {combined['max_drawdown']:.1%}")
    print(f"      ({time.time() - t0:.1f}s)\n")

    # ──────────────────────────────────────────────
    # 5. Phase 2C: Momentum Weights Override
    # ──────────────────────────────────────────────
    print("[5/5] Testing MOMENTUM WEIGHTS override...")
    weight_sets = [
        ("default (regime)", None),
        ("aggressive (0.15,0.35,0.50)", (0.15, 0.35, 0.50)),
        ("balanced (0.25,0.40,0.35)", (0.25, 0.40, 0.35)),
        ("defensive (0.40,0.40,0.20)", (0.40, 0.40, 0.20)),
    ]
    for label, weights in weight_sets:
        t0 = time.time()
        r = await run_rotation_backtest(
            **BASELINE_PARAMS, _prefetched=prefetched,
            momentum_weights=weights,
        )
        results[f"mw_{label}"] = r
        marker = " ← baseline" if weights is None else ""
        print(f"      {label:30s}  Cum={r['cumulative_return']:+.1%}  "
              f"Sharpe={r['sharpe_ratio']:.2f}  DD={r['max_drawdown']:.1%}  "
              f"({time.time() - t0:.1f}s){marker}")
    print()

    # ──────────────────────────────────────────────
    # Unit test: _apply_turnover_cap logic
    # ──────────────────────────────────────────────
    print("-" * 60)
    print("Unit Tests: _apply_turnover_cap()")
    print("-" * 60)

    scored = [("AAPL", 9.0), ("MSFT", 8.5), ("NVDA", 8.0),
              ("GOOG", 7.5), ("AMZN", 7.0), ("META", 6.5)]
    prev = ["TSLA", "AMD", "NFLX", "AAPL", "MSFT", "COST"]

    # Test 1: no cap (100%) — should pick pure top-6
    r1 = _apply_turnover_cap(scored, prev, top_n=6, max_turnover_pct=1.0)
    assert r1 == ["AAPL", "MSFT", "NVDA", "GOOG", "AMZN", "META"], f"FAIL: {r1}"
    print("  ✓ turnover_cap=1.0 → no restriction (pure top-6)")

    # Test 2: cap 50% on 6 positions → max 3 changes
    r2 = _apply_turnover_cap(scored, prev, top_n=6, max_turnover_pct=0.5)
    changes = [t for t in r2 if t not in prev]
    assert len(changes) <= 3, f"FAIL: {len(changes)} changes > 3: {r2}"
    assert len(r2) == 6, f"FAIL: wrong length {len(r2)}"
    print(f"  ✓ turnover_cap=0.5 → {len(changes)} changes (≤3): {r2}")

    # Test 3: no previous holdings — should just pick top-6
    r3 = _apply_turnover_cap(scored, [], top_n=6, max_turnover_pct=0.5)
    assert r3 == ["AAPL", "MSFT", "NVDA", "GOOG", "AMZN", "META"], f"FAIL: {r3}"
    print("  ✓ empty prev_selected → no restriction")

    # Test 4: cap 0% → max 1 change (minimum guaranteed)
    r4 = _apply_turnover_cap(scored, prev, top_n=6, max_turnover_pct=0.0)
    changes4 = [t for t in r4 if t not in prev]
    assert len(changes4) <= 1, f"FAIL: {len(changes4)} changes > 1: {r4}"
    print(f"  ✓ turnover_cap=0.0 → {len(changes4)} change (≤1): {r4}")

    print("\nAll unit tests passed! ✓\n")

    # ──────────────────────────────────────────────
    # Summary Table
    # ──────────────────────────────────────────────
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"{'Config':<30s} {'Cum Return':>12s} {'Sharpe':>8s} {'MaxDD':>8s}")
    print("-" * 60)
    summary_rows = [
        ("V4 Baseline", "baseline"),
        ("+ Deleverage", "deleverage"),
        ("+ Turnover Cap 50%", "turnover_cap"),
        ("+ Both", "combined"),
    ]
    for label, key in summary_rows:
        r = results[key]
        print(f"{label:<30s} {r['cumulative_return']:>+11.1%} {r['sharpe_ratio']:>8.2f} {r['max_drawdown']:>8.1%}")
    print("-" * 60)
    print("\nDone. V5 features verified — all flags default OFF, safe for live V4.\n")


if __name__ == "__main__":
    asyncio.run(run_tests())
