"""
StockQueen - 参数敏感性分析脚本
=================================
逐参数单独扫描（1D sweep），固定其余参数为默认值，分析每个参数对策略表现的影响。

适用策略：
  - MR  均值回归（MeanReversionConfig）
  - ED  事件驱动（EventDrivenConfig）
  - V4  轮动趋势（RotationConfig top_n + BACKTEST_STOP_MULT）

测试周期：2022-01-01 ~ 2024-12-31（样本外数据）

使用方法：
    cd StockQueen
    python scripts/sensitivity_test.py                     # 全部策略
    python scripts/sensitivity_test.py --strategy mr       # 只测MR
    python scripts/sensitivity_test.py --strategy ed       # 只测ED
    python scripts/sensitivity_test.py --strategy v4       # 只测V4
    python scripts/sensitivity_test.py --start 2023-01-01 --end 2024-12-31

输出：
  - 每个参数一张ASCII表，默认值标 (*)，Sharpe颜色编码
  - 完整结果保存至 scripts/stress_test_results/sensitivity_TIMESTAMP.json
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime

# Windows GBK 终端兼容：强制 stdout/stderr 使用 UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

# ============================================================
# 结果目录 & 日志
# ============================================================

RESULTS_DIR = Path(__file__).parent / "stress_test_results"
RESULTS_DIR.mkdir(exist_ok=True)

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = RESULTS_DIR / f"sensitivity_{TIMESTAMP}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
# 降低底层服务的日志噪音
logging.getLogger("app.services.alphavantage_client").setLevel(logging.WARNING)
logging.getLogger("app.services.rotation_service").setLevel(logging.WARNING)
logging.getLogger("app.services.mean_reversion_service").setLevel(logging.WARNING)
logging.getLogger("app.services.event_driven_service").setLevel(logging.WARNING)

logger = logging.getLogger("sensitivity_test")

# ============================================================
# 参数范围定义
# ============================================================

MR_PARAM_GRID = {
    "RSI_ENTRY_THRESHOLD": {
        "values": [22, 24, 26, 28, 30, 32, 34],
        "default": 28.0,
        "label": "MR RSI入场阈值",
    },
    "BB_ENTRY_THRESHOLD": {
        "values": [0.0, 0.02, 0.05, 0.08, 0.12],
        "default": 0.05,
        "label": "MR 布林带入场阈值",
    },
    "ATR_STOP_MULT": {
        "values": [1.5, 1.75, 2.0, 2.25, 2.5],
        "default": 2.0,
        "label": "MR ATR止损倍数",
    },
    "MAX_HOLD_DAYS": {
        "values": [5, 6, 7, 8, 10, 12],
        "default": 8,
        "label": "MR 最大持仓天数",
    },
}

ED_PARAM_GRID = {
    "MIN_BEAT_RATE": {
        "values": [0.60, 0.65, 0.70, 0.75, 0.80],
        "default": 0.70,
        "label": "ED 最低超预期率",
    },
    "MIN_EPS_SURPRISE_PCT": {
        "values": [0.01, 0.015, 0.02, 0.025, 0.03],
        "default": 0.02,
        "label": "ED 最低EPS超预期幅度",
    },
    "ENTRY_DAYS_BEFORE_EARNINGS": {
        "values": [2, 3, 4, 5],
        "default": 3,
        "label": "ED 财报前建仓天数",
    },
    "ATR_STOP_MULT": {
        "values": [1.0, 1.25, 1.5, 1.75, 2.0],
        "default": 1.5,
        "label": "ED ATR止损倍数",
    },
}

V4_PARAM_GRID = {
    "top_n": {
        "values": [3, 4, 5, 6, 7, 8],
        "default": 6,
        "label": "V4 持仓数量 top_n",
    },
    "BACKTEST_STOP_MULT": {
        "values": [1.0, 1.25, 1.5, 1.75, 2.0],
        "default": 1.5,
        "label": "V4 ATR止损倍数",
    },
}


# ============================================================
# ASCII 表格打印
# ============================================================

def _sharpe_indicator(sharpe: float) -> str:
    """Sharpe颜色指示符（用emoji替代真彩色以确保终端兼容）"""
    if sharpe is None or sharpe != sharpe:  # NaN check
        return "⚪"
    if sharpe >= 1.0:
        return "🟢"
    elif sharpe >= 0.5:
        return "🟡"
    else:
        return "🔴"


def print_sensitivity_table(param_name: str, param_label: str, rows: list, default_val):
    """打印单个参数扫描结果的ASCII表格"""
    header = (
        f"\n{'─'*80}\n"
        f"  参数: {param_label}  (默认值={default_val}, 标注 *)\n"
        f"{'─'*80}"
    )
    print(header)
    logger.info(header)

    col_fmt = "{ind} {val:<10} {sharpe:<8} {ret:<10} {dd:<10} {trades:<8} {wr:<8}"
    hdr_line = col_fmt.format(
        ind="  ",
        val=f"{'参数值':<10}",
        sharpe=f"{'Sharpe':<8}",
        ret=f"{'累计收益':<10}",
        dd=f"{'最大回撤':<10}",
        trades=f"{'交易次数':<8}",
        wr=f"{'胜率':<8}",
    )
    print(hdr_line)
    logger.info(hdr_line)
    print("  " + "─" * 66)

    for row in rows:
        is_default = abs(float(row["param_value"]) - float(default_val)) < 1e-9
        marker = "(*)" if is_default else "   "
        ind = _sharpe_indicator(row.get("sharpe_ratio"))

        sharpe_val = row.get("sharpe_ratio")
        sharpe_str = f"{sharpe_val:.3f}" if sharpe_val is not None else "ERR"

        ret_val = row.get("cumulative_return")
        ret_str = f"{ret_val:+.1%}" if ret_val is not None else "ERR"

        dd_val = row.get("max_drawdown")
        dd_str = f"{dd_val:.1%}" if dd_val is not None else "ERR"

        trades_val = row.get("total_trades", row.get("weeks", "N/A"))
        wr_val = row.get("win_rate")
        wr_str = f"{wr_val:.1%}" if wr_val is not None else "ERR"

        line = col_fmt.format(
            ind=f"{ind} {marker}",
            val=str(row["param_value"]),
            sharpe=sharpe_str,
            ret=ret_str,
            dd=dd_str,
            trades=str(trades_val),
            wr=wr_str,
        )
        print(line)
        logger.info(line)

    print("─" * 80)


# ============================================================
# MR 参数敏感性
# ============================================================

async def run_mr_sensitivity(start_date: str, end_date: str, prefetched: dict) -> dict:
    """扫描所有MR参数，返回 {param_name: [result_rows]}"""
    from app.services.mean_reversion_service import (
        run_mean_reversion_backtest,
        MeanReversionConfig,
    )

    all_results = {}
    logger.info("=" * 60)
    logger.info(f"[MR敏感性] 开始扫描，测试期 {start_date} ~ {end_date}")

    # 保存所有默认值
    defaults = {
        "RSI_ENTRY_THRESHOLD": MeanReversionConfig.RSI_ENTRY_THRESHOLD,
        "BB_ENTRY_THRESHOLD":  MeanReversionConfig.BB_ENTRY_THRESHOLD,
        "ATR_STOP_MULT":       MeanReversionConfig.ATR_STOP_MULT,
        "MAX_HOLD_DAYS":       MeanReversionConfig.MAX_HOLD_DAYS,
    }

    for param_name, grid in MR_PARAM_GRID.items():
        rows = []
        logger.info(f"[MR敏感性] 扫描参数 {param_name}，共 {len(grid['values'])} 个值")

        for val in grid["values"]:
            # 设置目标参数
            setattr(MeanReversionConfig, param_name, val)
            # 同步更新全局单例 MRC
            from app.services import mean_reversion_service as _mrsvc
            setattr(_mrsvc.MRC, param_name, val)

            try:
                result = await run_mean_reversion_backtest(
                    start_date=start_date,
                    end_date=end_date,
                    _prefetched=prefetched,
                )
                if "error" in result:
                    logger.warning(f"[MR] {param_name}={val} 回测出错: {result['error']}")
                    rows.append({"param_value": val, "error": result["error"]})
                else:
                    rows.append({
                        "param_value": val,
                        "sharpe_ratio": result.get("sharpe_ratio"),
                        "cumulative_return": result.get("cumulative_return"),
                        "max_drawdown": result.get("max_drawdown"),
                        "total_trades": result.get("total_trades"),
                        "win_rate": result.get("win_rate"),
                    })
                    logger.info(
                        f"[MR] {param_name}={val} "
                        f"Sharpe={result.get('sharpe_ratio'):.3f} "
                        f"累计={result.get('cumulative_return'):+.2%} "
                        f"回撤={result.get('max_drawdown'):.2%}"
                    )
            except Exception as e:
                logger.warning(f"[MR] {param_name}={val} 异常: {e}")
                rows.append({"param_value": val, "error": str(e)})
            finally:
                # 立即恢复默认值
                setattr(MeanReversionConfig, param_name, defaults[param_name])
                setattr(_mrsvc.MRC, param_name, defaults[param_name])

        all_results[param_name] = rows
        print_sensitivity_table(param_name, grid["label"], rows, grid["default"])

    return all_results


# ============================================================
# ED 参数敏感性
# ============================================================

async def run_ed_sensitivity(start_date: str, end_date: str, prefetched_price: dict, prefetched_fund: dict) -> dict:
    """扫描所有ED参数，返回 {param_name: [result_rows]}"""
    from app.services.event_driven_service import (
        run_event_driven_backtest,
        EventDrivenConfig,
    )

    all_results = {}
    logger.info("=" * 60)
    logger.info(f"[ED敏感性] 开始扫描，测试期 {start_date} ~ {end_date}")

    defaults = {
        "MIN_BEAT_RATE":              EventDrivenConfig.MIN_BEAT_RATE,
        "MIN_EPS_SURPRISE_PCT":       EventDrivenConfig.MIN_EPS_SURPRISE_PCT,
        "ENTRY_DAYS_BEFORE_EARNINGS": EventDrivenConfig.ENTRY_DAYS_BEFORE_EARNINGS,
        "ATR_STOP_MULT":              EventDrivenConfig.ATR_STOP_MULT,
    }

    for param_name, grid in ED_PARAM_GRID.items():
        rows = []
        logger.info(f"[ED敏感性] 扫描参数 {param_name}，共 {len(grid['values'])} 个值")

        for val in grid["values"]:
            setattr(EventDrivenConfig, param_name, val)
            from app.services import event_driven_service as _edsvc
            setattr(_edsvc.EDC, param_name, val)

            try:
                result = await run_event_driven_backtest(
                    start_date=start_date,
                    end_date=end_date,
                    _prefetched=prefetched_price,
                    _prefetched_fundamentals=prefetched_fund,
                )
                if "error" in result:
                    logger.warning(f"[ED] {param_name}={val} 回测出错: {result['error']}")
                    rows.append({"param_value": val, "error": result["error"]})
                else:
                    rows.append({
                        "param_value": val,
                        "sharpe_ratio": result.get("sharpe_ratio"),
                        "cumulative_return": result.get("cumulative_return"),
                        "max_drawdown": result.get("max_drawdown"),
                        "total_trades": result.get("total_trades"),
                        "win_rate": result.get("win_rate"),
                    })
                    logger.info(
                        f"[ED] {param_name}={val} "
                        f"Sharpe={result.get('sharpe_ratio'):.3f} "
                        f"累计={result.get('cumulative_return'):+.2%} "
                        f"回撤={result.get('max_drawdown'):.2%}"
                    )
            except Exception as e:
                logger.warning(f"[ED] {param_name}={val} 异常: {e}")
                rows.append({"param_value": val, "error": str(e)})
            finally:
                setattr(EventDrivenConfig, param_name, defaults[param_name])
                setattr(_edsvc.EDC, param_name, defaults[param_name])

        all_results[param_name] = rows
        print_sensitivity_table(param_name, grid["label"], rows, grid["default"])

    return all_results


# ============================================================
# V4 参数敏感性
# ============================================================

async def run_v4_sensitivity(start_date: str, end_date: str, prefetched: dict) -> dict:
    """扫描V4 top_n 和 BACKTEST_STOP_MULT，返回 {param_name: [result_rows]}"""
    from app.services.rotation_service import run_rotation_backtest
    from app.config.rotation_watchlist import RotationConfig

    all_results = {}
    logger.info("=" * 60)
    logger.info(f"[V4敏感性] 开始扫描，测试期 {start_date} ~ {end_date}")

    default_stop = RotationConfig.BACKTEST_STOP_MULT

    for param_name, grid in V4_PARAM_GRID.items():
        rows = []
        logger.info(f"[V4敏感性] 扫描参数 {param_name}，共 {len(grid['values'])} 个值")

        for val in grid["values"]:
            # top_n 直接传参数；BACKTEST_STOP_MULT 修改类属性
            kwargs = {}
            if param_name == "top_n":
                kwargs["top_n"] = val
            else:
                RotationConfig.BACKTEST_STOP_MULT = val

            try:
                result = await run_rotation_backtest(
                    start_date=start_date,
                    end_date=end_date,
                    _prefetched=prefetched,
                    **kwargs,
                )
                if "error" in result:
                    logger.warning(f"[V4] {param_name}={val} 回测出错: {result['error']}")
                    rows.append({"param_value": val, "error": result["error"]})
                else:
                    rows.append({
                        "param_value": val,
                        "sharpe_ratio": result.get("sharpe_ratio"),
                        "cumulative_return": result.get("cumulative_return"),
                        "max_drawdown": result.get("max_drawdown"),
                        "total_trades": result.get("weeks"),   # V4 用周数表示交易次数
                        "win_rate": result.get("win_rate"),
                    })
                    logger.info(
                        f"[V4] {param_name}={val} "
                        f"Sharpe={result.get('sharpe_ratio'):.3f} "
                        f"累计={result.get('cumulative_return'):+.2%} "
                        f"回撤={result.get('max_drawdown'):.2%}"
                    )
            except Exception as e:
                logger.warning(f"[V4] {param_name}={val} 异常: {e}")
                rows.append({"param_value": val, "error": str(e)})
            finally:
                if param_name == "BACKTEST_STOP_MULT":
                    RotationConfig.BACKTEST_STOP_MULT = default_stop

        all_results[param_name] = rows
        print_sensitivity_table(param_name, grid["label"], rows, grid["default"])

    return all_results


# ============================================================
# 数据预取
# ============================================================

async def prefetch_all_data(start_date: str, end_date: str, strategies: list = None) -> dict:
    """一次性预取所需策略数据，避免重复API调用。strategies 控制预取范围。"""
    if strategies is None:
        strategies = ["mr", "ed", "v4"]
    logger.info(f"[数据预取] 开始，测试期 {start_date} ~ {end_date}，策略={strategies}")
    t0 = time.time()
    data = {}

    # V4 / MR 都需要 price histories（V4 prefetch 覆盖所有股票）
    need_price = any(s in strategies for s in ["v4", "mr"])
    if need_price:
        try:
            from app.services.rotation_service import _fetch_backtest_data
            logger.info("[数据预取] 获取V4/MR价格数据...")
            v4_data = await _fetch_backtest_data(start_date, end_date)
            data["v4"] = v4_data
            data["mr"] = v4_data.get("histories", {})
            logger.info(f"[数据预取] 价格数据完成，{len(data['mr'])}只股票")
        except Exception as e:
            logger.error(f"[数据预取] 价格数据失败: {e}")
            data["v4"] = {}
            data["mr"] = {}
    else:
        data["v4"] = {}
        data["mr"] = {}

    # ED 财报数据（只在测试 ED 时才拉取，耗时较长）
    if "ed" in strategies:
        try:
            from app.services.event_driven_service import _fetch_ed_data
            logger.info("[数据预取] 获取ED数据（价格+财报）...")
            ed_histories, ed_fundamentals = await _fetch_ed_data(start_date, end_date)
            data["ed_price"] = ed_histories
            data["ed_fund"] = ed_fundamentals
            logger.info(f"[数据预取] ED数据完成，价格{len(ed_histories)}只，财报{len(ed_fundamentals)}只")
        except Exception as e:
            logger.error(f"[数据预取] ED数据失败: {e}")
            data["ed_price"] = {}
            data["ed_fund"] = {}
    else:
        data["ed_price"] = {}
        data["ed_fund"] = {}

    elapsed = time.time() - t0
    logger.info(f"[数据预取] 全部完成，耗时 {elapsed:.0f}s")
    return data


# ============================================================
# 主函数
# ============================================================

async def main():
    parser = argparse.ArgumentParser(description="StockQueen 参数敏感性分析")
    parser.add_argument(
        "--strategy", choices=["mr", "ed", "v4", "all"], default="all",
        help="测试策略：mr / ed / v4 / all（默认all）"
    )
    parser.add_argument("--start", default="2022-01-01", help="回测开始日期（默认2022-01-01）")
    parser.add_argument("--end",   default="2024-12-31", help="回测结束日期（默认2024-12-31）")
    args = parser.parse_args()

    strategies = (
        ["mr", "ed", "v4"] if args.strategy == "all"
        else [args.strategy]
    )

    print("=" * 80)
    print("  StockQueen 参数敏感性分析")
    print(f"  测试期：{args.start} ~ {args.end}")
    print(f"  策略：{', '.join(strategies)}")
    print("=" * 80)
    logger.info(f"参数敏感性分析启动: 策略={strategies} 期间={args.start}~{args.end}")

    t_total = time.time()

    # 数据预取（只预取需要的策略数据）
    prefetched = await prefetch_all_data(args.start, args.end, strategies=strategies)

    full_results = {
        "meta": {
            "timestamp": TIMESTAMP,
            "start_date": args.start,
            "end_date": args.end,
            "strategies": strategies,
        },
        "results": {},
    }

    # MR
    if "mr" in strategies:
        print("\n" + "=" * 80)
        print("  均值回归 (MR) 参数敏感性")
        print("=" * 80)
        mr_data = prefetched.get("mr", {})
        mr_results = await run_mr_sensitivity(args.start, args.end, mr_data if mr_data else None)
        full_results["results"]["mr"] = mr_results

    # ED
    if "ed" in strategies:
        print("\n" + "=" * 80)
        print("  事件驱动 (ED) 参数敏感性")
        print("=" * 80)
        ed_results = await run_ed_sensitivity(
            args.start, args.end,
            prefetched.get("ed_price", None) or None,
            prefetched.get("ed_fund", None) or None,
        )
        full_results["results"]["ed"] = ed_results

    # V4
    if "v4" in strategies:
        print("\n" + "=" * 80)
        print("  V4轮动趋势 参数敏感性")
        print("=" * 80)
        v4_data = prefetched.get("v4", {})
        v4_results = await run_v4_sensitivity(args.start, args.end, v4_data if v4_data else None)
        full_results["results"]["v4"] = v4_results

    # 保存结果
    out_file = RESULTS_DIR / f"sensitivity_{TIMESTAMP}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(full_results, f, indent=2, ensure_ascii=False, default=str)

    elapsed = time.time() - t_total
    print(f"\n{'='*80}")
    print(f"  敏感性分析完成，耗时 {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  结果已保存: {out_file}")
    print(f"  日志文件:   {log_file}")
    print("=" * 80)
    logger.info(f"分析完成，结果保存至 {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
