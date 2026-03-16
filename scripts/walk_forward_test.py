"""
StockQueen V5 Walk-Forward Validation (Phase A + Phase B Weight Search)
=======================================================================
Phase A: Train on historical window -> select best TOP_N + HB params
Phase B: Lock best TOP_N/HB from Phase A -> search momentum weight grid
Then test on next out-of-sample window.

Windows (6 windows, ~8mo train + ~8mo OOS, overlapping):
  W1: Train 2021-07 ~ 2022-06  ->  Test 2022-07 ~ 2023-02
  W2: Train 2022-03 ~ 2022-12  ->  Test 2023-03 ~ 2023-10
  W3: Train 2022-11 ~ 2023-08  ->  Test 2023-11 ~ 2024-06
  W4: Train 2023-07 ~ 2024-04  ->  Test 2024-07 ~ 2025-02
  W5: Train 2024-03 ~ 2024-12  ->  Test 2025-03 ~ 2025-10
  W6: Train 2024-11 ~ 2025-08  ->  Test 2025-09 ~ 2026-03

Phase A grid: TOP_N x HOLDING_BONUS (25 combos)
Phase B grid: WEIGHT_GRID (9 momentum weight combos)

Results saved to: scripts/stress_test_results/walk_forward_v5.json

Usage:
    cd StockQueen
    python scripts/walk_forward_test.py
"""

import asyncio
import json
import sys
import time
import numpy as np
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Configure logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
    stream=sys.stdout,
)
logging.getLogger("app.services.rotation_service").setLevel(logging.INFO)
logging.getLogger("app.services.alphavantage_client").setLevel(logging.INFO)

RESULTS_DIR = PROJECT_ROOT / "scripts" / "stress_test_results"
RESULTS_DIR.mkdir(exist_ok=True)

# Walk-Forward windows (6 windows, ~8mo train + ~8mo OOS, overlapping)
WINDOWS = [
    {
        "name": "W1",
        "train_start": "2021-07-01", "train_end": "2022-06-30",
        "test_start":  "2022-07-01", "test_end":  "2023-02-28",
    },
    {
        "name": "W2",
        "train_start": "2022-03-01", "train_end": "2022-12-31",
        "test_start":  "2023-03-01", "test_end":  "2023-10-31",
    },
    {
        "name": "W3",
        "train_start": "2022-11-01", "train_end": "2023-08-31",
        "test_start":  "2023-11-01", "test_end":  "2024-06-30",
    },
    {
        "name": "W4",
        "train_start": "2023-07-01", "train_end": "2024-04-30",
        "test_start":  "2024-07-01", "test_end":  "2025-02-28",
    },
    {
        "name": "W5",
        "train_start": "2024-03-01", "train_end": "2024-12-31",
        "test_start":  "2025-03-01", "test_end":  "2025-10-31",
    },
    {
        "name": "W6",
        "train_start": "2024-11-01", "train_end": "2025-08-31",
        "test_start":  "2025-09-01", "test_end":  "2026-03-01",
    },
]

# === Phase A: TOP_N x HOLDING_BONUS grid ===
TOP_N_VALUES = [2, 3, 4, 5, 6]
BONUS_VALUES = [0, 0.25, 0.5, 0.75, 1.0]
ATR_STOP_VALUES = [1.5]                    # locked
TRAILING_MULT_VALUES = [1.5]               # locked
TRAILING_ACTIVATE_VALUES = [0.5]           # locked

# === Phase B: Momentum Weight Search (using locked TOP_N and HB) ===
WEIGHT_GRID = [
    (0.15, 0.35, 0.50),  # strong_bull default
    (0.15, 0.45, 0.40),
    (0.20, 0.40, 0.40),  # bull default
    (0.25, 0.40, 0.35),
    (0.30, 0.40, 0.30),
    (0.35, 0.40, 0.25),  # choppy default
    (0.35, 0.35, 0.30),
    (0.40, 0.40, 0.20),  # bear default
    (0.40, 0.35, 0.25),
]


