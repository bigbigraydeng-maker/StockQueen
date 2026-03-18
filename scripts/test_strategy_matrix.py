"""
StockQueen - 策略矩阵测试脚本
测试三策略组合：V4趋势 + 均值回归 + 事件驱动

使用方法：
    python scripts/test_strategy_matrix.py

测试内容：
  1. 均值回归独立回测（2021-2024）
  2. 事件驱动独立回测（2021-2024）
  3. 组合回测（三种资金分配方案对比）
  4. 相关性矩阵分析

生产隔离保证：
  - 只读取数据，不修改任何生产数据库
  - 结果写入 scripts/strategy_matrix_results/ 目录
  - 使用独立日志文件，不污染生产日志
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 路径修正（确保能import app模块）
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

# ============================================================
# 日志配置（独立文件，不污染生产日志）
# ============================================================

RESULTS_DIR = ROOT_DIR / "scripts" / "strategy_matrix_results"
RESULTS_DIR.mkdir(exist_ok=True)

log_file = RESULTS_DIR / f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("strategy_matrix_test")


# ============================================================
# 测试配置
# ============================================================

TEST_PERIODS = [
    ("2018-01-01", "2018-12-31", "2018 (高波动+Q4暴跌)"),
    ("2019-01-01", "2019-12-31", "2019 (强牛市)"),
    ("2020-01-01", "2020-12-31", "2020 (COVID崩盘+反弹)"),
    ("2021-04-01", "2021-12-31", "2021 (V4热身期后)"),
    ("2022-01-01", "2022-12-31", "2022 (熊市)"),
    ("2023-01-01", "2023-12-31", "2023 (震荡牛市)"),
    ("2024-01-01", "2024-12-31", "2024 (强牛市)"),
    ("2018-01-01", "2024-12-31", "全周期 2018-2024"),
]

# 三种资金分配方案（变量二测试）
ALLOCATION_SCHEMES = [
    {
        "name": "保守方案",
        "alloc": {"v4": 0.60, "mean_reversion": 0.20, "event_driven": 0.15, "cash": 0.05},
    },
    {
        "name": "均衡方案",
        "alloc": {"v4": 0.50, "mean_reversion": 0.25, "event_driven": 0.20, "cash": 0.05},
    },
    {
        "name": "激进方案",
        "alloc": {"v4": 0.40, "mean_reversion": 0.30, "event_driven": 0.25, "cash": 0.05},
    },
]


# ============================================================
# 测试函数
# ============================================================

async def test_mean_reversion_standalone():
    """测试1：均值回归策略独立回测"""
    from app.services.mean_reversion_service import run_mean_reversion_backtest

    logger.info("=" * 60)
    logger.info("测试1：均值回归策略独立回测")
    logger.info("=" * 60)

    results = {}
    for start, end, label in TEST_PERIODS:
        logger.info(f"\n▶ {label} ({start} → {end})")
        try:
            result = await run_mean_reversion_backtest(start_date=start, end_date=end)
            results[label] = result
            _print_summary("均值回归", result)
        except Exception as e:
            logger.error(f"  ❌ 错误: {e}", exc_info=True)
            results[label] = {"error": str(e)}

    _save_results("mean_reversion_standalone", results)
    return results


async def test_event_driven_standalone():
    """测试2：事件驱动策略独立回测"""
    from app.services.event_driven_service import run_event_driven_backtest

    logger.info("=" * 60)
    logger.info("测试2：事件驱动策略独立回测")
    logger.info("=" * 60)

    results = {}
    for start, end, label in TEST_PERIODS:
        logger.info(f"\n▶ {label} ({start} → {end})")
        try:
            result = await run_event_driven_backtest(start_date=start, end_date=end)
            results[label] = result
            _print_summary("事件驱动", result)
        except Exception as e:
            logger.error(f"  ❌ 错误: {e}", exc_info=True)
            results[label] = {"error": str(e)}

    _save_results("event_driven_standalone", results)
    return results


async def test_allocation_schemes():
    """测试3：不同资金分配方案的组合回测"""
    from app.services.portfolio_manager import run_portfolio_backtest

    logger.info("=" * 60)
    logger.info("测试3：资金分配方案对比（全周期 2018-2024）")
    logger.info("=" * 60)

    start, end = "2018-01-01", "2024-12-31"
    results = {}

    for scheme in ALLOCATION_SCHEMES:
        logger.info(f"\n▶ {scheme['name']}: {scheme['alloc']}")
        try:
            result = await run_portfolio_backtest(
                start_date=start,
                end_date=end,
                allocation_override=scheme["alloc"],
            )
            results[scheme["name"]] = result
            _print_portfolio_summary(scheme["name"], result)
        except Exception as e:
            logger.error(f"  ❌ 错误: {e}", exc_info=True)
            results[scheme["name"]] = {"error": str(e)}

    _save_results("allocation_schemes_comparison", results)
    return results


async def test_correlation_analysis():
    """测试4：策略相关性分析（关键验证：相关性是否足够低）"""
    from app.services.portfolio_manager import run_portfolio_backtest

    logger.info("=" * 60)
    logger.info("测试4：策略相关性分析")
    logger.info("=" * 60)

    start, end = "2018-01-01", "2024-12-31"
    try:
        result = await run_portfolio_backtest(start_date=start, end_date=end)
        corr = result.get("correlations", {})

        logger.info("\n📊 相关性矩阵：")
        logger.info(f"  V4 ↔ 均值回归:   {corr.get('v4_vs_mean_reversion', 'N/A'):.3f}  {corr.get('assessment', {}).get('v4_vs_mean_reversion', '')}")
        logger.info(f"  V4 ↔ 事件驱动:   {corr.get('v4_vs_event_driven', 'N/A'):.3f}  {corr.get('assessment', {}).get('v4_vs_event_driven', '')}")
        logger.info(f"  均值回归 ↔ 事件: {corr.get('mean_reversion_vs_event_driven', 'N/A'):.3f}  {corr.get('assessment', {}).get('mean_reversion_vs_event_driven', '')}")
        logger.info(f"\n  结论: {corr.get('diversification_verdict', '')}")

        _save_results("correlation_analysis", {"correlations": corr, "period": f"{start}→{end}"})
        return corr
    except Exception as e:
        logger.error(f"相关性分析失败: {e}", exc_info=True)
        return {}


async def test_vix_adjustment():
    """测试5：VIX调节逻辑验证"""
    from app.services.portfolio_manager import get_strategy_allocations

    logger.info("=" * 60)
    logger.info("测试5：VIX全局调节逻辑")
    logger.info("=" * 60)

    test_cases = [
        ("bull", None),
        ("bull", 15.0),
        ("bull", 28.0),
        ("bull", 38.0),
        ("choppy", 22.0),
        ("bear", 40.0),
    ]

    for regime, vix in test_cases:
        alloc = get_strategy_allocations(regime, vix=vix)
        vix_str = f"VIX={vix}" if vix else "VIX=N/A"
        logger.info(
            f"  {regime:12s} {vix_str:10s} → "
            f"V4={alloc['v4']:.0%} MR={alloc['mean_reversion']:.0%} "
            f"ED={alloc['event_driven']:.0%} 现金={alloc['cash']:.0%}"
            f"  [{alloc.get('note', '')}]"
        )


# ============================================================
# 输出格式化
# ============================================================

def _print_summary(strategy_name: str, result: dict):
    """打印单策略回测摘要。"""
    if "error" in result:
        logger.error(f"  ❌ {strategy_name}: {result['error']}")
        return
    logger.info(
        f"  {strategy_name}: "
        f"累计={result.get('cumulative_return', 0):+.1%}  "
        f"年化={result.get('annualized_return', 0):+.1%}  "
        f"夏普={result.get('sharpe_ratio', 0):.2f}  "
        f"回撤={result.get('max_drawdown', 0):.1%}  "
        f"胜率={result.get('win_rate', 0):.1%}  "
        f"交易={result.get('total_trades', 0)}次"
    )


def _print_portfolio_summary(scheme_name: str, result: dict):
    """打印组合回测摘要。"""
    if "error" in result:
        logger.error(f"  ❌ {scheme_name}: {result['error']}")
        return

    port = result.get("portfolio", {})
    subs = result.get("sub_strategies", {})

    logger.info(f"\n  📦 {scheme_name}:")
    logger.info(
        f"    组合: 累计={port.get('cumulative_return', 0):+.1%}  "
        f"年化={port.get('annualized_return', 0):+.1%}  "
        f"夏普={port.get('sharpe_ratio', 0):.2f}  "
        f"回撤={port.get('max_drawdown', 0):.1%}"
    )
    for name, sub in subs.items():
        logger.info(
            f"    └ {ALLOCATION_SCHEMES[0]['alloc'].get(name, 0):.0%} {name}: "
            f"累计={sub.get('cumulative_return', 0):+.1%}  "
            f"夏普={sub.get('sharpe_ratio', 0):.2f}"
        )


def _save_results(test_name: str, results: dict):
    """保存测试结果到JSON文件（生产隔离）。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = RESULTS_DIR / f"{test_name}_{timestamp}.json"

    # 清理不可序列化的数据（equity_curve可能很大）
    def clean(obj):
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items() if k != "equity_curve"}
        elif isinstance(obj, list):
            return [clean(i) for i in obj]
        elif isinstance(obj, float):
            return round(obj, 6)
        return obj

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(clean(results), f, ensure_ascii=False, indent=2)
        logger.info(f"  💾 结果已保存: {filepath}")
    except Exception as e:
        logger.warning(f"  ⚠️ 结果保存失败: {e}")


