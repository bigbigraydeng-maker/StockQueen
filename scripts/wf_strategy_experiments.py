"""
StockQueen - Walk-Forward 策略实验（三组对比）
==============================================
针对已识别的结构性问题，通过 WF 对比测试量化改进效果。

实验 A: Hedge Overlay 对比
  - baseline: hedge_overlay=False（当前 WF 基准）
  - experiment: hedge_overlay=True（启用对冲叠加层）

实验 B: 趋势保留豁免
  - baseline: trend_hold_exempt=False（当前：跌出 TOP_N 立即卖出）
  - experiment: trend_hold_exempt=True（高分+RS>0 给一次保留周）

实验 C: Choppy MR 条件激活
  - baseline: active_regimes={bull}（当前）
  - experiment: active_regimes={bull, choppy}，choppy 用 RSI<=22

用法：
    python scripts/wf_strategy_experiments.py --experiment hedge   # 只跑 A
    python scripts/wf_strategy_experiments.py --experiment hold    # 只跑 B
    python scripts/wf_strategy_experiments.py --experiment mr      # 只跑 C
    python scripts/wf_strategy_experiments.py --experiment all     # 全部
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

# Windows GBK 终端兼容
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

RESULTS_DIR = Path(__file__).parent / "stress_test_results"
RESULTS_DIR.mkdir(exist_ok=True)

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = RESULTS_DIR / f"strategy_experiments_{TIMESTAMP}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logging.getLogger("app.services.alphavantage_client").setLevel(logging.WARNING)
logging.getLogger("app.services.rotation_service").setLevel(logging.WARNING)
logging.getLogger("app.services.mean_reversion_service").setLevel(logging.WARNING)

logger = logging.getLogger("strategy_experiments")

# ============================================================
# Walk-Forward 窗口（与 walk_forward_v5_full.py 保持一致）
# ============================================================
WINDOWS = [
    {"name": "W1", "train": ("2018-01-01", "2019-12-31"), "test": ("2020-01-01", "2020-12-31")},
    {"name": "W2", "train": ("2018-01-01", "2020-12-31"), "test": ("2021-01-01", "2021-12-31")},
    {"name": "W3", "train": ("2018-01-01", "2021-12-31"), "test": ("2022-01-01", "2022-12-31")},
    {"name": "W4", "train": ("2018-01-01", "2022-12-31"), "test": ("2023-01-01", "2023-12-31")},
    {"name": "W5", "train": ("2018-01-01", "2023-12-31"), "test": ("2024-01-01", "2024-12-31")},
    {"name": "W6", "train": ("2018-01-01", "2024-12-31"), "test": ("2025-01-01", "2025-12-31")},
]

V4_TOP_N_RANGE = [3, 4, 5, 6, 7]
V4_HB_RANGE = [0.0, 0.5, 1.0]
MR_RSI_RANGE = [20, 22, 24, 26, 28]  # 扩展到更低值用于 choppy 实验


def _equity_to_stats(equity_curve: list) -> dict:
    if len(equity_curve) < 2:
        return {"sharpe_ratio": 0.0, "cumulative_return": 0.0,
                "max_drawdown": 0.0, "annualized_return": 0.0}
    daily_returns = [(equity_curve[i] / equity_curve[i - 1]) - 1
                     for i in range(1, len(equity_curve))]
    total_days = len(daily_returns)
    cum_ret = equity_curve[-1] - 1.0
    ann_ret = (equity_curve[-1] ** (252 / max(total_days, 1))) - 1
    vol = float(np.std(daily_returns) * np.sqrt(252)) if len(daily_returns) > 1 else 0.0
    sharpe = ann_ret / vol if vol > 0 else 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return {
        "sharpe_ratio": round(sharpe, 3),
        "cumulative_return": round(cum_ret, 4),
        "max_drawdown": round(max_dd, 4),
        "annualized_return": round(ann_ret, 4),
    }


# ============================================================
# 实验 A: Hedge Overlay WF 对比
# ============================================================

async def run_experiment_hedge(v4_prefetched: dict) -> dict:
    """跑 V4 baseline (no hedge) vs V4 + hedge_overlay 的 WF 对比"""
    from app.services.rotation_service import run_rotation_backtest

    logger.info("=" * 60)
    logger.info("实验 A: Hedge Overlay WF 对比")
    logger.info("=" * 60)

    results = {"experiment": "hedge_overlay", "windows": []}

    for w in WINDOWS:
        w_name = w["name"]
        train_start, train_end = w["train"]
        test_start, test_end = w["test"]

        logger.info(f"\n--- {w_name}: 训练 {train_start}~{train_end} ---")

        # 训练期找最佳参数（不开 hedge，因为 hedge 是独立叠加层，不影响 alpha 参数选择）
        best_tn, best_hb, is_sharpe = 3, 0.0, -999.0
        for tn in V4_TOP_N_RANGE:
            for hb in V4_HB_RANGE:
                try:
                    result = await run_rotation_backtest(
                        start_date=train_start, end_date=train_end,
                        top_n=tn, holding_bonus=hb,
                        _prefetched=v4_prefetched,
                    )
                    s = result.get("sharpe_ratio", -999.0)
                    if s > is_sharpe:
                        is_sharpe, best_tn, best_hb = s, tn, hb
                except Exception as e:
                    logger.warning(f"[Hedge {w_name}] train tn={tn} hb={hb} error: {e}")

        logger.info(f"[Hedge {w_name}] best param: top_n={best_tn} HB={best_hb} IS={is_sharpe:.3f}")

        # OOS: baseline (no hedge) vs experiment (with hedge)
        try:
            oos_baseline = await run_rotation_backtest(
                start_date=test_start, end_date=test_end,
                top_n=best_tn, holding_bonus=best_hb,
                _prefetched=v4_prefetched,
                hedge_overlay=False,
            )
            oos_hedge = await run_rotation_backtest(
                start_date=test_start, end_date=test_end,
                top_n=best_tn, holding_bonus=best_hb,
                _prefetched=v4_prefetched,
                hedge_overlay=True,
            )

            b_sharpe = oos_baseline.get("sharpe_ratio", 0.0)
            h_sharpe = oos_hedge.get("sharpe_ratio", 0.0)
            b_dd = oos_baseline.get("max_drawdown", 0.0)
            h_dd = oos_hedge.get("max_drawdown", 0.0)

            window_result = {
                "window": w_name,
                "test_period": f"{test_start}~{test_end}",
                "best_param": {"top_n": best_tn, "holding_bonus": best_hb},
                "is_sharpe": round(is_sharpe, 3),
                "baseline": {"sharpe": round(b_sharpe, 3), "max_dd": round(b_dd, 4),
                             "cum_ret": oos_baseline.get("cumulative_return")},
                "hedge": {"sharpe": round(h_sharpe, 3), "max_dd": round(h_dd, 4),
                          "cum_ret": oos_hedge.get("cumulative_return")},
                "delta_sharpe": round(h_sharpe - b_sharpe, 3),
                "delta_max_dd": round(h_dd - b_dd, 4),
            }
            results["windows"].append(window_result)
            logger.info(
                f"[Hedge {w_name}] OOS: baseline={b_sharpe:.3f} hedge={h_sharpe:.3f} "
                f"delta={h_sharpe - b_sharpe:+.3f} | MaxDD: {b_dd:.3f}->{h_dd:.3f}"
            )
        except Exception as e:
            logger.error(f"[Hedge {w_name}] OOS failed: {e}")
            results["windows"].append({"window": w_name, "error": str(e)})

    # 汇总
    valid = [w for w in results["windows"] if "baseline" in w]
    if valid:
        avg_b = np.mean([w["baseline"]["sharpe"] for w in valid])
        avg_h = np.mean([w["hedge"]["sharpe"] for w in valid])
        results["summary"] = {
            "avg_baseline_sharpe": round(float(avg_b), 3),
            "avg_hedge_sharpe": round(float(avg_h), 3),
            "avg_delta": round(float(avg_h - avg_b), 3),
            "windows_improved": sum(1 for w in valid if w["delta_sharpe"] > 0),
            "total_windows": len(valid),
        }
        logger.info(f"\n[Hedge] 汇总: baseline avg={avg_b:.3f} hedge avg={avg_h:.3f} delta={avg_h-avg_b:+.3f}")

    return results


# ============================================================
# 实验 B: 趋势保留豁免
# ============================================================

async def run_experiment_hold(v4_prefetched: dict) -> dict:
    """跑 V4 baseline vs V4 + trend_hold_exempt 的 WF 对比"""
    from app.services.rotation_service import run_rotation_backtest

    logger.info("=" * 60)
    logger.info("实验 B: 趋势保留豁免 WF 对比")
    logger.info("=" * 60)

    results = {"experiment": "trend_hold_exempt", "windows": []}

    for w in WINDOWS:
        w_name = w["name"]
        train_start, train_end = w["train"]
        test_start, test_end = w["test"]

        logger.info(f"\n--- {w_name}: 训练 {train_start}~{train_end} ---")

        # 训练期：分别找 baseline 和 exempt 的最佳参数
        best_baseline = {"tn": 3, "hb": 0.0, "sharpe": -999.0}
        best_exempt = {"tn": 3, "hb": 0.0, "sharpe": -999.0}

        for tn in V4_TOP_N_RANGE:
            for hb in V4_HB_RANGE:
                try:
                    # baseline
                    r_base = await run_rotation_backtest(
                        start_date=train_start, end_date=train_end,
                        top_n=tn, holding_bonus=hb,
                        _prefetched=v4_prefetched,
                        trend_hold_exempt=False,
                    )
                    s = r_base.get("sharpe_ratio", -999.0)
                    if s > best_baseline["sharpe"]:
                        best_baseline = {"tn": tn, "hb": hb, "sharpe": s}

                    # exempt
                    r_ex = await run_rotation_backtest(
                        start_date=train_start, end_date=train_end,
                        top_n=tn, holding_bonus=hb,
                        _prefetched=v4_prefetched,
                        trend_hold_exempt=True,
                    )
                    s = r_ex.get("sharpe_ratio", -999.0)
                    if s > best_exempt["sharpe"]:
                        best_exempt = {"tn": tn, "hb": hb, "sharpe": s}
                except Exception as e:
                    logger.warning(f"[Hold {w_name}] train tn={tn} hb={hb} error: {e}")

        logger.info(f"[Hold {w_name}] baseline best: tn={best_baseline['tn']} IS={best_baseline['sharpe']:.3f}")
        logger.info(f"[Hold {w_name}] exempt best:   tn={best_exempt['tn']} IS={best_exempt['sharpe']:.3f}")

        # OOS
        try:
            oos_base = await run_rotation_backtest(
                start_date=test_start, end_date=test_end,
                top_n=best_baseline["tn"], holding_bonus=best_baseline["hb"],
                _prefetched=v4_prefetched, trend_hold_exempt=False,
            )
            oos_ex = await run_rotation_backtest(
                start_date=test_start, end_date=test_end,
                top_n=best_exempt["tn"], holding_bonus=best_exempt["hb"],
                _prefetched=v4_prefetched, trend_hold_exempt=True,
            )

            b_sharpe = oos_base.get("sharpe_ratio", 0.0)
            e_sharpe = oos_ex.get("sharpe_ratio", 0.0)

            window_result = {
                "window": w_name,
                "test_period": f"{test_start}~{test_end}",
                "baseline": {
                    "param": {"top_n": best_baseline["tn"], "hb": best_baseline["hb"]},
                    "is_sharpe": round(best_baseline["sharpe"], 3),
                    "oos_sharpe": round(b_sharpe, 3),
                    "max_dd": round(oos_base.get("max_drawdown", 0.0), 4),
                    "cum_ret": oos_base.get("cumulative_return"),
                },
                "exempt": {
                    "param": {"top_n": best_exempt["tn"], "hb": best_exempt["hb"]},
                    "is_sharpe": round(best_exempt["sharpe"], 3),
                    "oos_sharpe": round(e_sharpe, 3),
                    "max_dd": round(oos_ex.get("max_drawdown", 0.0), 4),
                    "cum_ret": oos_ex.get("cumulative_return"),
                },
                "delta_sharpe": round(e_sharpe - b_sharpe, 3),
            }
            results["windows"].append(window_result)
            logger.info(f"[Hold {w_name}] OOS: baseline={b_sharpe:.3f} exempt={e_sharpe:.3f} delta={e_sharpe-b_sharpe:+.3f}")
        except Exception as e:
            logger.error(f"[Hold {w_name}] OOS failed: {e}")
            results["windows"].append({"window": w_name, "error": str(e)})

    valid = [w for w in results["windows"] if "baseline" in w]
    if valid:
        avg_b = np.mean([w["baseline"]["oos_sharpe"] for w in valid])
        avg_e = np.mean([w["exempt"]["oos_sharpe"] for w in valid])
        results["summary"] = {
            "avg_baseline_sharpe": round(float(avg_b), 3),
            "avg_exempt_sharpe": round(float(avg_e), 3),
            "avg_delta": round(float(avg_e - avg_b), 3),
            "windows_improved": sum(1 for w in valid if w["delta_sharpe"] > 0),
            "total_windows": len(valid),
        }
        logger.info(f"\n[Hold] 汇总: baseline avg={avg_b:.3f} exempt avg={avg_e:.3f} delta={avg_e-avg_b:+.3f}")

    return results


# ============================================================
# 实验 C: Choppy MR 条件激活
# ============================================================

async def run_experiment_mr(mr_prefetched) -> dict:
    """跑 MR baseline (bull only) vs MR + choppy (RSI tightened) 的 WF 对比"""
    from app.services.mean_reversion_service import (
        run_mean_reversion_backtest,
        MeanReversionConfig,
    )
    import app.services.mean_reversion_service as _mrsvc

    logger.info("=" * 60)
    logger.info("实验 C: Choppy MR 条件激活 WF 对比")
    logger.info("=" * 60)

    results = {"experiment": "choppy_mr", "windows": []}

    CHOPPY_RSI_CANDIDATES = [20, 22, 24]  # choppy 时更严格的 RSI 阈值候选

    for w in WINDOWS:
        w_name = w["name"]
        train_start, train_end = w["train"]
        test_start, test_end = w["test"]

        logger.info(f"\n--- {w_name}: 训练 {train_start}~{train_end} ---")

        # 训练期：baseline (bull only)
        default_rsi = MeanReversionConfig.RSI_ENTRY_THRESHOLD
        best_base_rsi, best_base_sharpe = 28, -999.0
        for rsi in MR_RSI_RANGE:
            MeanReversionConfig.RSI_ENTRY_THRESHOLD = rsi
            _mrsvc.MRC.RSI_ENTRY_THRESHOLD = rsi
            try:
                r = await run_mean_reversion_backtest(
                    start_date=train_start, end_date=train_end,
                    _prefetched=mr_prefetched,
                    active_regimes_override={"bull"},
                )
                s = r.get("sharpe_ratio", -999.0)
                if s > best_base_sharpe:
                    best_base_sharpe, best_base_rsi = s, rsi
            except Exception as e:
                logger.warning(f"[MR {w_name}] baseline RSI={rsi} error: {e}")
            finally:
                MeanReversionConfig.RSI_ENTRY_THRESHOLD = default_rsi
                _mrsvc.MRC.RSI_ENTRY_THRESHOLD = default_rsi

        # 训练期：experiment (bull + choppy)
        best_ex_rsi, best_ex_choppy_rsi, best_ex_sharpe = 28, 22, -999.0
        for rsi in MR_RSI_RANGE:
            for c_rsi in CHOPPY_RSI_CANDIDATES:
                MeanReversionConfig.RSI_ENTRY_THRESHOLD = rsi
                _mrsvc.MRC.RSI_ENTRY_THRESHOLD = rsi
                try:
                    r = await run_mean_reversion_backtest(
                        start_date=train_start, end_date=train_end,
                        _prefetched=mr_prefetched,
                        active_regimes_override={"bull", "choppy"},
                        choppy_rsi_threshold=c_rsi,
                    )
                    s = r.get("sharpe_ratio", -999.0)
                    if s > best_ex_sharpe:
                        best_ex_sharpe = s
                        best_ex_rsi = rsi
                        best_ex_choppy_rsi = c_rsi
                except Exception as e:
                    logger.warning(f"[MR {w_name}] experiment RSI={rsi} choppy_RSI={c_rsi} error: {e}")
                finally:
                    MeanReversionConfig.RSI_ENTRY_THRESHOLD = default_rsi
                    _mrsvc.MRC.RSI_ENTRY_THRESHOLD = default_rsi

        logger.info(f"[MR {w_name}] baseline best: RSI={best_base_rsi} IS={best_base_sharpe:.3f}")
        logger.info(f"[MR {w_name}] experiment best: RSI={best_ex_rsi} choppy_RSI={best_ex_choppy_rsi} IS={best_ex_sharpe:.3f}")

        # OOS
        try:
            # baseline
            MeanReversionConfig.RSI_ENTRY_THRESHOLD = best_base_rsi
            _mrsvc.MRC.RSI_ENTRY_THRESHOLD = best_base_rsi
            oos_base = await run_mean_reversion_backtest(
                start_date=test_start, end_date=test_end,
                _prefetched=mr_prefetched,
                active_regimes_override={"bull"},
            )
            MeanReversionConfig.RSI_ENTRY_THRESHOLD = default_rsi
            _mrsvc.MRC.RSI_ENTRY_THRESHOLD = default_rsi

            # experiment
            MeanReversionConfig.RSI_ENTRY_THRESHOLD = best_ex_rsi
            _mrsvc.MRC.RSI_ENTRY_THRESHOLD = best_ex_rsi
            oos_ex = await run_mean_reversion_backtest(
                start_date=test_start, end_date=test_end,
                _prefetched=mr_prefetched,
                active_regimes_override={"bull", "choppy"},
                choppy_rsi_threshold=best_ex_choppy_rsi,
            )
            MeanReversionConfig.RSI_ENTRY_THRESHOLD = default_rsi
            _mrsvc.MRC.RSI_ENTRY_THRESHOLD = default_rsi

            b_sharpe = oos_base.get("sharpe_ratio", 0.0)
            e_sharpe = oos_ex.get("sharpe_ratio", 0.0)

            window_result = {
                "window": w_name,
                "test_period": f"{test_start}~{test_end}",
                "baseline": {
                    "param": {"rsi": best_base_rsi, "regimes": ["bull"]},
                    "is_sharpe": round(best_base_sharpe, 3),
                    "oos_sharpe": round(b_sharpe, 3),
                    "max_dd": round(oos_base.get("max_drawdown", 0.0), 4),
                    "total_trades": oos_base.get("total_trades", 0),
                },
                "experiment": {
                    "param": {"rsi": best_ex_rsi, "choppy_rsi": best_ex_choppy_rsi,
                              "regimes": ["bull", "choppy"]},
                    "is_sharpe": round(best_ex_sharpe, 3),
                    "oos_sharpe": round(e_sharpe, 3),
                    "max_dd": round(oos_ex.get("max_drawdown", 0.0), 4),
                    "total_trades": oos_ex.get("total_trades", 0),
                },
                "delta_sharpe": round(e_sharpe - b_sharpe, 3),
            }
            results["windows"].append(window_result)
            logger.info(
                f"[MR {w_name}] OOS: baseline={b_sharpe:.3f} experiment={e_sharpe:.3f} "
                f"delta={e_sharpe-b_sharpe:+.3f} "
                f"trades: {oos_base.get('total_trades',0)} -> {oos_ex.get('total_trades',0)}"
            )
        except Exception as e:
            logger.error(f"[MR {w_name}] OOS failed: {e}")
            results["windows"].append({"window": w_name, "error": str(e)})
        finally:
            MeanReversionConfig.RSI_ENTRY_THRESHOLD = default_rsi
            _mrsvc.MRC.RSI_ENTRY_THRESHOLD = default_rsi

    valid = [w for w in results["windows"] if "baseline" in w]
    if valid:
        avg_b = np.mean([w["baseline"]["oos_sharpe"] for w in valid])
        avg_e = np.mean([w["experiment"]["oos_sharpe"] for w in valid])
        results["summary"] = {
            "avg_baseline_sharpe": round(float(avg_b), 3),
            "avg_experiment_sharpe": round(float(avg_e), 3),
            "avg_delta": round(float(avg_e - avg_b), 3),
            "windows_improved": sum(1 for w in valid if w["delta_sharpe"] > 0),
            "total_windows": len(valid),
        }
        logger.info(f"\n[MR] 汇总: baseline avg={avg_b:.3f} experiment avg={avg_e:.3f} delta={avg_e-avg_b:+.3f}")

    return results


# ============================================================
# Main
# ============================================================

async def main():
    parser = argparse.ArgumentParser(description="Strategy Experiments WF")
    parser.add_argument("--experiment", default="all",
                        choices=["hedge", "hold", "mr", "all"],
                        help="Which experiment to run")
    args = parser.parse_args()

    t_start = time.time()
    all_results = {}

    # 预取数据（V4 和 MR 共用 OHLCV）
    run_v4 = args.experiment in ("hedge", "hold", "all")
    run_mr = args.experiment in ("mr", "all")

    v4_prefetched = None
    mr_prefetched = None

    if run_v4:
        from app.services.rotation_service import _fetch_backtest_data
        logger.info("[Data] 预取 V4/Hedge/Hold 数据 (2018-01-01 ~ 2025-12-31)...")
        v4_prefetched = await _fetch_backtest_data("2018-01-01", "2025-12-31")
        if "error" in v4_prefetched:
            logger.error(f"V4 data fetch failed: {v4_prefetched['error']}")
            return
        logger.info(f"[Data] V4 预取完成: {len(v4_prefetched['histories'])} tickers")

    if run_mr:
        if v4_prefetched:
            mr_prefetched = v4_prefetched["histories"]
        else:
            from app.services.rotation_service import _fetch_backtest_data
            logger.info("[Data] 预取 MR 数据 (2018-01-01 ~ 2025-12-31)...")
            raw = await _fetch_backtest_data("2018-01-01", "2025-12-31")
            if "error" in raw:
                logger.error(f"MR data fetch failed: {raw['error']}")
                return
            mr_prefetched = raw["histories"]
        logger.info(f"[Data] MR 预取完成: {len(mr_prefetched)} tickers")

    # 运行实验
    if args.experiment in ("hedge", "all"):
        all_results["hedge_overlay"] = await run_experiment_hedge(v4_prefetched)

    if args.experiment in ("hold", "all"):
        all_results["trend_hold_exempt"] = await run_experiment_hold(v4_prefetched)

    if args.experiment in ("mr", "all"):
        all_results["choppy_mr"] = await run_experiment_mr(mr_prefetched)

    # 保存结果
    result_file = RESULTS_DIR / f"strategy_experiments_{TIMESTAMP}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)

    elapsed = time.time() - t_start
    logger.info(f"\n{'='*60}")
    logger.info(f"全部实验完成，耗时 {elapsed/60:.1f} 分钟")
    logger.info(f"结果: {result_file}")

    # 打印汇总
    for exp_name, exp_data in all_results.items():
        summary = exp_data.get("summary", {})
        if summary:
            logger.info(f"\n--- {exp_name} ---")
            for k, v in summary.items():
                logger.info(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