def _total_phase_a_combos():
    return (len(TOP_N_VALUES) * len(BONUS_VALUES) * len(ATR_STOP_VALUES)
            * len(TRAILING_MULT_VALUES) * len(TRAILING_ACTIVATE_VALUES))


async def run_phase_a_search(start_date: str, end_date: str, prefetched: dict) -> list:
    """
    Phase A: Search TOP_N x HOLDING_BONUS grid (stop/trail locked).
    Returns sorted list of results (best Sharpe first).
    """
    from app.services.rotation_service import run_rotation_backtest
    from app.config.rotation_watchlist import RotationConfig as RC

    results = []

    for tn in TOP_N_VALUES:
        for hb in BONUS_VALUES:
            for atr_s in ATR_STOP_VALUES:
                for tr_m in TRAILING_MULT_VALUES:
                    for tr_a in TRAILING_ACTIVATE_VALUES:
                        if tr_m == 0 and tr_a != TRAILING_ACTIVATE_VALUES[0]:
                            continue

                        orig_stop = RC.BACKTEST_STOP_MULT
                        orig_trail = RC.BACKTEST_TRAILING_MULT
                        orig_act = RC.BACKTEST_TRAILING_ACTIVATE
                        RC.BACKTEST_STOP_MULT = atr_s
                        RC.BACKTEST_TRAILING_MULT = tr_m
                        RC.BACKTEST_TRAILING_ACTIVATE = tr_a

                        try:
                            bt = await run_rotation_backtest(
                                start_date=start_date,
                                end_date=end_date,
                                top_n=tn,
                                holding_bonus=hb,
                                _prefetched=prefetched,
                            )

                            if "error" not in bt:
                                ae = bt.get("alpha_enhancements", {})
                                results.append({
                                    "top_n": tn,
                                    "holding_bonus": hb,
                                    "atr_stop": atr_s,
                                    "trailing_mult": tr_m,
                                    "trailing_activate": tr_a,
                                    "cumulative_return": bt["cumulative_return"],
                                    "annualized_return": bt["annualized_return"],
                                    "sharpe_ratio": bt["sharpe_ratio"],
                                    "max_drawdown": bt["max_drawdown"],
                                    "win_rate": bt["win_rate"],
                                    "alpha_vs_spy": bt["alpha_vs_spy"],
                                    "weeks": bt["weeks"],
                                    "stops_hit": ae.get("stop_triggered_count", 0),
                                    "trailing_hit": ae.get("trailing_triggered_count", 0),
                                })
                        except Exception as e:
                            print(f"    ERROR: top={tn} hb={hb} stop={atr_s} "
                                  f"trail={tr_m} act={tr_a}: {str(e)[:80]}")
                        finally:
                            RC.BACKTEST_STOP_MULT = orig_stop
                            RC.BACKTEST_TRAILING_MULT = orig_trail
                            RC.BACKTEST_TRAILING_ACTIVATE = orig_act

    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)
    return results


async def run_phase_b_search(start_date: str, end_date: str,
                              top_n: int, holding_bonus: float,
                              atr_stop: float, trailing_mult: float,
                              trailing_activate: float,
                              prefetched: dict) -> list:
    """
    Phase B: Lock TOP_N/HB from Phase A, search momentum weight grid.
    Returns sorted list of results (best Sharpe first).
    """
    from app.services.rotation_service import run_rotation_backtest
    from app.config.rotation_watchlist import RotationConfig as RC

    results = []

    orig_stop = RC.BACKTEST_STOP_MULT
    orig_trail = RC.BACKTEST_TRAILING_MULT
    orig_act = RC.BACKTEST_TRAILING_ACTIVATE
    RC.BACKTEST_STOP_MULT = atr_stop
    RC.BACKTEST_TRAILING_MULT = trailing_mult
    RC.BACKTEST_TRAILING_ACTIVATE = trailing_activate

    try:
        for weights in WEIGHT_GRID:
            try:
                bt = await run_rotation_backtest(
                    start_date=start_date,
                    end_date=end_date,
                    top_n=top_n,
                    holding_bonus=holding_bonus,
                    _prefetched=prefetched,
                    momentum_weights=weights,
                )

                if "error" not in bt:
                    ae = bt.get("alpha_enhancements", {})
                    results.append({
                        "momentum_weights": weights,
                        "w1w": weights[0],
                        "w1m": weights[1],
                        "w3m": weights[2],
                        "cumulative_return": bt["cumulative_return"],
                        "annualized_return": bt["annualized_return"],
                        "sharpe_ratio": bt["sharpe_ratio"],
                        "max_drawdown": bt["max_drawdown"],
                        "win_rate": bt["win_rate"],
                        "alpha_vs_spy": bt["alpha_vs_spy"],
                        "weeks": bt["weeks"],
                        "stops_hit": ae.get("stop_triggered_count", 0),
                        "trailing_hit": ae.get("trailing_triggered_count", 0),
                    })
            except Exception as e:
                print(f"    ERROR: weights={weights}: {str(e)[:80]}")
    finally:
        RC.BACKTEST_STOP_MULT = orig_stop
        RC.BACKTEST_TRAILING_MULT = orig_trail
        RC.BACKTEST_TRAILING_ACTIVATE = orig_act

    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)
    return results


