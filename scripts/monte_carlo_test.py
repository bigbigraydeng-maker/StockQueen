"""
StockQueen - 蒙特卡洛置换检验
================================
通过对交易信号/收益率序列的随机置换，检验策略的统计显著性。
若真实Sharpe显著高于随机基准，说明策略存在真实的预测边际，而非运气。

测试方法：
  1. 置换测试（Permutation Test）：
     - 运行真实回测 → 获取每笔交易的pnl_pct列表
     - 随机打乱收益顺序（保留真实收益分布，只改变时序）
     - 复利化得到新权益曲线 → 计算Sharpe
     - 500次迭代 → p值 = 随机Sharpe >= 真实Sharpe 的比例

  2. 随机入场测试（Random Entry Test）：
     - 同等交易次数，随机选入场日期
     - 固定 -2% 止损退出（保守假设）
     - 与真实策略Sharpe对比

判定标准：
  - p值 < 0.05 → 统计显著（拒绝"纯随机"假设）

测试期：2018-01-01 ~ 2024-12-31（完整周期，保障统计功效）

使用方法：
    cd StockQueen
    python scripts/monte_carlo_test.py                      # 全部策略，500次
    python scripts/monte_carlo_test.py --strategy mr        # 只测MR
    python scripts/monte_carlo_test.py --iterations 1000    # 1000次迭代
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
log_file = RESULTS_DIR / f"monte_carlo_{TIMESTAMP}.log"

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

logger = logging.getLogger("monte_carlo_test")

# 测试参数
MC_START_DATE = "2018-01-01"
MC_END_DATE   = "2024-12-31"

RANDOM_ENTRY_FIXED_STOP_PCT = 0.02   # 随机入场测试：固定止损 -2%


# ============================================================
# 核心统计函数
# ============================================================

def _compute_sharpe_from_returns(returns: list) -> float:
    """
    将离散收益率列表（如 [0.02, -0.01, ...]）转为年化Sharpe。
    注意：这里假设每笔收益是独立的交易收益，不是日收益。
    使用复利化权益曲线计算。
    """
    if len(returns) < 5:
        return 0.0

    arr = np.array(returns, dtype=float)
    # 将百分比转为小数（如果传入的是 pnl_pct 格式如 2.5，则需要/100）
    if np.abs(arr).max() > 5.0:  # 假设传入的是百分比
        arr = arr / 100.0

    # 构建权益曲线
    equity = np.cumprod(1.0 + arr)
    cum_ret = equity[-1] - 1.0

    # 用每笔交易收益计算Sharpe（以交易为单位，再年化）
    # 假设全年252天交易日，平均每笔持仓数天
    mean_ret = float(np.mean(arr))
    std_ret  = float(np.std(arr, ddof=1)) if len(arr) > 1 else 1e-9

    if std_ret < 1e-9:
        return 0.0

    # 年化：n_trades per year ≈ total_trades (全周期 ≈ 6年 → /6)
    # 用更稳健的信息比率方式：mean/std * sqrt(n_trades_per_year)
    # 近似：6年数据，假设交易均匀分布
    n_per_year = len(returns) / 6.0
    sharpe = (mean_ret / std_ret) * np.sqrt(max(n_per_year, 1))
    return float(sharpe)


def _permutation_sharpe(trade_returns: list, n_iter: int, rng: np.random.Generator) -> np.ndarray:
    """
    对 trade_returns 进行 n_iter 次随机置换，返回每次的Sharpe数组。
    trade_returns: 每笔交易 pnl_pct（百分比，如 2.5 表示+2.5%）
    """
    arr = np.array(trade_returns, dtype=float)
    sharpes = np.empty(n_iter)

    for i in range(n_iter):
        shuffled = rng.permutation(arr)
        sharpes[i] = _compute_sharpe_from_returns(shuffled.tolist())

    return sharpes


def _random_entry_sharpe(
    trade_count: int,
    all_dates: list,
    price_data: dict,  # {ticker: {"close": [...], "dates": [...]}}
    n_iter: int,
    rng: np.random.Generator,
    fixed_stop_pct: float = 0.02,
) -> float:
    """
    随机入场测试：随机选 trade_count 个 (日期, 股票) 组合入场，
    固定 -fixed_stop_pct 止损，计算平均Sharpe（单次，不迭代）。
    """
    if not all_dates or not price_data:
        return 0.0

    tickers = [t for t in price_data.keys() if t not in ("SPY", "QQQ")]
    if not tickers:
        return 0.0

    trade_returns = []
    attempts = 0
    max_attempts = trade_count * 10

    while len(trade_returns) < trade_count and attempts < max_attempts:
        attempts += 1
        # 随机选 ticker 和日期
        ticker = tickers[rng.integers(0, len(tickers))]
        h = price_data.get(ticker, {})
        dates_t = [str(d)[:10] for d in h.get("dates", [])]
        closes_t = h.get("close", [])

        if len(dates_t) < 5 or len(dates_t) != len(closes_t):
            continue

        # 随机选入场日期索引
        idx = int(rng.integers(0, len(dates_t) - 5))
        entry_price = closes_t[idx]
        stop_price = entry_price * (1.0 - fixed_stop_pct)

        # 简单模拟：持有至触发止损或最多10天退出
        exit_price = entry_price
        for j in range(1, min(11, len(closes_t) - idx)):
            cur_price = closes_t[idx + j]
            if cur_price <= stop_price:
                exit_price = stop_price
                break
            exit_price = cur_price

        pnl = (exit_price - entry_price) / entry_price * 100.0
        trade_returns.append(pnl)

    if not trade_returns:
        return 0.0

    return _compute_sharpe_from_returns(trade_returns)


# ============================================================
# 提取交易收益列表
# ============================================================

def _extract_trade_returns(backtest_result: dict, strategy: str) -> list:
    """
    从回测结果中提取每笔 exit 交易的 pnl_pct 列表。
    V4 策略没有逐笔 exit pnl，使用周收益率列表作为替代。
    """
    if strategy == "v4":
        # V4 weekly_details 有每周收益
        wd = backtest_result.get("weekly_details", [])
        returns = [entry["return_pct"] for entry in wd if "return_pct" in entry]
        return returns

    trades = backtest_result.get("trades", [])
    returns = [
        t["pnl_pct"]
        for t in trades
        if t.get("type") == "exit" and "pnl_pct" in t
    ]
    return returns


# ============================================================
# 策略级蒙特卡洛
# ============================================================

async def run_mc_for_strategy(
    strategy: str,
    n_iter: int,
    v4_prefetched: dict,
    mr_prefetched,
    ed_price: dict,
    ed_fund: dict,
) -> dict:
    """
    对单个策略执行完整蒙特卡洛分析。
    返回格式化结果字典。
    """
    strat_names = {"v4": "V4 轮动趋势", "mr": "MR 均值回归", "ed": "ED 事件驱动"}
    logger.info(f"[MC] 开始 {strat_names.get(strategy, strategy)} 蒙特卡洛分析")

    # ---- Step 1: 运行真实回测 ----
    real_result = {}
    try:
        if strategy == "v4":
            from app.services.rotation_service import run_rotation_backtest
            real_result = await run_rotation_backtest(
                start_date=MC_START_DATE,
                end_date=MC_END_DATE,
                _prefetched=v4_prefetched,
            )
        elif strategy == "mr":
            from app.services.mean_reversion_service import run_mean_reversion_backtest
            real_result = await run_mean_reversion_backtest(
                start_date=MC_START_DATE,
                end_date=MC_END_DATE,
                _prefetched=mr_prefetched,
            )
        elif strategy == "ed":
            from app.services.event_driven_service import run_event_driven_backtest
            real_result = await run_event_driven_backtest(
                start_date=MC_START_DATE,
                end_date=MC_END_DATE,
                _prefetched=ed_price,
                _prefetched_fundamentals=ed_fund,
            )
    except Exception as e:
        logger.error(f"[MC] {strategy} 真实回测失败: {e}")
        return {"strategy": strategy, "error": str(e)}

    if "error" in real_result:
        logger.error(f"[MC] {strategy} 真实回测返回错误: {real_result['error']}")
        return {"strategy": strategy, "error": real_result["error"]}

    real_sharpe = real_result.get("sharpe_ratio", 0.0)
    trade_returns = _extract_trade_returns(real_result, strategy)
    n_trades = len(trade_returns)

    logger.info(f"[MC] {strategy} 真实Sharpe={real_sharpe:.4f} 交易次数={n_trades}")

    if n_trades < 10:
        logger.warning(f"[MC] {strategy} 交易次数不足（{n_trades}），蒙特卡洛结果可能不可靠")

    # ---- Step 2: 置换测试 ----
    rng = np.random.default_rng(seed=42)
    logger.info(f"[MC] {strategy} 开始 {n_iter} 次置换测试...")
    t0 = time.time()
    shuffled_sharpes = _permutation_sharpe(trade_returns, n_iter, rng)
    elapsed_perm = time.time() - t0
    logger.info(f"[MC] {strategy} 置换测试完成，耗时 {elapsed_perm:.1f}s")

    # p值、统计量
    p_value = float(np.mean(shuffled_sharpes >= real_sharpe))
    median_shuffled = float(np.median(shuffled_sharpes))
    pct95_shuffled  = float(np.percentile(shuffled_sharpes, 95))
    pct5_shuffled   = float(np.percentile(shuffled_sharpes, 5))

    # ---- Step 3: 随机入场测试 ----
    price_data_for_random = {}
    if strategy == "v4":
        price_data_for_random = v4_prefetched.get("histories", {}) if isinstance(v4_prefetched, dict) else {}
    elif strategy == "mr":
        price_data_for_random = mr_prefetched if isinstance(mr_prefetched, dict) else {}
    elif strategy == "ed":
        price_data_for_random = ed_price or {}

    # 构建日期列表（从第一个有效股票中提取）
    all_dates = []
    for h in price_data_for_random.values():
        if h and "dates" in h:
            all_dates = [str(d)[:10] for d in h["dates"]]
            break

    logger.info(f"[MC] {strategy} 随机入场测试（{n_trades}笔，{n_iter}次迭代）...")
    random_entry_sharpes = np.array([
        _random_entry_sharpe(
            trade_count=max(n_trades, 10),
            all_dates=all_dates,
            price_data=price_data_for_random,
            n_iter=n_iter,
            rng=rng,
            fixed_stop_pct=RANDOM_ENTRY_FIXED_STOP_PCT,
        )
        for _ in range(min(n_iter, 200))   # 随机入场测试稍减少迭代次数（每次已含多笔交易）
    ])
    random_entry_median = float(np.median(random_entry_sharpes))

    # ---- 判定 ----
    is_significant = p_value < 0.05
    verdict = "✅ 统计显著 (p < 0.05)" if is_significant else "❌ 不显著 (p >= 0.05)"

    result = {
        "strategy": strategy,
        "strategy_name": strat_names.get(strategy, strategy),
        "real_sharpe": real_sharpe,
        "n_trades": n_trades,
        "permutation_test": {
            "n_iterations": n_iter,
            "median_shuffled_sharpe": round(median_shuffled, 4),
            "pct5_shuffled_sharpe":   round(pct5_shuffled, 4),
            "pct95_shuffled_sharpe":  round(pct95_shuffled, 4),
            "p_value": round(p_value, 4),
            "is_significant": is_significant,
        },
        "random_entry_test": {
            "description": f"随机入场+固定{RANDOM_ENTRY_FIXED_STOP_PCT*100:.0f}%止损",
            "iterations": len(random_entry_sharpes),
            "median_random_entry_sharpe": round(random_entry_median, 4),
        },
        "verdict": verdict,
        "backtest_summary": {
            "cumulative_return": real_result.get("cumulative_return"),
            "max_drawdown": real_result.get("max_drawdown"),
            "win_rate": real_result.get("win_rate"),
            "annualized_return": real_result.get("annualized_return"),
        },
    }
    return result


# ============================================================
# 打印输出
# ============================================================

def print_mc_result(r: dict):
    """美观打印单个策略的蒙特卡洛结果"""
    if "error" in r:
        print(f"\n策略: {r['strategy']}")
        print(f"  错误: {r['error']}")
        return

    strat_name = r.get("strategy_name", r["strategy"])
    perm = r.get("permutation_test", {})
    rand = r.get("random_entry_test", {})
    bt   = r.get("backtest_summary", {})

    block = (
        f"\n策略: {strat_name}\n"
        f"{'─'*45}\n"
        f"真实 Sharpe:          {r['real_sharpe']:.4f}\n"
        f"交易次数:             {r['n_trades']}\n"
        f"累计收益:             {bt.get('cumulative_return', 0):+.2%}\n"
        f"最大回撤:             {bt.get('max_drawdown', 0):.2%}\n"
        f"胜率:                 {bt.get('win_rate', 0):.1%}\n"
        f"\n--- 置换检验 ({perm.get('n_iterations', 0)} 次迭代) ---\n"
        f"随机中位 Sharpe:      {perm.get('median_shuffled_sharpe', 0):.4f}\n"
        f"随机 5分位 Sharpe:    {perm.get('pct5_shuffled_sharpe', 0):.4f}\n"
        f"随机 95分位 Sharpe:   {perm.get('pct95_shuffled_sharpe', 0):.4f}\n"
        f"p值:                  {perm.get('p_value', 1.0):.4f}\n"
        f"\n--- 随机入场测试 ---\n"
        f"随机入场中位 Sharpe:  {rand.get('median_random_entry_sharpe', 0):.4f}\n"
        f"\n结论:                 {r['verdict']}\n"
        f"{'─'*45}"
    )
    print(block)
    logger.info(f"[MC结果] {strat_name}: Sharpe={r['real_sharpe']:.4f} p={perm.get('p_value'):.4f} {r['verdict']}")


# ============================================================
# 主函数
# ============================================================

async def main():
    parser = argparse.ArgumentParser(description="StockQueen 蒙特卡洛置换检验")
    parser.add_argument(
        "--strategy", choices=["mr", "ed", "v4", "all"], default="all",
        help="测试策略（默认all）",
    )
    parser.add_argument(
        "--iterations", type=int, default=500,
        help="蒙特卡洛迭代次数（默认500）",
    )
    args = parser.parse_args()

    strategies = (
        ["v4", "mr", "ed"] if args.strategy == "all"
        else [args.strategy]
    )
    n_iter = args.iterations

    print("=" * 60)
    print("  StockQueen 蒙特卡洛置换检验")
    print(f"  测试期：{MC_START_DATE} ~ {MC_END_DATE}")
    print(f"  策略：{', '.join(strategies)}")
    print(f"  迭代次数：{n_iter}")
    print("=" * 60)
    logger.info(f"蒙特卡洛检验启动: 策略={strategies} 迭代={n_iter}")

    t_total = time.time()

    # ---- 数据预取 ----
    logger.info("[数据预取] 开始...")
    v4_prefetched = {}
    mr_prefetched = {}
    ed_price = {}
    ed_fund = {}

    if "v4" in strategies:
        try:
            from app.services.rotation_service import _fetch_backtest_data
            v4_prefetched = await _fetch_backtest_data(MC_START_DATE, MC_END_DATE)
            logger.info(f"[数据预取] V4: {len(v4_prefetched.get('histories', {}))}只")
        except Exception as e:
            logger.error(f"[数据预取] V4失败: {e}")

    if "mr" in strategies:
        mr_prefetched = v4_prefetched.get("histories", {}) if v4_prefetched else {}
        if not mr_prefetched:
            try:
                from app.services.mean_reversion_service import _fetch_mr_data
                mr_prefetched = await _fetch_mr_data(MC_START_DATE, MC_END_DATE)
                logger.info(f"[数据预取] MR: {len(mr_prefetched)}只")
            except Exception as e:
                logger.error(f"[数据预取] MR失败: {e}")
        else:
            logger.info(f"[数据预取] MR复用V4数据: {len(mr_prefetched)}只")

    if "ed" in strategies:
        try:
            from app.services.event_driven_service import _fetch_ed_data
            ed_price, ed_fund = await _fetch_ed_data(MC_START_DATE, MC_END_DATE)
            logger.info(f"[数据预取] ED: 价格{len(ed_price)}只, 财报{len(ed_fund)}只")
        except Exception as e:
            logger.error(f"[数据预取] ED失败: {e}")

    # ---- 逐策略执行 ----
    all_results = []
    for strategy in strategies:
        t_strat = time.time()
        print(f"\n{'='*60}")
        print(f"  正在检验: {strategy.upper()}")
        print(f"{'='*60}")
        try:
            result = await run_mc_for_strategy(
                strategy=strategy,
                n_iter=n_iter,
                v4_prefetched=v4_prefetched,
                mr_prefetched=mr_prefetched,
                ed_price=ed_price,
                ed_fund=ed_fund,
            )
        except Exception as e:
            logger.error(f"[MC] {strategy} 顶层异常: {e}")
            result = {"strategy": strategy, "error": str(e)}

        all_results.append(result)
        print_mc_result(result)
        elapsed_s = time.time() - t_strat
        logger.info(f"[MC] {strategy} 完成，耗时 {elapsed_s:.0f}s")

    # ---- 综合汇总 ----
    print(f"\n{'='*60}")
    print("  综合显著性汇总")
    print("=" * 60)
    sig_count = 0
    for r in all_results:
        if "error" in r:
            print(f"  {r['strategy']:6s}: ERR")
            continue
        perm = r.get("permutation_test", {})
        sig = perm.get("is_significant", False)
        if sig:
            sig_count += 1
        icon = "✅" if sig else "❌"
        print(
            f"  {r['strategy']:6s}: {icon}  "
            f"Sharpe={r['real_sharpe']:.3f}  "
            f"p={perm.get('p_value', 1.0):.4f}  "
            f"95th随机={perm.get('pct95_shuffled_sharpe', 0):.3f}"
        )
    print(f"\n  {sig_count}/{len(all_results)} 个策略通过显著性检验 (p < 0.05)")

    # ---- 保存结果 ----
    out_data = {
        "meta": {
            "test": "蒙特卡洛置换检验",
            "timestamp": TIMESTAMP,
            "start_date": MC_START_DATE,
            "end_date": MC_END_DATE,
            "strategies": strategies,
            "n_iterations": n_iter,
        },
        "results": all_results,
        "summary": {
            "strategies_tested": len(all_results),
            "strategies_significant": sig_count,
            "significance_rate": round(sig_count / len(all_results), 3) if all_results else 0,
        },
    }

    out_file = RESULTS_DIR / f"monte_carlo_{TIMESTAMP}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2, ensure_ascii=False, default=str)

    elapsed = time.time() - t_total
    print(f"\n{'='*60}")
    print(f"  蒙特卡洛检验完成，耗时 {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  结果已保存: {out_file}")
    print(f"  日志文件:   {log_file}")
    print("=" * 60)
    logger.info(f"蒙特卡洛检验完成，结果保存至 {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
