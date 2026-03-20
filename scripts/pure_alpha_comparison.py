"""
StockQueen - 纯 Alpha 策略 vs 宝典 V4（Regime 门控）对比测试
================================================================
核心问题：Regime 门控是否真的带来了额外价值？
         还是评分系统本身已经能自我保护？

方法：
  两种策略使用完全相同的参数（top_n=3, HB=0.0）、相同数据、相同 WF 框架
  唯一区别：
    - 宝典 V4：regime 门控开启（bear 只买防御/做空 ETF，bull 只买进攻股）
    - 纯 Alpha： regime 门控关闭，永远从全池取评分最高的 Top-3

WF 窗口（5个扩展窗口）：
  W1: Train 2018-2019  Test 2020  (COVID 崩溃 + 反弹)
  W2: Train 2018-2020  Test 2021  (牛市)
  W3: Train 2018-2021  Test 2022  (熊市 -20%)
  W4: Train 2018-2022  Test 2023  (反弹年)
  W5: Train 2018-2023  Test 2024  (AI 牛市)

运行方法：
    cd StockQueen
    python scripts/pure_alpha_comparison.py
    python scripts/pure_alpha_comparison.py --cache-only   # 跳过数据预取（用已有缓存）
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
log_file = RESULTS_DIR / f"pure_alpha_comparison_{TIMESTAMP}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# WF 配置（与 walk_forward_v5_full.py 一致）
# ============================================================

WF_WINDOWS = [
    {"name": "W1", "train": ("2018-01-01", "2019-12-31"), "test": ("2020-01-01", "2020-12-31")},
    {"name": "W2", "train": ("2018-01-01", "2020-12-31"), "test": ("2021-01-01", "2021-12-31")},
    {"name": "W3", "train": ("2018-01-01", "2021-12-31"), "test": ("2022-01-01", "2022-12-31")},
    {"name": "W4", "train": ("2018-01-01", "2022-12-31"), "test": ("2023-01-01", "2023-12-31")},
    {"name": "W5", "train": ("2018-01-01", "2023-12-31"), "test": ("2024-01-01", "2024-12-31")},
]

# 锁定参数（与宝典 V4 WF 验证结论一致）
FIXED_TOP_N = 3
FIXED_HB    = 0.0


# ============================================================
# 指标计算（与 walk_forward_v5_full.py 一致）
# ============================================================

def compute_metrics(weekly_returns: list) -> dict:
    if not weekly_returns or len(weekly_returns) < 2:
        return {"sharpe_ratio": 0.0, "cumulative_return": 0.0,
                "max_drawdown": 0.0, "win_rate": 0.0, "num_weeks": 0}
    r = np.array(weekly_returns, dtype=float)
    ann_ret = float(r.mean() * 52)
    vol     = float(r.std(ddof=1) * np.sqrt(52)) if r.std() > 0 else 1e-9
    sharpe  = ann_ret / vol if vol > 0 else 0.0

    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    for rr in r:
        cum *= (1 + rr)
        if cum > peak:
            peak = cum
        dd = (cum - peak) / peak
        if dd < max_dd:
            max_dd = dd

    return {
        "sharpe_ratio":      round(sharpe, 3),
        "cumulative_return": round(cum - 1, 4),
        "max_drawdown":      round(max_dd, 4),
        "win_rate":          round(float((r > 0).mean()), 3),
        "num_weeks":         len(r),
    }


# ============================================================
# 单窗口运行
# ============================================================

async def run_window(window: dict, prefetched: dict) -> dict:
    """
    对一个 WF 窗口运行两种策略：
    - v4:    regime 门控开启
    - alpha: regime 门控关闭（纯评分 Top-N）
    返回 {v4: metrics, alpha: metrics}
    """
    from app.services.rotation_service import run_rotation_backtest

    wname      = window["name"]
    test_start = window["test"][0]
    test_end   = window["test"][1]

    results = {}
    for label, disable_regime in [("v4", False), ("alpha", True)]:
        t0 = time.time()
        try:
            r = await run_rotation_backtest(
                start_date=test_start,
                end_date=test_end,
                top_n=FIXED_TOP_N,
                holding_bonus=FIXED_HB,
                _prefetched=prefetched,
                disable_regime_filter=disable_regime,
            )
            if "error" in r:
                logger.warning(f"[{wname}][{label}] 错误: {r['error']}")
                results[label] = {"sharpe_ratio": None, "error": r["error"]}
            else:
                metrics = {
                    "sharpe_ratio":      r.get("sharpe_ratio"),
                    "cumulative_return": r.get("cumulative_return"),
                    "max_drawdown":      r.get("max_drawdown"),
                    "win_rate":          r.get("win_rate"),
                    "num_weeks":         r.get("num_weeks"),
                }
                results[label] = metrics
                elapsed = time.time() - t0
                logger.info(
                    f"[{wname}][{label}] "
                    f"Sharpe={metrics['sharpe_ratio']:.3f}  "
                    f"Return={metrics['cumulative_return']:+.1%}  "
                    f"MaxDD={metrics['max_drawdown']:.1%}  "
                    f"({elapsed:.0f}s)"
                )
        except Exception as e:
            logger.error(f"[{wname}][{label}] 异常: {e}", exc_info=True)
            results[label] = {"sharpe_ratio": None, "error": str(e)}

    return results


# ============================================================
# 汇总打印
# ============================================================

def print_summary(window_results: list):
    logger.info("")
    logger.info("=" * 70)
    logger.info("   宝典 V4（Regime 门控）vs 纯 Alpha（评分 Top-3，无门控）对比")
    logger.info("=" * 70)
    logger.info(f"{'窗口':<6} {'测试期':<12} {'V4 Sharpe':>10} {'Alpha Sharpe':>13} {'差值':>8} {'V4 MDD':>8} {'Alpha MDD':>10}")
    logger.info("-" * 70)

    v4_sharpes    = []
    alpha_sharpes = []

    for w, wr in zip(WF_WINDOWS, window_results):
        v4    = wr.get("v4", {})
        alpha = wr.get("alpha", {})
        s_v4    = v4.get("sharpe_ratio")
        s_alpha = alpha.get("sharpe_ratio")
        mdd_v4    = v4.get("max_drawdown")
        mdd_alpha = alpha.get("max_drawdown")

        def fmt(v): return f"{v:.3f}" if v is not None else "  ERR"
        def fmtpct(v): return f"{v:.1%}" if v is not None else "  ERR"

        diff = (s_alpha - s_v4) if (s_v4 is not None and s_alpha is not None) else None
        diff_str = f"{diff:+.3f}" if diff is not None else "  N/A"
        winner = " ← Alpha" if (diff and diff > 0.1) else (" ← V4  " if (diff and diff < -0.1) else "  ~同等")

        logger.info(
            f"{w['name']:<6} {w['test'][0][:4]:<12} "
            f"{fmt(s_v4):>10} {fmt(s_alpha):>13} "
            f"{diff_str:>8}{winner}  "
            f"{fmtpct(mdd_v4):>8} {fmtpct(mdd_alpha):>10}"
        )

        if s_v4    is not None: v4_sharpes.append(s_v4)
        if s_alpha is not None: alpha_sharpes.append(s_alpha)

    logger.info("-" * 70)
    avg_v4    = np.mean(v4_sharpes)    if v4_sharpes    else None
    avg_alpha = np.mean(alpha_sharpes) if alpha_sharpes else None

    def fmt(v): return f"{v:.3f}" if v is not None else "  ERR"
    logger.info(
        f"{'均值':<6} {'':<12} {fmt(avg_v4):>10} {fmt(avg_alpha):>13} "
        f"{f'{avg_alpha-avg_v4:+.3f}' if (avg_v4 and avg_alpha) else '':>8}"
    )
    logger.info("=" * 70)

    # 结论
    logger.info("")
    if avg_v4 is not None and avg_alpha is not None:
        if avg_v4 > avg_alpha + 0.2:
            logger.info("结论：Regime 门控显著优于纯 Alpha（+0.2+ Sharpe）")
            logger.info("      → 门控有真实价值，当前宝典策略设计合理")
        elif avg_alpha > avg_v4 + 0.2:
            logger.info("结论：纯 Alpha 显著优于 Regime 门控（+0.2+ Sharpe）")
            logger.info("      → 评分系统本身已能自我保护，门控可能是多余约束")
        else:
            logger.info("结论：两种策略表现相近（差值 < 0.2）")
            logger.info("      → 深入看 W3（2022熊市）窗口差异，决定是否保留门控")

    # 检查 W3（2022 熊市）——最关键的窗口
    if len(window_results) >= 3:
        w3 = window_results[2]
        s_v4_w3    = w3.get("v4",    {}).get("sharpe_ratio")
        s_alpha_w3 = w3.get("alpha", {}).get("sharpe_ratio")
        if s_v4_w3 is not None and s_alpha_w3 is not None:
            logger.info("")
            logger.info(f"关键窗口 W3（2022 熊市）：V4={s_v4_w3:.3f}  Alpha={s_alpha_w3:.3f}")
            if s_v4_w3 > s_alpha_w3 + 0.3:
                logger.info("  → 熊市中 Regime 门控保护力显著，建议保留")
            elif s_alpha_w3 > s_v4_w3 - 0.1:
                logger.info("  → 纯 Alpha 在熊市自保能力不弱，评分系统可能已内置防守")
            else:
                logger.info("  → 两者熊市差异中等，建议结合回撤数据综合判断")


# ============================================================
# 主流程
# ============================================================

async def main(cache_only: bool = False):
    logger.info("=" * 70)
    logger.info("  StockQueen — 纯 Alpha vs 宝典 V4 对比测试")
    logger.info(f"  top_n={FIXED_TOP_N}  HB={FIXED_HB}  WF 窗口数={len(WF_WINDOWS)}")
    logger.info("=" * 70)

    # 数据预取（只需一次，两种策略共用）
    logger.info("正在预取历史数据（所有 WF 窗口共用同一份）...")
    from app.services.rotation_service import _fetch_backtest_data
    t0 = time.time()
    full_start = WF_WINDOWS[0]["train"][0]
    full_end   = WF_WINDOWS[-1]["test"][1]

    if not cache_only:
        prefetched = await _fetch_backtest_data(full_start, full_end)
        if "error" in prefetched:
            logger.error(f"数据预取失败: {prefetched['error']}")
            return
        logger.info(f"数据预取完成：{len(prefetched.get('histories', {}))} 只股票  ({time.time()-t0:.0f}s)")
    else:
        logger.info("--cache-only 模式：跳过预取，使用现有缓存")
        prefetched = {}

    # 逐窗口运行
    window_results = []
    for window in WF_WINDOWS:
        logger.info(f"\n{'='*50}")
        logger.info(f"  窗口 {window['name']}  测试期: {window['test'][0]} ~ {window['test'][1]}")
        logger.info(f"{'='*50}")
        wr = await run_window(window, prefetched)
        window_results.append(wr)

    # 打印汇总
    print_summary(window_results)

    # 保存结果
    output = {
        "meta": {
            "test": "Pure Alpha vs V4 Regime-Gated Comparison",
            "timestamp": TIMESTAMP,
            "top_n": FIXED_TOP_N,
            "holding_bonus": FIXED_HB,
            "windows": [w["name"] for w in WF_WINDOWS],
        },
        "window_results": [
            {
                "window":      w["name"],
                "test_period": f"{w['test'][0]} ~ {w['test'][1]}",
                **wr,
            }
            for w, wr in zip(WF_WINDOWS, window_results)
        ],
    }
    out_file = RESULTS_DIR / f"pure_alpha_comparison_{TIMESTAMP}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info(f"\n结果已保存: {out_file}")
    logger.info(f"日志已保存: {log_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="纯 Alpha vs 宝典 V4 对比测试")
    parser.add_argument("--cache-only", action="store_true",
                        help="跳过数据预取，使用已有本地缓存")
    args = parser.parse_args()
    asyncio.run(main(cache_only=args.cache_only))