async def run_single_backtest(start_date: str, end_date: str,
                               top_n: int, holding_bonus: float,
                               atr_stop: float, trailing_mult: float,
                               trailing_activate: float,
                               prefetched: dict,
                               momentum_weights: tuple = None) -> dict:
    """Run a single backtest with specific parameters."""
    from app.services.rotation_service import run_rotation_backtest
    from app.config.rotation_watchlist import RotationConfig as RC

    orig_stop = RC.BACKTEST_STOP_MULT
    orig_trail = RC.BACKTEST_TRAILING_MULT
    orig_act = RC.BACKTEST_TRAILING_ACTIVATE
    RC.BACKTEST_STOP_MULT = atr_stop
    RC.BACKTEST_TRAILING_MULT = trailing_mult
    RC.BACKTEST_TRAILING_ACTIVATE = trailing_activate

    try:
        bt = await run_rotation_backtest(
            start_date=start_date,
            end_date=end_date,
            top_n=top_n,
            holding_bonus=holding_bonus,
            _prefetched=prefetched,
            momentum_weights=momentum_weights,
        )
        if "error" in bt:
            return {"error": bt["error"]}

        ae = bt.get("alpha_enhancements", {})
        return {
            "cumulative_return": bt["cumulative_return"],
            "annualized_return": bt["annualized_return"],
            "sharpe_ratio": bt["sharpe_ratio"],
            "max_drawdown": bt["max_drawdown"],
            "win_rate": bt["win_rate"],
            "alpha_vs_spy": bt["alpha_vs_spy"],
            "weeks": bt["weeks"],
            "stops_hit": ae.get("stop_triggered_count", 0),
            "trailing_hit": ae.get("trailing_triggered_count", 0),
            "weekly_details": bt.get("weekly_details", []),
        }
    finally:
        RC.BACKTEST_STOP_MULT = orig_stop
        RC.BACKTEST_TRAILING_MULT = orig_trail
        RC.BACKTEST_TRAILING_ACTIVATE = orig_act


