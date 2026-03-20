"""
StockQueen - 纯 Alpha 策略压力测试
====================================
在决定去掉 Regime 门控之前，验证纯 Alpha 的统计显著性和尾部风险。

测试 1: 蒙特卡洛置换检验（Permutation Test）
  - 对实际收益序列做随机打乱（500次），检验 Sharpe 是否显著高于随机
  - 同时对 V4（有门控）做相同测试，用于对比基础统计显著性

测试 2: Bootstrap 置信区间
  - 对实际周度收益做有放回重采样（1000次），得到 Sharpe/MDD/回报 分布
  - 核心问题：纯 Alpha 的 MDD 尾部是否可接受（P95 MDD < 40%？）
  - 与 V4 分布对比

测试 3: 分 Regime 子期间拆分（Regime Drill-Down）
  - W3（2022熊市）内细分月度收益分布
  - W4（2023风格切换）内细分月度收益分布
  - 找出纯 Alpha 最脆弱的市场微结构

测试 4: 连续亏损周分析
  - 最长连续亏损周数（V4 vs Alpha）
  - 最大回撤持续时间（水下时间）

运行方法：
    cd StockQueen
    python scripts/pure_alpha_stress_test.py
    python scripts/pure_alpha_stress_test.py --cache-only
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
log_file = RESULTS_DIR / f"pure_alpha_stress_{TIMESTAMP}.log"

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

# 全周期回测（最完整的数据）
FULL_START = "2018-01-01"
FULL_END   = "2024-12-31"

# 关键子窗口（对应 WF 测试期）
SUB_WINDOWS = [
    {"name": "W1_2020", "start": "2020-01-01", "end": "2020-12-31", "label": "COVID崩溃+反弹"},
    {"name": "W2_2021", "start": "2021-01-01", "end": "2021-12-31", "label": "牛市"},
    {"name": "W3_2022", "start": "2022-01-01", "end": "2022-12-31", "label": "熊市"},
    {"name": "W4_2023", "start": "2023-01-01", "end": "2023-12-31", "label": "风格切换"},
    {"name": "W5_2024", "start": "2024-01-01", "end": "2024-12-31", "label": "AI牛市"},
]

# 锁定参数（WF 对比用）
TOP_N = 3
HB    = 0.0

N_PERMUTATIONS = 500   # 置换检验次数
N_BOOTSTRAP    = 1000  # Bootstrap 次数


# ============================================================
# 辅助函数
# ============================================================

def _weekly_returns_from_bt(bt_result: dict) -> np.ndarray:
    """从回测结果提取周度收益序列"""
    eq = bt_result.get("equity_curve", [])
    if len(eq) < 2:
        return np.array([])
    # equity_curve 是日线，转为周度（每5个交易日）
    weekly = []
    step = 5
    for i in range(step, len(eq), step):
        w_ret = (eq[i] / eq[i - step]) - 1
        weekly.append(w_ret)
    return np.array(weekly)


def _compute_sharpe(returns: np.ndarray) -> float:
    if len(returns) < 4:
        return 0.0
    ann_ret = float(returns.mean() * 52)
    vol = float(returns.std(ddof=1) * np.sqrt(52)) if returns.std() > 0 else 1e-9
    return ann_ret / vol if vol > 0 else 0.0


def _compute_mdd(returns: np.ndarray) -> float:
    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        cum *= (1 + r)
        if cum > peak:
            peak = cum
        dd = (cum - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return max_dd  # 负数


def _compute_underwater_weeks(returns: np.ndarray) -> int:
    """最长连续水下（回撤期）周数"""
    cum = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(cum)
    underwater = cum < peak
    max_run = 0
    cur_run = 0
    for u in underwater:
        if u:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 0
    return max_run


def _max_consecutive_losses(returns: np.ndarray) -> int:
    """最长连续亏损周数"""
    max_run = 0
    cur_run = 0
    for r in returns:
        if r < 0:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 0
    return max_run


# ============================================================
# 测试 1: 置换检验
# ============================================================

def permutation_test(returns: np.ndarray, n_iter: int = 500, label: str = "") -> dict:
    """对收益序列打乱，检验实际 Sharpe 是否显著高于随机"""
    real_sharpe = _compute_sharpe(returns)
    shuffled_sharpes = []
    rng = np.random.default_rng(42)

    for _ in range(n_iter):
        shuffled = rng.permutation(returns)
        shuffled_sharpes.append(_compute_sharpe(shuffled))

    shuffled_sharpes = np.array(shuffled_sharpes)
    p_value = float((shuffled_sharpes >= real_sharpe).mean())

    result = {
        "label":           label,
        "real_sharpe":     round(real_sharpe, 3),
        "n_iter":          n_iter,
        "median_shuffled": round(float(np.median(shuffled_sharpes)), 3),
        "pct95_shuffled":  round(float(np.percentile(shuffled_sharpes, 95)), 3),
        "p_value":         round(p_value, 4),
        "significant":     p_value < 0.05,
        "verdict":         "✅ 统计显著 (p < 0.05)" if p_value < 0.05 else "❌ 不显著 (p >= 0.05)",
    }
    logger.info(
        f"  [{label}] 置换检验: 实际Sharpe={real_sharpe:.3f}  "
        f"打乱中位={result['median_shuffled']:.3f}  "
        f"p={p_value:.4f}  {result['verdict']}"
    )
    return result


# ============================================================
# 测试 2: Bootstrap 置信区间
# ============================================================

def bootstrap_ci(returns: np.ndarray, n_iter: int = 1000, label: str = "") -> dict:
    """有放回重采样，得到关键指标的置信区间"""
    rng = np.random.default_rng(42)
    sharpes = []
    mdds    = []
    cumrets = []

    for _ in range(n_iter):
        sample = rng.choice(returns, size=len(returns), replace=True)
        sharpes.append(_compute_sharpe(sample))
        mdds.append(_compute_mdd(sample))
        cumrets.append(float(np.prod(1 + sample) - 1))

    def ci(arr, lo=5, hi=95):
        return round(float(np.percentile(arr, lo)), 3), round(float(np.percentile(arr, hi)), 3)

    sharpe_ci = ci(sharpes)
    mdd_ci    = ci(mdds)
    ret_ci    = ci(cumrets)

    result = {
        "label":          label,
        "n_iter":         n_iter,
        "sharpe_median":  round(float(np.median(sharpes)), 3),
        "sharpe_ci90":    sharpe_ci,
        "mdd_median":     round(float(np.median(mdds)), 3),
        "mdd_p5":         round(float(np.percentile(mdds, 5)), 3),   # 最差 5% MDD
        "mdd_ci90":       mdd_ci,
        "annual_ret_median": round(float(np.median(cumrets)), 3),
        "annual_ret_ci90":   ret_ci,
    }
    logger.info(
        f"  [{label}] Bootstrap: "
        f"Sharpe {sharpe_ci[0]}~{sharpe_ci[1]}  "
        f"MDD P5={result['mdd_p5']:.1%}  "
        f"Ret P5~P95={ret_ci[0]:.1%}~{ret_ci[1]:.1%}"
    )
    return result


# ============================================================
# 测试 3: 连续亏损分析
# ============================================================

def consecutive_loss_analysis(returns: np.ndarray, label: str = "") -> dict:
    max_consec_loss = _max_consecutive_losses(returns)
    max_underwater  = _compute_underwater_weeks(returns)
    win_rate = float((returns > 0).mean())
    loss_rate = float((returns < 0).mean())

    result = {
        "label":                label,
        "win_rate":             round(win_rate, 3),
        "loss_rate":            round(loss_rate, 3),
        "max_consecutive_losses": max_consec_loss,
        "max_underwater_weeks":   max_underwater,
    }
    logger.info(
        f"  [{label}] 连续亏损: 最长={max_consec_loss}周  "
        f"水下最长={max_underwater}周  "
        f"胜率={win_rate:.0%}"
    )
    return result


# ============================================================
# 主测试执行
# ============================================================

async def run_stress_tests(prefetched: dict) -> dict:
    from app.services.rotation_service import run_rotation_backtest

    all_results = {
        "permutation": {},
        "bootstrap":   {},
        "consecutive": {},
        "subwindow_comparison": [],
    }

    # ── 全周期回测（获取完整收益序列）──
    logger.info("\n" + "=" * 60)
    logger.info("  全周期回测 (2018-2024) 获取收益序列")
    logger.info("=" * 60)

    for label, disable_regime in [("v4", False), ("alpha", True)]:
        r = await run_rotation_backtest(
            start_date=FULL_START,
            end_date=FULL_END,
            top_n=TOP_N,
            holding_bonus=HB,
            _prefetched=prefetched,
            disable_regime_filter=disable_regime,
        )
        if "error" in r:
            logger.error(f"全周期回测 [{label}] 失败: {r['error']}")
            continue

        weekly = _weekly_returns_from_bt(r)
        if len(weekly) < 10:
            logger.warning(f"[{label}] 周度收益太少: {len(weekly)} 周")
            continue

        logger.info(f"\n── {label.upper()} 策略（全周期 2018-2024，{len(weekly)} 周）──")

        # 测试 1: 置换检验
        logger.info("  测试1: 置换检验")
        perm = permutation_test(weekly, N_PERMUTATIONS, label.upper())
        all_results["permutation"][label] = perm

        # 测试 2: Bootstrap
        logger.info("  测试2: Bootstrap 置信区间")
        boot = bootstrap_ci(weekly, N_BOOTSTRAP, label.upper())
        all_results["bootstrap"][label] = boot

        # 测试 3: 连续亏损
        logger.info("  测试3: 连续亏损分析")
        consec = consecutive_loss_analysis(weekly, label.upper())
        all_results["consecutive"][label] = consec

    # ── 子窗口对比（聚焦关键年份）──
    logger.info("\n" + "=" * 60)
    logger.info("  子窗口对比（5个 WF 测试期）")
    logger.info("=" * 60)

    for sw in SUB_WINDOWS:
        logger.info(f"\n  [{sw['name']} {sw['label']}]")
        sw_result = {
            "window": sw["name"],
            "label":  sw["label"],
            "period": f"{sw['start']} ~ {sw['end']}",
        }

        for mode, disable in [("v4", False), ("alpha", True)]:
            r = await run_rotation_backtest(
                start_date=sw["start"],
                end_date=sw["end"],
                top_n=TOP_N,
                holding_bonus=HB,
                _prefetched=prefetched,
                disable_regime_filter=disable,
            )
            if "error" in r:
                sw_result[mode] = {"error": r["error"]}
                continue

            weekly = _weekly_returns_from_bt(r)
            if len(weekly) < 4:
                sw_result[mode] = {"error": "数据不足"}
                continue

            sharpe  = _compute_sharpe(weekly)
            mdd     = _compute_mdd(weekly)
            cumret  = float(np.prod(1 + weekly) - 1)
            win     = float((weekly > 0).mean())
            mcl     = _max_consecutive_losses(weekly)
            muw     = _compute_underwater_weeks(weekly)

            sw_result[mode] = {
                "sharpe":              round(sharpe, 3),
                "cumulative_return":   round(cumret, 4),
                "max_drawdown":        round(mdd, 4),
                "win_rate":            round(win, 3),
                "max_consec_losses":   mcl,
                "max_underwater_weeks": muw,
                "n_weeks":             len(weekly),
            }
            logger.info(
                f"    {mode.upper()}: Sharpe={sharpe:.3f}  "
                f"Ret={cumret:+.1%}  MDD={mdd:.1%}  "
                f"最长亏损={mcl}周  水下={muw}周"
            )

        # Alpha vs V4 差值
        alpha_s = sw_result.get("alpha", {}).get("sharpe")
        v4_s    = sw_result.get("v4",    {}).get("sharpe")
        if alpha_s is not None and v4_s is not None:
            diff = alpha_s - v4_s
            sw_result["alpha_advantage"] = round(diff, 3)
            verdict = "← Alpha优" if diff > 0.2 else ("← V4优" if diff < -0.2 else "~ 同等")
            logger.info(f"    差值: {diff:+.3f}  {verdict}")

        all_results["subwindow_comparison"].append(sw_result)

    return all_results


# ============================================================
# 汇总打印
# ============================================================

def print_final_summary(results: dict):
    logger.info("")
    logger.info("=" * 70)
    logger.info("  纯 Alpha 压力测试 — 最终判决")
    logger.info("=" * 70)

    # 置换检验
    logger.info("")
    logger.info("【置换检验结果】")
    for label, r in results["permutation"].items():
        logger.info(f"  {label.upper()}: {r.get('verdict', 'N/A')}  "
                    f"(实际Sharpe={r.get('real_sharpe')}  p={r.get('p_value')})")

    # Bootstrap MDD 尾部
    logger.info("")
    logger.info("【Bootstrap MDD 尾部（P5 最差情景）】")
    for label, r in results["bootstrap"].items():
        p5 = r.get("mdd_p5", 0)
        acceptable = "✅ 可接受" if abs(p5) < 0.45 else "⚠️  偏高"
        logger.info(f"  {label.upper()}: P5 MDD = {p5:.1%}  {acceptable}")

    # 连续亏损
    logger.info("")
    logger.info("【最长连续亏损 & 水下时间】")
    for label, r in results["consecutive"].items():
        logger.info(f"  {label.upper()}: 最长亏损={r.get('max_consecutive_losses')}周  "
                    f"水下={r.get('max_underwater_weeks')}周  "
                    f"胜率={r.get('win_rate'):.0%}")

    # 子窗口总结
    logger.info("")
    logger.info("【分窗口 Alpha 优势汇总】")
    advantages = []
    for sw in results["subwindow_comparison"]:
        adv = sw.get("alpha_advantage")
        flag = ""
        if adv is not None:
            advantages.append(adv)
            if adv > 0.2:   flag = "← Alpha优"
            elif adv < -0.2: flag = "← V4优"
            else:             flag = "~ 同等"
        logger.info(
            f"  {sw['window']} [{sw['label']}]: "
            f"Alpha优势={adv:+.3f if adv else 'N/A'}  {flag}"
        )

    # 最终 PASS/FAIL
    logger.info("")
    logger.info("─" * 70)

    alpha_perm = results["permutation"].get("alpha", {})
    alpha_boot = results["bootstrap"].get("alpha", {})
    alpha_consec = results["consecutive"].get("alpha", {})

    checks = {
        "置换检验显著 (p<0.05)":      alpha_perm.get("significant", False),
        "Bootstrap P5 MDD < 45%":   abs(alpha_boot.get("mdd_p5", -1)) < 0.45,
        "最长连亏 ≤ 6周":            alpha_consec.get("max_consecutive_losses", 99) <= 6,
        "水下时间 ≤ 30周":           alpha_consec.get("max_underwater_weeks", 99) <= 30,
        "全窗口 Alpha 平均优势 > 0": (np.mean(advantages) > 0 if advantages else False),
    }

    passed = sum(checks.values())
    total  = len(checks)

    for check, ok in checks.items():
        logger.info(f"  {'✅' if ok else '❌'} {check}")

    logger.info("─" * 70)
    if passed >= 4:
        logger.info(f"  🟢 最终判决: PASS ({passed}/{total}) — 纯 Alpha 风险特征可接受，建议去掉 Regime 门控")
    elif passed >= 3:
        logger.info(f"  🟡 最终判决: 条件通过 ({passed}/{total}) — 可以推进，但需关注未通过项")
    else:
        logger.info(f"  🔴 最终判决: FAIL ({passed}/{total}) — 纯 Alpha 风险不可接受，维持 Regime 门控")

    logger.info("=" * 70)


# ============================================================
# 主流程
# ============================================================

async def main(cache_only: bool = False):
    logger.info("=" * 70)
    logger.info("  StockQueen — 纯 Alpha 策略压力测试")
    logger.info(f"  回测周期: {FULL_START} ~ {FULL_END}")
    logger.info(f"  参数: top_n={TOP_N} HB={HB}")
    logger.info(f"  置换检验: {N_PERMUTATIONS}次  Bootstrap: {N_BOOTSTRAP}次")
    logger.info("=" * 70)

    from app.services.rotation_service import _fetch_backtest_data

    if not cache_only:
        logger.info("正在预取历史数据...")
        t0 = time.time()
        prefetched = await _fetch_backtest_data(FULL_START, FULL_END)
        if "error" in prefetched:
            logger.error(f"数据预取失败: {prefetched['error']}")
            return
        logger.info(f"数据预取完成: {len(prefetched.get('histories', {}))} 只 ({time.time()-t0:.0f}s)")
    else:
        logger.info("--cache-only 模式")
        prefetched = {}

    results = await run_stress_tests(prefetched)
    print_final_summary(results)

    output = {
        "meta": {
            "test":            "Pure Alpha Stress Test",
            "timestamp":       TIMESTAMP,
            "full_period":     f"{FULL_START} ~ {FULL_END}",
            "top_n":           TOP_N,
            "holding_bonus":   HB,
            "n_permutations":  N_PERMUTATIONS,
            "n_bootstrap":     N_BOOTSTRAP,
        },
        "results": results,
    }
    out_file = RESULTS_DIR / f"pure_alpha_stress_{TIMESTAMP}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info(f"\n结果已保存: {out_file}")
    logger.info(f"日志已保存: {log_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="纯 Alpha 策略压力测试")
    parser.add_argument("--cache-only", action="store_true", help="跳过数据预取，使用已有缓存")
    args = parser.parse_args()
    asyncio.run(main(cache_only=args.cache_only))
