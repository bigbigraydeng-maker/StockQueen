"""
StockQueen - 纯 Alpha 参数重优化（Walk-Forward）
=================================================
核心问题：去掉 Regime 门控后，top_n 和 HB 的最优参数是否改变？

方法：
  与 walk_forward_v5_full.py 完全相同的 WF 框架（5个扩展窗口）
  唯一区别：disable_regime_filter=True（纯 Alpha 模式）
  训练期搜索最优 top_n × HB → 测试期 OOS 验证
  同时输出 V4（有门控，top_n=3 HB=0.0 锁定参数）作为对照基准

搜索范围（比 V4 WF 更细粒度）：
  top_n = [2, 3, 4, 5, 6]
  HB    = [0.0, 0.25, 0.5, 0.75, 1.0]  (25 组)

关键输出：
  1. 每窗口：IS最优参数、OOS Sharpe、过拟合比（OOS/IS）
  2. 参数稳定性：各窗口最优 top_n 是否一致
  3. 与 V4 锁定参数（3/0.0）的对比
  4. 最终推荐：纯 Alpha 模式应锁定哪个参数

运行方法：
    cd StockQueen
    python scripts/pure_alpha_param_search.py
    python scripts/pure_alpha_param_search.py --cache-only
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
log_file = RESULTS_DIR / f"pure_alpha_param_search_{TIMESTAMP}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logging.getLogger("app.services.alphavantage_client").setLevel(logging.WARNING)
logging.getLogger("app.services.rotation_service").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ============================================================
# 配置
# ============================================================

WF_WINDOWS = [
    {"name": "W1", "train": ("2018-01-01", "2019-12-31"), "test": ("2020-01-01", "2020-12-31")},
    {"name": "W2", "train": ("2018-01-01", "2020-12-31"), "test": ("2021-01-01", "2021-12-31")},
    {"name": "W3", "train": ("2018-01-01", "2021-12-31"), "test": ("2022-01-01", "2022-12-31")},
    {"name": "W4", "train": ("2018-01-01", "2022-12-31"), "test": ("2023-01-01", "2023-12-31")},
    {"name": "W5", "train": ("2018-01-01", "2023-12-31"), "test": ("2024-01-01", "2024-12-31")},
]

# 参数搜索范围（纯 Alpha 模式专用，比 V4 更细）
ALPHA_TOP_N_RANGE = [2, 3, 4, 5, 6]
ALPHA_HB_RANGE    = [0.0, 0.25, 0.5, 0.75, 1.0]

# V4 对照基准（已锁定参数）
V4_BASELINE_TOP_N = 3
V4_BASELINE_HB    = 0.0


# ============================================================
# 辅助：参数搜索
# ============================================================

async def _search_best_params(
    train_start: str,
    train_end: str,
    prefetched: dict,
    window_name: str,
) -> tuple:
    """
    在训练期内网格搜索纯 Alpha 最优 top_n × HB。
    返回 (best_top_n, best_hb, best_is_sharpe, all_results)
    """
    from app.services.rotation_service import run_rotation_backtest

    best_top_n  = ALPHA_TOP_N_RANGE[0]
    best_hb     = ALPHA_HB_RANGE[0]
    best_sharpe = -999.0
    all_results = []

    total = len(ALPHA_TOP_N_RANGE) * len(ALPHA_HB_RANGE)
    done  = 0

    for tn in ALPHA_TOP_N_RANGE:
        for hb in ALPHA_HB_RANGE:
            done += 1
            try:
                r = await run_rotation_backtest(
                    start_date=train_start,
                    end_date=train_end,
                    top_n=tn,
                    holding_bonus=hb,
                    _prefetched=prefetched,
                    disable_regime_filter=True,
                )
                s = r.get("sharpe_ratio", -999.0) if "error" not in r else -999.0
                all_results.append({"top_n": tn, "hb": hb, "is_sharpe": round(s, 3)})
                logger.debug(f"  [{window_name}] IS top_n={tn} HB={hb} Sharpe={s:.3f}  [{done}/{total}]")
                if s > best_sharpe:
                    best_sharpe = s
                    best_top_n  = tn
                    best_hb     = hb
            except Exception as e:
                logger.warning(f"  [{window_name}] IS top_n={tn} HB={hb} 异常: {e}")
                all_results.append({"top_n": tn, "hb": hb, "is_sharpe": None, "error": str(e)})

    logger.info(
        f"[{window_name}] 训练期最优 top_n={best_top_n} HB={best_hb} "
        f"IS Sharpe={best_sharpe:.3f}"
    )
    return best_top_n, best_hb, best_sharpe, all_results


async def _run_oos(
    test_start: str,
    test_end: str,
    top_n: int,
    hb: float,
    prefetched: dict,
    disable_regime: bool = True,
) -> dict:
    from app.services.rotation_service import run_rotation_backtest
    return await run_rotation_backtest(
        start_date=test_start,
        end_date=test_end,
        top_n=top_n,
        holding_bonus=hb,
        _prefetched=prefetched,
        disable_regime_filter=disable_regime,
    )


# ============================================================
# 单窗口执行
# ============================================================

async def run_window(window: dict, prefetched: dict) -> dict:
    w_name      = window["name"]
    train_start, train_end = window["train"]
    test_start,  test_end  = window["test"]

    logger.info(f"\n{'='*60}")
    logger.info(f"[{w_name}] 训练期: {train_start} ~ {train_end}")
    logger.info(f"[{w_name}] 测试期: {test_start} ~ {test_end}")

    # ── 纯 Alpha：搜索最优参数 ──
    t0 = time.time()
    best_tn, best_hb, is_sharpe, grid = await _search_best_params(
        train_start, train_end, prefetched, w_name
    )
    logger.info(f"[{w_name}] 参数搜索耗时 {time.time()-t0:.0f}s")

    # ── 纯 Alpha：OOS 测试（最优参数）──
    oos_best = await _run_oos(test_start, test_end, best_tn, best_hb, prefetched, disable_regime=True)

    # ── 纯 Alpha：OOS 测试（固定 top_n=3 HB=0.0，方便与 V4 对比）──
    oos_fixed = await _run_oos(test_start, test_end, 3, 0.0, prefetched, disable_regime=True)

    # ── V4 基准：OOS 测试（有门控，top_n=3 HB=0.0）──
    oos_v4 = await _run_oos(test_start, test_end, V4_BASELINE_TOP_N, V4_BASELINE_HB,
                            prefetched, disable_regime=False)

    def _extract(r):
        if not r or "error" in r:
            return {"sharpe_ratio": None, "cumulative_return": None,
                    "max_drawdown": None, "win_rate": None}
        return {
            "sharpe_ratio":      r.get("sharpe_ratio"),
            "cumulative_return": r.get("cumulative_return"),
            "max_drawdown":      r.get("max_drawdown"),
            "win_rate":          r.get("win_rate"),
        }

    oos_best_s  = oos_best.get("sharpe_ratio")  if "error" not in oos_best  else None
    overfitting = round(oos_best_s / is_sharpe, 3) if (oos_best_s and is_sharpe > 0) else None

    result = {
        "window":       w_name,
        "train_period": f"{train_start} ~ {train_end}",
        "test_period":  f"{test_start} ~ {test_end}",
        "best_param":   {"top_n": best_tn, "hb": best_hb},
        "is_sharpe":    round(is_sharpe, 3),
        "overfitting_ratio": overfitting,
        "alpha_best":   _extract(oos_best),
        "alpha_fixed":  _extract(oos_fixed),   # top_n=3 HB=0 (apples-to-apples with V4)
        "v4_baseline":  _extract(oos_v4),
        "is_grid":      grid,
    }

    logger.info(
        f"[{w_name}] OOS 结果:\n"
        f"  Alpha(最优 top_n={best_tn},HB={best_hb}): "
        f"Sharpe={oos_best_s:.3f}  "
        f"过拟合比={overfitting:.2f}\n"
        f"  Alpha(固定 top_n=3,HB=0.0):  "
        f"Sharpe={oos_fixed.get('sharpe_ratio', 'ERR'):.3f}\n"
        f"  V4  (门控 top_n=3,HB=0.0):  "
        f"Sharpe={oos_v4.get('sharpe_ratio', 'ERR'):.3f}"
        if oos_best_s else f"[{w_name}] OOS 计算失败"
    )
    return result


# ============================================================
# 汇总打印
# ============================================================

def print_summary(results: list):
    logger.info("")
    logger.info("=" * 80)
    logger.info("   纯 Alpha 参数重优化 — Walk-Forward 结果汇总")
    logger.info("=" * 80)
    logger.info(
        f"{'窗口':<6} {'最优top_n':>9} {'最优HB':>8} "
        f"{'IS Sharpe':>10} {'OOS(最优)':>10} {'OOS(固定3/0)':>12} "
        f"{'V4基准':>8} {'过拟合比':>9}"
    )
    logger.info("-" * 80)

    alpha_best_sharpes  = []
    alpha_fixed_sharpes = []
    v4_sharpes          = []
    top_n_votes         = []

    for r in results:
        tn   = r["best_param"]["top_n"]
        hb   = r["best_param"]["hb"]
        is_s = r["is_sharpe"]
        ab   = r["alpha_best"].get("sharpe_ratio")
        af   = r["alpha_fixed"].get("sharpe_ratio")
        v4   = r["v4_baseline"].get("sharpe_ratio")
        of   = r["overfitting_ratio"]

        def f(v): return f"{v:.3f}" if v is not None else "  ERR"

        logger.info(
            f"{r['window']:<6} {tn:>9} {hb:>8.2f} "
            f"{f(is_s):>10} {f(ab):>10} {f(af):>12} "
            f"{f(v4):>8} {f(of):>9}"
        )

        if ab  is not None: alpha_best_sharpes.append(ab)
        if af  is not None: alpha_fixed_sharpes.append(af)
        if v4  is not None: v4_sharpes.append(v4)
        top_n_votes.append(tn)

    logger.info("-" * 80)
    avg_ab = np.mean(alpha_best_sharpes)  if alpha_best_sharpes  else None
    avg_af = np.mean(alpha_fixed_sharpes) if alpha_fixed_sharpes else None
    avg_v4 = np.mean(v4_sharpes)          if v4_sharpes          else None

    def f(v): return f"{v:.3f}" if v is not None else "  ERR"
    logger.info(
        f"{'均值':<6} {'-':>9} {'-':>8} "
        f"{'':>10} {f(avg_ab):>10} {f(avg_af):>12} {f(avg_v4):>8}"
    )
    logger.info("=" * 80)

    # ── 参数稳定性分析 ──
    from collections import Counter
    top_n_dist = Counter(top_n_votes)
    logger.info("")
    logger.info("── 参数稳定性 ──")
    logger.info(f"  top_n 分布: {dict(top_n_dist)}")
    most_common_tn = top_n_dist.most_common(1)[0][0]
    logger.info(f"  最频出现的 top_n = {most_common_tn}（{top_n_dist[most_common_tn]}/5 窗口）")

    # ── 结论 ──
    logger.info("")
    logger.info("── 结论 ──")

    if avg_ab and avg_v4:
        alpha_gain = avg_ab - avg_v4
        logger.info(f"  纯Alpha(最优参数) vs V4基准: {alpha_gain:+.3f} Sharpe")
        logger.info(f"  纯Alpha(固定3/0)  vs V4基准: {avg_af - avg_v4:+.3f} Sharpe" if avg_af else "")

    # 判断是否需要重新锁定参数
    if most_common_tn == 3:
        logger.info("  → top_n=3 在纯Alpha模式下仍然稳定，维持原锁定参数")
    else:
        logger.info(f"  → 纯Alpha模式建议将 top_n 改为 {most_common_tn}（5窗口中出现 {top_n_dist[most_common_tn]} 次）")

    # 过拟合检查
    of_ratios = [r["overfitting_ratio"] for r in results if r["overfitting_ratio"]]
    if of_ratios:
        avg_of = np.mean(of_ratios)
        logger.info(f"  平均过拟合比 = {avg_of:.2f}（>0.5 为健康，>1.0 为 OOS 超越 IS）")
        if avg_of >= 0.5:
            logger.info("  → 过拟合比健康，参数可推广到样本外")
        else:
            logger.info("  → ⚠️  过拟合比偏低，参数在样本外泛化能力存疑")


# ============================================================
# 主流程
# ============================================================

async def main(cache_only: bool = False):
    logger.info("=" * 70)
    logger.info("  StockQueen — 纯 Alpha 参数重优化 Walk-Forward")
    logger.info(f"  top_n 搜索范围: {ALPHA_TOP_N_RANGE}")
    logger.info(f"  HB 搜索范围:    {ALPHA_HB_RANGE}")
    logger.info(f"  参数组合数:     {len(ALPHA_TOP_N_RANGE) * len(ALPHA_HB_RANGE)} × 10 WF窗口（训+测）= "
                f"{len(ALPHA_TOP_N_RANGE) * len(ALPHA_HB_RANGE) * 10} 次回测")
    logger.info("=" * 70)

    # 数据预取
    from app.services.rotation_service import _fetch_backtest_data
    full_start = WF_WINDOWS[0]["train"][0]
    full_end   = WF_WINDOWS[-1]["test"][1]

    if not cache_only:
        logger.info("正在预取历史数据...")
        t0 = time.time()
        prefetched = await _fetch_backtest_data(full_start, full_end)
        if "error" in prefetched:
            logger.error(f"数据预取失败: {prefetched['error']}")
            return
        logger.info(f"数据预取完成: {len(prefetched.get('histories', {}))} 只股票 ({time.time()-t0:.0f}s)")
    else:
        logger.info("--cache-only 模式")
        prefetched = {}

    # 逐窗口
    window_results = []
    for window in WF_WINDOWS:
        wr = await run_window(window, prefetched)
        window_results.append(wr)

    # 汇总
    print_summary(window_results)

    # 保存
    output = {
        "meta": {
            "test":       "Pure Alpha Parameter Re-Optimization Walk-Forward",
            "timestamp":  TIMESTAMP,
            "top_n_range": ALPHA_TOP_N_RANGE,
            "hb_range":    ALPHA_HB_RANGE,
            "windows":    [w["name"] for w in WF_WINDOWS],
        },
        "window_results": window_results,
    }
    out_file = RESULTS_DIR / f"pure_alpha_param_search_{TIMESTAMP}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info(f"\n结果已保存: {out_file}")
    logger.info(f"日志已保存: {log_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="纯 Alpha 参数重优化 Walk-Forward")
    parser.add_argument("--cache-only", action="store_true", help="跳过数据预取，使用已有缓存")
    args = parser.parse_args()
    asyncio.run(main(cache_only=args.cache_only))