async def main():
    from app.services.rotation_service import _fetch_backtest_data

    total_phase_a = _total_phase_a_combos()
    total_phase_b = len(WEIGHT_GRID)

    print("=" * 70)
    print("StockQueen V5 Walk-Forward Validation (Phase A + Phase B Weight Search)")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Windows: {len(WINDOWS)}")
    print(f"Phase A params per window: {total_phase_a}")
    print(f"  TOP_N: {TOP_N_VALUES}")
    print(f"  HB: {BONUS_VALUES}")
    print(f"  STOP: {ATR_STOP_VALUES} (locked)")
    print(f"  TRAILING_MULT: {TRAILING_MULT_VALUES} (locked)")
    print(f"  TRAILING_ACTIVATE: {TRAILING_ACTIVATE_VALUES} (locked)")
    print(f"Phase B momentum weight combos: {total_phase_b}")
    print(f"  WEIGHT_GRID: {WEIGHT_GRID}")
    print()

    t0 = time.time()

    # Fetch ALL data once (covering the full date range: 2021-01 to 2026-03)
    print("Fetching data for full period (2021-01 to 2026-03)...")
    prefetched = await _fetch_backtest_data("2021-01-01", "2026-03-01")
    if "error" in prefetched:
        print(f"FATAL: {prefetched['error']}")
        return

    n_tickers = len(prefetched.get("histories", {}))
    n_fund = len(prefetched.get("bt_fundamentals", {}))
    print(f"Data ready: {n_tickers} tickers, {n_fund} with earnings/cashflow")
    print()

    window_results = []
    all_oos_weekly_returns = []

    for w in WINDOWS:
        print(f"{'='*70}")
        print(f"  {w['name']}: Train [{w['train_start']} ~ {w['train_end']}]")
        print(f"         Test  [{w['test_start']} ~ {w['test_end']}]")
        print(f"{'='*70}")

        # ================================================================
        # PHASE A: Search TOP_N x HOLDING_BONUS (momentum weights = default)
        # ================================================================
        print(f"\n  [PHASE A] Running {total_phase_a} combos on training window...")
        t1 = time.time()
        phase_a_results = await run_phase_a_search(
            w["train_start"], w["train_end"], prefetched
        )
        t_phase_a = time.time() - t1

        if not phase_a_results:
            print(f"  WARNING: No valid results for Phase A in {w['name']}")
            window_results.append({"window": w["name"], "error": "no Phase A results"})
            continue

        best_a = phase_a_results[0]
        print(f"\n  [PHASE A] Done in {t_phase_a:.0f}s. {len(phase_a_results)} valid combos.")
        print(f"  [PHASE A] Best: TOP_N={best_a['top_n']} HB={best_a['holding_bonus']} "
              f"STOP={best_a['atr_stop']} TRAIL={best_a['trailing_mult']} "
              f"ACT={best_a['trailing_activate']}")
        print(f"  [PHASE A] Train Sharpe={best_a['sharpe_ratio']:.2f} "
              f"Return={best_a['cumulative_return']:.1%} "
              f"MaxDD={best_a['max_drawdown']:.1%}")

        print(f"\n  [PHASE A] Top 5:")
        for idx, r in enumerate(phase_a_results[:5]):
            print(f"    #{idx+1}: top={r['top_n']} hb={r['holding_bonus']} "
                  f"-> Sharpe={r['sharpe_ratio']:.2f} Return={r['cumulative_return']:.1%}")

        # ================================================================
        # PHASE B: Lock TOP_N/HB, search momentum weight grid
        # ================================================================
        print(f"\n  [PHASE B] Searching {total_phase_b} momentum weight combos "
              f"(locked TOP_N={best_a['top_n']}, HB={best_a['holding_bonus']})...")
        t2 = time.time()
        phase_b_results = await run_phase_b_search(
            start_date=w["train_start"],
            end_date=w["train_end"],
            top_n=best_a["top_n"],
            holding_bonus=best_a["holding_bonus"],
            atr_stop=best_a["atr_stop"],
            trailing_mult=best_a["trailing_mult"],
            trailing_activate=best_a["trailing_activate"],
            prefetched=prefetched,
        )
        t_phase_b = time.time() - t2

        best_weights = None
        if phase_b_results:
            best_b = phase_b_results[0]
            best_weights = best_b["momentum_weights"]
            print(f"\n  [PHASE B] Done in {t_phase_b:.0f}s. {len(phase_b_results)} valid combos.")
            print(f"  [PHASE B] Best weights: w1w={best_b['w1w']:.2f} "
                  f"w1m={best_b['w1m']:.2f} w3m={best_b['w3m']:.2f}")
            print(f"  [PHASE B] Train Sharpe={best_b['sharpe_ratio']:.2f} "
                  f"Return={best_b['cumulative_return']:.1%} "
                  f"MaxDD={best_b['max_drawdown']:.1%}")

            # Compare Phase B best vs Phase A best (without weight override)
            sharpe_improvement = best_b["sharpe_ratio"] - best_a["sharpe_ratio"]
            print(f"  [PHASE B] Sharpe improvement over Phase A: {sharpe_improvement:+.3f}")

            print(f"\n  [PHASE B] All weight results:")
            for idx, r in enumerate(phase_b_results):
                marker = " <-- BEST" if idx == 0 else ""
                print(f"    #{idx+1}: ({r['w1w']:.2f}, {r['w1m']:.2f}, {r['w3m']:.2f}) "
                      f"-> Sharpe={r['sharpe_ratio']:.2f} Return={r['cumulative_return']:.1%}"
                      f"{marker}")
        else:
            print(f"\n  [PHASE B] WARNING: No valid Phase B results, using default weights")

        # ================================================================
        # OOS TEST: Apply best params + best weights to out-of-sample
        # ================================================================
        print(f"\n  [TEST] Applying best params to out-of-sample window...")
        t3 = time.time()
        oos_result = await run_single_backtest(
            w["test_start"], w["test_end"],
            top_n=best_a["top_n"],
            holding_bonus=best_a["holding_bonus"],
            atr_stop=best_a["atr_stop"],
            trailing_mult=best_a["trailing_mult"],
            trailing_activate=best_a["trailing_activate"],
            prefetched=prefetched,
            momentum_weights=best_weights,
        )
        t_test = time.time() - t3

        if "error" in oos_result:
            print(f"  [TEST] ERROR: {oos_result['error']}")
            window_results.append({
                "window": w["name"],
                "phase_a_best": {
                    "top_n": best_a["top_n"],
                    "holding_bonus": best_a["holding_bonus"],
                },
                "phase_b_best_weights": list(best_weights) if best_weights else None,
                "train_sharpe": best_a["sharpe_ratio"],
                "error": oos_result["error"],
            })
            continue

        print(f"  [TEST] Done in {t_test:.0f}s.")
        print(f"  [TEST] OOS Sharpe={oos_result['sharpe_ratio']:.2f} "
              f"Return={oos_result['cumulative_return']:.1%} "
              f"MaxDD={oos_result['max_drawdown']:.1%} "
              f"Alpha={oos_result['alpha_vs_spy']:.1%} "
              f"Stops={oos_result['stops_hit']} Trailing={oos_result['trailing_hit']}")

        # Collect OOS weekly returns for spliced equity curve
        for wd in oos_result.get("weekly_details", []):
            all_oos_weekly_returns.append(wd["return_pct"] / 100.0)

        # Compare train vs test (overfitting check)
        train_sharpe = best_b["sharpe_ratio"] if phase_b_results else best_a["sharpe_ratio"]
        sharpe_decay = train_sharpe - oos_result["sharpe_ratio"]
        train_return = best_b["cumulative_return"] if phase_b_results else best_a["cumulative_return"]
        return_decay = train_return - oos_result["cumulative_return"]

        print(f"\n  [COMPARE] Sharpe decay: {train_sharpe:.2f} -> "
              f"{oos_result['sharpe_ratio']:.2f} (D={sharpe_decay:+.2f})")
        print(f"  [COMPARE] Return decay: {train_return:.1%} -> "
              f"{oos_result['cumulative_return']:.1%} (D={return_decay:+.1%})")

        if sharpe_decay > 0.5:
            print(f"  [WARN] LARGE Sharpe decay -- possible overfitting")
        elif sharpe_decay < 0:
            print(f"  [OK] OOS performed BETTER than training -- robust signal")
        else:
            print(f"  [INFO] Moderate decay -- within normal range")

        window_results.append({
            "window": w["name"],
            "train_period": f"{w['train_start']} ~ {w['train_end']}",
            "test_period": f"{w['test_start']} ~ {w['test_end']}",
            "phase_a_best": {
                "top_n": best_a["top_n"],
                "holding_bonus": best_a["holding_bonus"],
                "atr_stop": best_a["atr_stop"],
                "trailing_mult": best_a["trailing_mult"],
                "trailing_activate": best_a["trailing_activate"],
                "train_sharpe": best_a["sharpe_ratio"],
                "train_return": best_a["cumulative_return"],
            },
            "phase_b_best": {
                "momentum_weights": list(best_weights) if best_weights else None,
                "train_sharpe": best_b["sharpe_ratio"] if phase_b_results else None,
                "train_return": best_b["cumulative_return"] if phase_b_results else None,
                "sharpe_improvement": round(sharpe_improvement, 3) if phase_b_results else None,
            },
            "phase_b_all_results": [
                {
                    "weights": list(r["momentum_weights"]),
                    "sharpe": r["sharpe_ratio"],
                    "return": r["cumulative_return"],
                }
                for r in phase_b_results
            ] if phase_b_results else [],
            "oos_results": {
                "sharpe": oos_result["sharpe_ratio"],
                "return": oos_result["cumulative_return"],
                "annualized_return": oos_result["annualized_return"],
                "max_drawdown": oos_result["max_drawdown"],
                "win_rate": oos_result["win_rate"],
                "alpha_vs_spy": oos_result["alpha_vs_spy"],
                "weeks": oos_result["weeks"],
                "stops_hit": oos_result["stops_hit"],
                "trailing_hit": oos_result["trailing_hit"],
            },
            "decay": {
                "sharpe_decay": round(sharpe_decay, 3),
                "return_decay": round(return_decay, 4),
            },
        })
        print()

    # -- OVERALL SUMMARY --
    print(f"\n{'='*70}")
    print(f"WALK-FORWARD OVERALL SUMMARY (V5 Phase A+B)")
    print(f"{'='*70}")

    valid_windows = [w for w in window_results if "oos_results" in w]

    if valid_windows:
        oos_sharpes = [w["oos_results"]["sharpe"] for w in valid_windows]
        oos_returns = [w["oos_results"]["return"] for w in valid_windows]
        oos_maxdds = [w["oos_results"]["max_drawdown"] for w in valid_windows]
        train_sharpes = [
            w["phase_b_best"]["train_sharpe"]
            if w["phase_b_best"]["train_sharpe"] is not None
            else w["phase_a_best"]["train_sharpe"]
            for w in valid_windows
        ]
        sharpe_decays = [w["decay"]["sharpe_decay"] for w in valid_windows]

        # Spliced OOS equity curve
        spliced_cum = 0.0
        if all_oos_weekly_returns:
            spliced_cum = float(np.prod([1 + r for r in all_oos_weekly_returns]) - 1)
            n_weeks = len(all_oos_weekly_returns)
            spliced_ann = float((1 + spliced_cum) ** (52 / n_weeks) - 1) if n_weeks > 0 else 0
            spliced_vol = float(np.std(all_oos_weekly_returns) * np.sqrt(52)) if n_weeks > 1 else 1
            spliced_sharpe = spliced_ann / spliced_vol if spliced_vol > 0 else 0

            # Spliced max drawdown
            equity = 1.0
            peak = 1.0
            spliced_maxdd = 0.0
            for r in all_oos_weekly_returns:
                equity *= (1 + r)
                if equity > peak:
                    peak = equity
                dd = (equity - peak) / peak
                if dd < spliced_maxdd:
                    spliced_maxdd = dd
        else:
            spliced_ann = 0
            spliced_sharpe = 0
            spliced_maxdd = 0
            n_weeks = 0

        print(f"\nPer-window OOS performance:")
        for w in valid_windows:
            oos = w["oos_results"]
            pa = w["phase_a_best"]
            pb = w["phase_b_best"]
            wt_str = f"({pb['momentum_weights'][0]:.2f},{pb['momentum_weights'][1]:.2f},{pb['momentum_weights'][2]:.2f})" if pb.get("momentum_weights") else "default"
            print(f"  {w['window']}: Sharpe={oos['sharpe']:.2f} "
                  f"Return={oos['return']:.1%} MaxDD={oos['max_drawdown']:.1%} "
                  f"Alpha={oos['alpha_vs_spy']:.1%} "
                  f"| top={pa['top_n']} hb={pa['holding_bonus']} "
                  f"weights={wt_str}")

        print(f"\nSpliced OOS equity curve ({n_weeks} weeks):")
        print(f"  Cumulative return: {spliced_cum:.1%}")
        print(f"  Annualized return: {spliced_ann:.1%}")
        print(f"  Sharpe ratio:      {spliced_sharpe:.2f}")
        print(f"  Max drawdown:      {spliced_maxdd:.1%}")

        print(f"\nOverfitting check:")
        print(f"  Mean train Sharpe:  {np.mean(train_sharpes):.2f}")
        print(f"  Mean OOS Sharpe:    {np.mean(oos_sharpes):.2f}")
        print(f"  Mean Sharpe decay:  {np.mean(sharpe_decays):.2f}")

        if np.mean(sharpe_decays) > 0.5:
            verdict = "[WARN] HIGH OVERFITTING RISK -- train >> OOS"
        elif np.mean(sharpe_decays) > 0.2:
            verdict = "[INFO] MODERATE decay -- some overfitting but strategy has edge"
        elif all(s > 0 for s in oos_sharpes):
            verdict = "[OK] ROBUST -- positive OOS Sharpe in all windows"
        else:
            verdict = "[FAIL] WEAK -- negative OOS Sharpe in some windows"

        print(f"\n  VERDICT: {verdict}")

        # Param stability check
        print(f"\nParameter stability across windows:")
        top_ns = [w["phase_a_best"]["top_n"] for w in valid_windows]
        hbs = [w["phase_a_best"]["holding_bonus"] for w in valid_windows]
        weight_strs = [
            str(w["phase_b_best"]["momentum_weights"])
            if w["phase_b_best"].get("momentum_weights") else "default"
            for w in valid_windows
        ]
        print(f"  TOP_N:   {top_ns}  {'[OK] STABLE' if len(set(top_ns)) <= 2 else '[WARN] VARIES'}")
        print(f"  HB:      {hbs}  {'[OK] STABLE' if len(set(hbs)) <= 2 else '[WARN] VARIES'}")
        print(f"  Weights: {weight_strs}  {'[OK] STABLE' if len(set(weight_strs)) <= 2 else '[WARN] VARIES'}")

        # Phase B impact summary
        print(f"\nPhase B (momentum weight) impact:")
        for w in valid_windows:
            pb = w["phase_b_best"]
            if pb.get("sharpe_improvement") is not None:
                print(f"  {w['window']}: Sharpe improvement from weight search: "
                      f"{pb['sharpe_improvement']:+.3f}")

        # Save results
        summary = {
            "test": "Walk-Forward Validation V5",
            "version": "V5 Phase A+B Weight Search",
            "timestamp": datetime.now().isoformat(),
            "windows": window_results,
            "spliced_oos": {
                "cumulative_return": round(spliced_cum, 4),
                "annualized_return": round(spliced_ann, 4),
                "sharpe_ratio": round(spliced_sharpe, 2),
                "max_drawdown": round(spliced_maxdd, 4),
                "total_weeks": n_weeks,
                "weekly_returns": [round(r, 6) for r in all_oos_weekly_returns],
            },
            "overfitting_check": {
                "mean_train_sharpe": round(float(np.mean(train_sharpes)), 2),
                "mean_oos_sharpe": round(float(np.mean(oos_sharpes)), 2),
                "mean_sharpe_decay": round(float(np.mean(sharpe_decays)), 2),
                "oos_sharpes": [round(s, 2) for s in oos_sharpes],
                "verdict": verdict,
            },
            "parameter_stability": {
                "top_n_values": top_ns,
                "holding_bonus_values": hbs,
                "momentum_weights": [
                    w["phase_b_best"]["momentum_weights"] for w in valid_windows
                ],
                "stable": len(set(top_ns)) <= 2 and len(set(weight_strs)) <= 2,
            },
        }

        outfile = RESULTS_DIR / "walk_forward_v5.json"
        with open(outfile, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"\nResults saved: {outfile}")

    else:
        print("\nNo valid windows completed. Check errors above.")

    elapsed = time.time() - t0
    print(f"\n{'='*70}")
    print(f"WALK-FORWARD COMPLETE in {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