# ============================================================
# 主函数
# ============================================================

async def main():
    logger.info("🚀 StockQueen 策略矩阵测试开始")
    logger.info(f"📁 结果目录: {RESULTS_DIR}")
    logger.info(f"📋 日志文件: {log_file}")
    logger.info("=" * 60)

    # 按顺序执行所有测试
    await test_vix_adjustment()          # 最快，无API调用
    await test_mean_reversion_standalone()
    await test_event_driven_standalone()
    await test_allocation_schemes()
    await test_correlation_analysis()

    logger.info("\n" + "=" * 60)
    logger.info("✅ 所有测试完成")
    logger.info(f"📁 结果保存在: {RESULTS_DIR}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["vix","mr","ed","alloc","corr"], default=None,
                        help="只跑指定测试: vix/mr/ed/alloc/corr")
    args = parser.parse_args()

    async def main_selective():
        logger.info("🚀 StockQueen 策略矩阵测试开始")
        logger.info(f"📁 结果目录: {RESULTS_DIR}")
        logger.info(f"📋 日志文件: {log_file}")
        logger.info("=" * 60)
        only = args.only
        if only is None or only == "vix":   await test_vix_adjustment()
        if only is None or only == "mr":    await test_mean_reversion_standalone()
        if only is None or only == "ed":    await test_event_driven_standalone()
        if only is None or only == "alloc": await test_allocation_schemes()
        if only is None or only == "corr":  await test_correlation_analysis()
        logger.info("\n" + "=" * 60)
        logger.info("✅ 测试完成")
        logger.info(f"📁 结果保存在: {RESULTS_DIR}")

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main_selective())
