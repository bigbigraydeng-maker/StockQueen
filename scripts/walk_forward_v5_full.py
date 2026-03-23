"""
StockQueen - Walk-Forward 全策略验证（V5完整版）
=================================================
在扩展Walk-Forward框架下验证三个策略（V4 / MR / ED）以及等权组合的样本外鲁棒性。

Walk-Forward逻辑：
  1. 训练期 → 每个策略独立找最优参数（by Sharpe）
  2. 测试期 → 应用训练期最优参数，记录OOS表现
  3. 组合层 → V4:0.5 + MR:0.25 + ED:0.25 等权混合OOS结果
  4. 最终汇总 → 平均OOS Sharpe、过拟合比率、参数稳定性、PASS/FAIL判定

扩展窗口（使用2018年数据）：
  W1: Train 2018-2019  Test 2020
  W2: Train 2018-2020  Test 2021
  W3: Train 2018-2021  Test 2022
  W4: Train 2018-2022  Test 2023
  W5: Train 2018-2023  Test 2024
  W6: Train 2018-2024  Test 2025  ← 新增（关税不确定性压力年）

通过标准：
  - 平均OOS Sharpe > 0.4
  - 过拟合比率 (OOS Sharpe / IS Sharpe) > 0.5

使用方法：
    cd StockQueen
    python scripts/walk_forward_v5_full.py                      # 全部策略
    python scripts/walk_forward_v5_full.py --strategy v4        # 只跑V4
    python scripts/walk_forward_v5_full.py --strategy portfolio # 只跑组合
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

# Windows GBK 终端兼容：强制 stdout/stderr 使用 UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

# ============================================================
# 结果目录 & 日志
# ============================================================

RESULTS_DIR = Path(__file__).parent / "stress_test_results"
RESULTS_DIR.mkdir(exist_ok=True)

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = RESULTS_DIR / f"walk_forward_v5_full_{TIMESTAMP}.log"

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
logging.getLogger("app.services.event_driven_service").setLevel(logging.WARNING)

logger = logging.getLogger("walk_forward_v5_full")

# ============================================================
# Walk-Forward 窗口定义
# ============================================================

WINDOWS = [
    {
        "name": "W1",
        "train": ("2018-01-01", "2019-12-31"),
        "test":  ("2020-01-01", "2020-12-31"),
    },
    {
        "name": "W2",
        "train": ("2018-01-01", "2020-12-31"),
        "test":  ("2021-01-01", "2021-12-31"),
    },
    {
        "name": "W3",
        "train": ("2018-01-01", "2021-12-31"),
        "test":  ("2022-01-01", "2022-12-31"),
    },
    {
        "name": "W4",
        "train": ("2018-01-01", "2022-12-31"),
        "test":  ("2023-01-01", "2023-12-31"),
    },
    {
        "name": "W5",
        "train": ("2018-01-01", "2023-12-31"),
        "test":  ("2024-01-01", "2024-12-31"),
    },
    {
        "name": "W6",
        "train": ("2018-01-01", "2024-12-31"),
        "test":  ("2025-01-01", "2025-12-31"),
    },
]

# 参数搜索范围
V4_TOP_N_RANGE    = [3, 4, 5, 6, 7]
V4_HB_RANGE       = [0.0, 0.5, 1.0]   # Holding Bonus 二维验证（HB锁0来自旧WF，需在扩展窗口重验证）
MR_RSI_RANGE      = [24, 26, 28, 30, 32]
ED_BEAT_RATE_RANGE = [0.60, 0.65, 0.70, 0.75]

# 组合权重（V4 : MR : ED）
PORTFOLIO_WEIGHTS = {"v4": 0.50, "mr": 0.25, "ed": 0.25}


# ============================================================
# 辅助函数
# ============================================================

def _combine_equity_curves(curves: dict, weights: dict) -> list:
    """
    将多个日级别equity_curve合并为加权组合曲线。
    curves: {strategy_name: [float, ...]}  从1.0开始
    weights: {strategy_name: float}
    返回合并后的equity_curve列表。
    """
    # 取最短长度对齐
    lengths = [len(v) for v in curves.values() if v]
    if not lengths:
        return [1.0]
    min_len = min(lengths)

    combined = []
    for i in range(min_len):
        val = sum(
            weights.get(name, 0.0) * curve[i]
            for name, curve in curves.items()
            if curve and i < len(curve)
        )
        combined.append(val)
    return combined


def _equity_to_stats(equity_curve: list) -> dict:
    """从equity_curve计算回测统计指标"""
    if len(equity_curve) < 2:
        return {"sharpe_ratio": 0.0, "cumulative_return": 0.0,
                "max_drawdown": 0.0, "annualized_return": 0.0}

    daily_returns = [
        (equity_curve[i] / equity_curve[i - 1]) - 1
        for i in range(1, len(equity_curve))
    ]
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
# V4 参数搜索
# ============================================================

async def _search_v4_best(
    train_start: str,
    train_end: str,
    v4_prefetched: dict,
    universe_filter: set = None,
) -> tuple:
    """训练期内搜索最佳 top_n × HB 组合，返回 (best_top_n, best_hb, best_sharpe)"""
    from app.services.rotation_service import run_rotation_backtest

    best_top_n = V4_TOP_N_RANGE[0]
    best_hb    = V4_HB_RANGE[0]
    best_sharpe = -999.0

    for tn in V4_TOP_N_RANGE:
        for hb in V4_HB_RANGE:
            try:
                result = await run_rotation_backtest(
                    start_date=train_start,
                    end_date=train_end,
                    top_n=tn,
                    holding_bonus=hb,
                    _prefetched=v4_prefetched,
                    universe_filter=universe_filter,
                )
                if "error" not in result:
                    s = result.get("sharpe_ratio", -999.0)
                    logger.debug(f"[V4 训练] top_n={tn} HB={hb} Sharpe={s:.3f}")
                    if s > best_sharpe:
                        best_sharpe = s
                        best_top_n  = tn
                        best_hb     = hb
            except Exception as e:
                logger.warning(f"[V4 训练] top_n={tn} HB={hb} 异常: {e}")

    logger.info(f"[V4 训练] 最佳 top_n={best_top_n} HB={best_hb} IS Sharpe={best_sharpe:.3f}")
    return best_top_n, best_hb, best_sharpe


async def _run_v4_oos(
    test_start: str,
    test_end: str,
    top_n: int,
    holding_bonus: float,
    v4_prefetched: dict,
    universe_filter: set = None,
) -> dict:
    """测试期运行V4，返回完整结果dict"""
    from app.services.rotation_service import run_rotation_backtest
    return await run_rotation_backtest(
        start_date=test_start,
        end_date=test_end,
        top_n=top_n,
        holding_bonus=holding_bonus,
        _prefetched=v4_prefetched,
        universe_filter=universe_filter,
    )


# ============================================================
# MR 参数搜索
# ============================================================

async def _search_mr_best(train_start: str, train_end: str, mr_prefetched) -> tuple:
    """训练期内搜索最佳 RSI_ENTRY_THRESHOLD，返回 (best_rsi, best_sharpe)"""
    from app.services.mean_reversion_service import (
        run_mean_reversion_backtest,
        MeanReversionConfig,
    )
    import app.services.mean_reversion_service as _mrsvc

    default_rsi = MeanReversionConfig.RSI_ENTRY_THRESHOLD
    best_rsi = MR_RSI_RANGE[0]
    best_sharpe = -999.0

    for rsi in MR_RSI_RANGE:
        MeanReversionConfig.RSI_ENTRY_THRESHOLD = rsi
        _mrsvc.MRC.RSI_ENTRY_THRESHOLD = rsi
        try:
            result = await run_mean_reversion_backtest(
                start_date=train_start,
                end_date=train_end,
                _prefetched=mr_prefetched,
            )
            if "error" not in result:
                s = result.get("sharpe_ratio", -999.0)
                logger.debug(f"[MR 训练] RSI={rsi} Sharpe={s:.3f}")
                if s > best_sharpe:
                    best_sharpe = s
                    best_rsi = rsi
        except Exception as e:
            logger.warning(f"[MR 训练] RSI={rsi} 异常: {e}")
        finally:
            MeanReversionConfig.RSI_ENTRY_THRESHOLD = default_rsi
            _mrsvc.MRC.RSI_ENTRY_THRESHOLD = default_rsi

    logger.info(f"[MR 训练] 最佳 RSI_ENTRY_THRESHOLD={best_rsi} IS Sharpe={best_sharpe:.3f}")
    return best_rsi, best_sharpe


async def _run_mr_oos(test_start: str, test_end: str, rsi_threshold: float, mr_prefetched) -> dict:
    """测试期运行MR，返回完整结果dict"""
    from app.services.mean_reversion_service import (
        run_mean_reversion_backtest,
        MeanReversionConfig,
    )
    import app.services.mean_reversion_service as _mrsvc

    default_rsi = MeanReversionConfig.RSI_ENTRY_THRESHOLD
    MeanReversionConfig.RSI_ENTRY_THRESHOLD = rsi_threshold
    _mrsvc.MRC.RSI_ENTRY_THRESHOLD = rsi_threshold
    try:
        return await run_mean_reversion_backtest(
            start_date=test_start,
            end_date=test_end,
            _prefetched=mr_prefetched,
        )
    finally:
        MeanReversionConfig.RSI_ENTRY_THRESHOLD = default_rsi
        _mrsvc.MRC.RSI_ENTRY_THRESHOLD = default_rsi


# ============================================================
# ED 参数搜索
# ============================================================

async def _search_ed_best(train_start: str, train_end: str, ed_price, ed_fund) -> tuple:
    """训练期内搜索最佳 MIN_BEAT_RATE，返回 (best_rate, best_sharpe)"""
    from app.services.event_driven_service import (
        run_event_driven_backtest,
        EventDrivenConfig,
    )
    import app.services.event_driven_service as _edsvc

    default_rate = EventDrivenConfig.MIN_BEAT_RATE
    best_rate = ED_BEAT_RATE_RANGE[0]
    best_sharpe = -999.0

    for rate in ED_BEAT_RATE_RANGE:
        EventDrivenConfig.MIN_BEAT_RATE = rate
        _edsvc.EDC.MIN_BEAT_RATE = rate
        try:
            result = await run_event_driven_backtest(
                start_date=train_start,
                end_date=train_end,
                _prefetched=ed_price,
                _prefetched_fundamentals=ed_fund,
            )
            if "error" not in result:
                s = result.get("sharpe_ratio", -999.0)
                logger.debug(f"[ED 训练] beat_rate={rate} Sharpe={s:.3f}")
                if s > best_sharpe:
                    best_sharpe = s
                    best_rate = rate
        except Exception as e:
            logger.warning(f"[ED 训练] beat_rate={rate} 异常: {e}")
        finally:
            EventDrivenConfig.MIN_BEAT_RATE = default_rate
            _edsvc.EDC.MIN_BEAT_RATE = default_rate

    logger.info(f"[ED 训练] 最佳 MIN_BEAT_RATE={best_rate} IS Sharpe={best_sharpe:.3f}")
    return best_rate, best_sharpe


async def _run_ed_oos(test_start: str, test_end: str, beat_rate: float, ed_price, ed_fund) -> dict:
    """测试期运行ED，返回完整结果dict"""
    from app.services.event_driven_service import (
        run_event_driven_backtest,
        EventDrivenConfig,
    )
    import app.services.event_driven_service as _edsvc

    default_rate = EventDrivenConfig.MIN_BEAT_RATE
    EventDrivenConfig.MIN_BEAT_RATE = beat_rate
    _edsvc.EDC.MIN_BEAT_RATE = beat_rate
    try:
        return await run_event_driven_backtest(
            start_date=test_start,
            end_date=test_end,
            _prefetched=ed_price,
            _prefetched_fundamentals=ed_fund,
        )
    finally:
        EventDrivenConfig.MIN_BEAT_RATE = default_rate
        _edsvc.EDC.MIN_BEAT_RATE = default_rate


# ============================================================
# 单窗口执行
# ============================================================

async def run_window(
    window: dict,
    v4_prefetched: dict,
    mr_prefetched,
    ed_price,
    ed_fund,
    run_strategies: list,
    pit_universes: dict = None,
) -> dict:
    """执行单个Walk-Forward窗口，返回该窗口完整结果

    Args:
        pit_universes: {year: set_of_tickers} — Point-in-Time universe 快照。
                       训练期使用 train_start 年份的快照，测试期使用 test_start 年份的快照。
                       None 表示不应用 PIT 过滤（向后兼容）。
    """
    w_name = window["name"]
    train_start, train_end = window["train"]
    test_start, test_end = window["test"]

    logger.info(f"\n{'='*60}")
    logger.info(f"[窗口 {w_name}] 训练期: {train_start} ~ {train_end}")
    logger.info(f"[窗口 {w_name}] 测试期: {test_start} ~ {test_end}")

    # PIT universe 过滤集合：训练用 train_start 年份，测试用 test_start 年份
    train_year = int(train_start[:4])
    test_year  = int(test_start[:4])
    train_pit = pit_universes.get(train_year) if pit_universes else None
    test_pit  = pit_universes.get(test_year)  if pit_universes else None
    if train_pit:
        logger.info(f"[窗口 {w_name}] PIT train filter: {len(train_pit)} tickers ({train_year})")
    if test_pit:
        logger.info(f"[窗口 {w_name}] PIT test  filter: {len(test_pit)} tickers ({test_year})")

    window_result = {
        "window": w_name,
        "train_period": f"{train_start} ~ {train_end}",
        "test_period":  f"{test_start} ~ {test_end}",
        "pit_train_year": train_year,
        "pit_test_year":  test_year,
        "pit_train_count": len(train_pit) if train_pit else None,
        "pit_test_count":  len(test_pit)  if test_pit  else None,
        "strategies": {},
    }

    # ---- V4 ----
    if "v4" in run_strategies:
        logger.info(f"[窗口 {w_name}] 训练V4（搜索 top_n × HB，PIT={train_year}）...")
        try:
            best_tn, best_hb, is_sharpe = await _search_v4_best(
                train_start, train_end, v4_prefetched, universe_filter=train_pit
            )
            logger.info(f"[窗口 {w_name}] V4 OOS测试 top_n={best_tn} HB={best_hb}（PIT={test_year}）...")
            oos_result = await _run_v4_oos(
                test_start, test_end, best_tn, best_hb, v4_prefetched, universe_filter=test_pit
            )
            if "error" in oos_result:
                raise RuntimeError(oos_result["error"])
            oos_sharpe = oos_result.get("sharpe_ratio", 0.0)
            overfitting_ratio = oos_sharpe / is_sharpe if is_sharpe > 0 else 0.0
            window_result["strategies"]["v4"] = {
                "best_param": {"top_n": best_tn, "holding_bonus": best_hb},
                "is_sharpe": round(is_sharpe, 3),
                "oos_sharpe": round(oos_sharpe, 3),
                "oos_cumulative_return": oos_result.get("cumulative_return"),
                "oos_max_drawdown": oos_result.get("max_drawdown"),
                "overfitting_ratio": round(overfitting_ratio, 3),
                "equity_curve": oos_result.get("equity_curve", []),
            }
            logger.info(
                f"[窗口 {w_name}] V4 IS={is_sharpe:.3f} "
                f"OOS={oos_sharpe:.3f} 过拟合比={overfitting_ratio:.2f} "
                f"best_param=top_n={best_tn},HB={best_hb}"
            )
        except Exception as e:
            logger.warning(f"[窗口 {w_name}] V4 失败: {e}")
            window_result["strategies"]["v4"] = {"error": str(e)}

    # ---- MR ----
    if "mr" in run_strategies:
        logger.info(f"[窗口 {w_name}] 训练MR（搜索 RSI阈值）...")
        try:
            best_rsi, is_sharpe = await _search_mr_best(train_start, train_end, mr_prefetched)
            logger.info(f"[窗口 {w_name}] MR OOS测试 RSI={best_rsi}...")
            oos_result = await _run_mr_oos(test_start, test_end, best_rsi, mr_prefetched)
            if "error" in oos_result:
                raise RuntimeError(oos_result["error"])
            oos_sharpe = oos_result.get("sharpe_ratio", 0.0)
            overfitting_ratio = oos_sharpe / is_sharpe if is_sharpe > 0 else 0.0
            window_result["strategies"]["mr"] = {
                "best_param": {"rsi_entry_threshold": best_rsi},
                "is_sharpe": round(is_sharpe, 3),
                "oos_sharpe": round(oos_sharpe, 3),
                "oos_cumulative_return": oos_result.get("cumulative_return"),
                "oos_max_drawdown": oos_result.get("max_drawdown"),
                "overfitting_ratio": round(overfitting_ratio, 3),
                "equity_curve": oos_result.get("equity_curve", []),
            }
            logger.info(
                f"[窗口 {w_name}] MR IS={is_sharpe:.3f} "
                f"OOS={oos_sharpe:.3f} 过拟合比={overfitting_ratio:.2f}"
            )
        except Exception as e:
            logger.warning(f"[窗口 {w_name}] MR 失败: {e}")
            window_result["strategies"]["mr"] = {"error": str(e)}

    # ---- ED ----
    if "ed" in run_strategies:
        logger.info(f"[窗口 {w_name}] 训练ED（搜索 MIN_BEAT_RATE）...")
        try:
            best_rate, is_sharpe = await _search_ed_best(train_start, train_end, ed_price, ed_fund)
            logger.info(f"[窗口 {w_name}] ED OOS测试 beat_rate={best_rate}...")
            oos_result = await _run_ed_oos(test_start, test_end, best_rate, ed_price, ed_fund)
            if "error" in oos_result:
                raise RuntimeError(oos_result["error"])
            oos_sharpe = oos_result.get("sharpe_ratio", 0.0)
            overfitting_ratio = oos_sharpe / is_sharpe if is_sharpe > 0 else 0.0
            window_result["strategies"]["ed"] = {
                "best_param": {"min_beat_rate": best_rate},
                "is_sharpe": round(is_sharpe, 3),
                "oos_sharpe": round(oos_sharpe, 3),
                "oos_cumulative_return": oos_result.get("cumulative_return"),
                "oos_max_drawdown": oos_result.get("max_drawdown"),
                "overfitting_ratio": round(overfitting_ratio, 3),
                "equity_curve": oos_result.get("equity_curve", []),
            }
            logger.info(
                f"[窗口 {w_name}] ED IS={is_sharpe:.3f} "
                f"OOS={oos_sharpe:.3f} 过拟合比={overfitting_ratio:.2f}"
            )
        except Exception as e:
            logger.warning(f"[窗口 {w_name}] ED 失败: {e}")
            window_result["strategies"]["ed"] = {"error": str(e)}

    # ---- Portfolio（等权合并）----
    if "portfolio" in run_strategies:
        strats_with_curves = {
            name: window_result["strategies"].get(name, {}).get("equity_curve", [])
            for name in ["v4", "mr", "ed"]
            if name in run_strategies
        }
        valid_curves = {k: v for k, v in strats_with_curves.items() if v}

        if len(valid_curves) >= 2:
            # 对V4的equity_curve做特殊处理（它是list of dicts）
            flat_curves = {}
            for name, curve in valid_curves.items():
                if curve and isinstance(curve[0], dict):
                    # V4格式：[{"date":..., "portfolio":...}, ...]
                    flat_curves[name] = [entry.get("portfolio", 1.0) for entry in curve]
                else:
                    flat_curves[name] = curve

            active_weights = {k: PORTFOLIO_WEIGHTS[k] for k in flat_curves}
            total_w = sum(active_weights.values())
            norm_weights = {k: v / total_w for k, v in active_weights.items()}

            combined = _combine_equity_curves(flat_curves, norm_weights)
            port_stats = _equity_to_stats(combined)

            window_result["strategies"]["portfolio"] = {
                "weights": norm_weights,
                "oos_sharpe": port_stats["sharpe_ratio"],
                "oos_cumulative_return": port_stats["cumulative_return"],
                "oos_max_drawdown": port_stats["max_drawdown"],
                "oos_annualized_return": port_stats["annualized_return"],
                "equity_curve": combined,
            }
            logger.info(
                f"[窗口 {w_name}] 组合 OOS Sharpe={port_stats['sharpe_ratio']:.3f} "
                f"累计={port_stats['cumulative_return']:+.2%}"
            )
        else:
            logger.warning(f"[窗口 {w_name}] 组合：有效策略不足（仅{len(valid_curves)}个），跳过")
            window_result["strategies"]["portfolio"] = {"error": "有效策略不足，无法合并"}

    return window_result


# ============================================================
# 汇总统计
# ============================================================

def compute_summary(window_results: list, run_strategies: list) -> dict:
    """计算跨窗口汇总统计"""
    summary = {}

    for strat in run_strategies:
        valid_windows = [
            w for w in window_results
            if strat in w.get("strategies", {})
            and "error" not in w["strategies"][strat]
        ]
        if not valid_windows:
            summary[strat] = {"verdict": "SKIP（无有效窗口）"}
            continue

        oos_sharpes = [w["strategies"][strat]["oos_sharpe"] for w in valid_windows]
        is_sharpes  = [w["strategies"][strat].get("is_sharpe", 0.0) for w in valid_windows
                       if "is_sharpe" in w["strategies"][strat]]
        over_ratios = [w["strategies"][strat].get("overfitting_ratio", 0.0)
                       for w in valid_windows if "overfitting_ratio" in w["strategies"][strat]]

        avg_oos_sharpe = float(np.mean(oos_sharpes))
        avg_is_sharpe  = float(np.mean(is_sharpes)) if is_sharpes else 0.0
        avg_over_ratio = float(np.mean(over_ratios)) if over_ratios else 0.0

        # 参数稳定性
        if strat == "v4":
            param_values = [
                w["strategies"][strat]["best_param"].get("top_n")
                for w in valid_windows if "best_param" in w["strategies"][strat]
            ]
        elif strat == "mr":
            param_values = [
                w["strategies"][strat]["best_param"].get("rsi_entry_threshold")
                for w in valid_windows if "best_param" in w["strategies"][strat]
            ]
        elif strat == "ed":
            param_values = [
                w["strategies"][strat]["best_param"].get("min_beat_rate")
                for w in valid_windows if "best_param" in w["strategies"][strat]
            ]
        else:
            param_values = []

        param_stability = (
            "稳定 ✅" if param_values and len(set(param_values)) <= 2
            else f"不稳定 ⚠️ 变化={set(param_values)}"
        ) if param_values else "N/A"

        # PASS/FAIL
        if avg_oos_sharpe > 0.4 and avg_over_ratio > 0.5:
            verdict = "PASS ✅"
        elif avg_oos_sharpe > 0.2:
            verdict = "MARGINAL ⚠️"
        else:
            verdict = "FAIL ❌"

        summary[strat] = {
            "avg_oos_sharpe": round(avg_oos_sharpe, 3),
            "avg_is_sharpe":  round(avg_is_sharpe, 3),
            "avg_overfitting_ratio": round(avg_over_ratio, 3),
            "param_values_across_windows": param_values,
            "param_stability": param_stability,
            "oos_sharpes_per_window": [round(s, 3) for s in oos_sharpes],
            "verdict": verdict,
        }

    return summary


def print_summary_table(summary: dict):
    """打印汇总结果表格"""
    print("\n" + "=" * 80)
    print("  Walk-Forward 汇总结果")
    print("=" * 80)

    for strat, s in summary.items():
        strat_name = {"v4": "V4 轮动", "mr": "MR 均值回归", "ed": "ED 事件驱动",
                      "portfolio": "组合"}.get(strat, strat)
        print(f"\n  策略: {strat_name}")
        print(f"  {'─'*50}")
        if "verdict" in s and len(s) == 1:
            print(f"    {s['verdict']}")
            continue
        print(f"    平均 OOS Sharpe:     {s.get('avg_oos_sharpe', 'N/A')}")
        print(f"    平均 IS Sharpe:      {s.get('avg_is_sharpe', 'N/A')}")
        print(f"    平均过拟合比率:      {s.get('avg_overfitting_ratio', 'N/A')} (目标>0.5)")
        print(f"    参数稳定性:         {s.get('param_stability', 'N/A')}")
        print(f"    各窗口OOS Sharpe:   {s.get('oos_sharpes_per_window', [])}")
        print(f"    判定:              {s.get('verdict', 'N/A')}")

    print("\n" + "=" * 80)


# ============================================================
# 主函数
# ============================================================

async def main():
    parser = argparse.ArgumentParser(description="StockQueen Walk-Forward 全策略验证（V5完整版）")
    parser.add_argument(
        "--strategy",
        choices=["mr", "ed", "v4", "portfolio", "all", "v4mr"],
        default="all",
        help="测试策略（默认all）。v4mr=仅V4+MR双策略组合（不含ED）",
    )
    parser.add_argument(
        "--no-pit",
        action="store_true",
        default=False,
        help="禁用 Point-in-Time universe 过滤（向后兼容模式，结果含幸存者偏差）",
    )
    args = parser.parse_args()

    # 解析策略列表
    if args.strategy == "all":
        run_strategies = ["v4", "mr", "ed", "portfolio"]
    elif args.strategy == "portfolio":
        run_strategies = ["v4", "mr", "ed", "portfolio"]  # 组合依赖其他三个
    elif args.strategy == "v4mr":
        run_strategies = ["v4", "mr", "portfolio"]  # 双策略组合（不含ED），权重自动归一化 V4:MR≈2:1
    else:
        run_strategies = [args.strategy]

    use_pit = not args.no_pit

    print("=" * 80)
    print("  StockQueen Walk-Forward 全策略验证（V5完整版）")
    print(f"  策略: {', '.join(run_strategies)}")
    print(f"  窗口数: {len(WINDOWS)}")
    print(f"  PIT 幸存者偏差修复: {'✅ 启用' if use_pit else '⚠️  禁用（--no-pit）'}")
    print("=" * 80)
    logger.info(f"Walk-Forward V5 Full 启动: 策略={run_strategies}, PIT={use_pit}")

    t_total = time.time()

    # ---- Point-in-Time Universe 快照（Phase 1.5 幸存者偏差修复）----
    pit_universes = None
    if use_pit and any(s in run_strategies for s in ["v4", "portfolio"]):
        logger.info("[PIT] 构建 Point-in-Time universe 快照...")
        from app.services.universe_service import UniverseService
        _usvc = UniverseService()

        # 训练期统一从 2018 开始；测试期为 2020~2025
        pit_years = set()
        for w in WINDOWS:
            pit_years.add(int(w["train"][0][:4]))  # 2018
            pit_years.add(int(w["test"][0][:4]))   # 2020~2025

        pit_universes = {}
        for year in sorted(pit_years):
            try:
                pit_universes[year] = await _usvc.get_pit_universe(year)
                logger.info(f"[PIT] {year}: {len(pit_universes[year])} tickers")
            except Exception as e:
                logger.error(f"[PIT] {year}: 获取失败 — {e}，该年份将不过滤")
                pit_universes[year] = None

        total_fetched = sum(len(v) for v in pit_universes.values() if v)
        logger.info(f"[PIT] 完成。{len(pit_universes)} 个快照，合计 {total_fetched} ticker-年次")
    else:
        if not use_pit:
            logger.warning("[PIT] 已禁用（--no-pit），回测结果含幸存者偏差")

    # ---- 数据预取（全覆盖 2018~2024）----
    logger.info("[数据预取] 开始获取全部数据（2018-01-01 ~ 2025-12-31）...")

    v4_prefetched = {}
    mr_prefetched = {}
    ed_price = {}
    ed_fund = {}

    if any(s in run_strategies for s in ["v4", "portfolio"]):
        try:
            from app.services.rotation_service import _fetch_backtest_data
            v4_prefetched = await _fetch_backtest_data("2018-01-01", "2025-12-31")
            logger.info(f"[数据预取] V4数据: {len(v4_prefetched.get('histories', {}))}只")
        except Exception as e:
            logger.error(f"[数据预取] V4数据失败: {e}")

    if any(s in run_strategies for s in ["mr", "portfolio"]):
        # MR复用V4的histories
        mr_prefetched = v4_prefetched.get("histories", {}) if v4_prefetched else {}
        if not mr_prefetched:
            try:
                from app.services.mean_reversion_service import _fetch_mr_data
                mr_prefetched = await _fetch_mr_data("2018-01-01", "2025-12-31")
                logger.info(f"[数据预取] MR数据: {len(mr_prefetched)}只")
            except Exception as e:
                logger.error(f"[数据预取] MR数据失败: {e}")
        else:
            logger.info(f"[数据预取] MR数据复用V4: {len(mr_prefetched)}只")

    if any(s in run_strategies for s in ["ed", "portfolio"]):
        try:
            from app.services.event_driven_service import _fetch_ed_data
            ed_price, ed_fund = await _fetch_ed_data("2018-01-01", "2025-12-31")
            logger.info(f"[数据预取] ED数据: 价格{len(ed_price)}只, 财报{len(ed_fund)}只")
        except Exception as e:
            logger.error(f"[数据预取] ED数据失败: {e}")

    # ---- 逐窗口运行 ----
    window_results = []
    for window in WINDOWS:
        t_win = time.time()
        w_result = await run_window(
            window=window,
            v4_prefetched=v4_prefetched,
            mr_prefetched=mr_prefetched,
            ed_price=ed_price,
            ed_fund=ed_fund,
            run_strategies=run_strategies,
            pit_universes=pit_universes,
        )
        window_results.append(w_result)
        elapsed_win = time.time() - t_win
        logger.info(f"[窗口 {window['name']}] 完成，耗时 {elapsed_win:.0f}s")

        # 打印单窗口快速摘要
        print(f"\n  [{window['name']}] {window['test'][0]} ~ {window['test'][1]} 测试结果:")
        for strat in run_strategies:
            sdata = w_result.get("strategies", {}).get(strat, {})
            if "error" in sdata:
                print(f"    {strat:12s}: ERR - {sdata['error'][:60]}")
            elif "oos_sharpe" in sdata:
                print(
                    f"    {strat:12s}: OOS Sharpe={sdata['oos_sharpe']:.3f} "
                    f"累计={sdata.get('oos_cumulative_return', 0):+.2%} "
                    f"最大回撤={sdata.get('oos_max_drawdown', 0):.2%}"
                )

    # ---- 汇总 ----
    summary = compute_summary(window_results, run_strategies)
    print_summary_table(summary)

    # ---- 保存结果 ----
    out_data = {
        "meta": {
            "test": "Walk-Forward V5 Full（全策略）",
            "timestamp": TIMESTAMP,
            "run_strategies": run_strategies,
            "windows": [
                {"name": w["name"], "train": w["train"], "test": w["test"]}
                for w in WINDOWS
            ],
            "v4_top_n_range": V4_TOP_N_RANGE,
            "mr_rsi_range": MR_RSI_RANGE,
            "ed_beat_rate_range": ED_BEAT_RATE_RANGE,
            "portfolio_weights": PORTFOLIO_WEIGHTS,
        },
        "window_results": [
            {
                k: v for k, v in wr.items()
                if k != "strategies" or True  # 保留，但去掉equity_curve节省空间
            }
            for wr in window_results
        ],
        "summary": summary,
    }

    # 清理equity_curve以减小文件体积
    for wr in out_data["window_results"]:
        for strat_data in wr.get("strategies", {}).values():
            strat_data.pop("equity_curve", None)

    out_file = RESULTS_DIR / f"walk_forward_v5_full_{TIMESTAMP}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2, ensure_ascii=False, default=str)

    elapsed = time.time() - t_total
    print(f"\n{'='*80}")
    print(f"  Walk-Forward V5 Full 完成，耗时 {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  结果已保存: {out_file}")
    print(f"  日志文件:   {log_file}")
    print("=" * 80)
    logger.info(f"Walk-Forward完成，结果保存至 {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
