"""
StockQueen - 2026 Live OOS 追踪器
==================================
用 W5 锁定参数（V4: TOP_N=3 HB=0, MR: RSI=28）对 2026-01-02 至今做模拟回测，
作为"W6 实时预览"。每周一通过 GHA 自动更新，结果写入 Supabase live_oos_tracking。

注意：
  - 交易天数 < 100 时 Sharpe 置信区间极宽（±2+），仅供参考
  - 参数已锁定，不做搜索，直接用 WF 验证后的最优值
  - 数据源：Massive API（实时价格）

使用方法：
    python scripts/live_oos_2026.py                    # 追踪至今日
    python scripts/live_oos_2026.py --end 2026-03-21   # 追踪至指定日期
    python scripts/live_oos_2026.py --no-upload        # 不写 Supabase（本地测试）
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

RESULTS_DIR = Path(__file__).parent / "stress_test_results"
RESULTS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("app.services.alphavantage_client").setLevel(logging.WARNING)
logging.getLogger("app.services.rotation_service").setLevel(logging.WARNING)
logging.getLogger("app.services.mean_reversion_service").setLevel(logging.WARNING)

logger = logging.getLogger("live_oos_2026")

# ============================================================
# 锁定参数（来自 W5 Walk-Forward 验证，GHA #23423631911）
# ============================================================
OOS_START   = "2026-01-02"   # 2026 首个交易日
LOCKED_V4_TOP_N = 3
LOCKED_V4_HB    = 0.0
LOCKED_MR_RSI   = 28
STRATEGY        = "v4mr"

# 组合权重（与 WF 一致）
V4_WEIGHT = 2 / 3
MR_WEIGHT = 1 / 3


def _equity_to_stats(equity_curve: list) -> dict:
    if len(equity_curve) < 2:
        return {"sharpe": 0.0, "ytd_return": 0.0, "max_drawdown": 0.0}
    daily_returns = [
        (equity_curve[i] / equity_curve[i - 1]) - 1
        for i in range(1, len(equity_curve))
    ]
    n = len(daily_returns)
    cum_ret = equity_curve[-1] - 1.0
    vol = float(np.std(daily_returns) * np.sqrt(252)) if n > 1 else 0.0
    ann_ret = (equity_curve[-1] ** (252 / max(n, 1))) - 1
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
        "sharpe": round(sharpe, 3),
        "ytd_return": round(cum_ret, 4),
        "max_drawdown": round(max_dd, 4),
        "trading_days": n,
    }


async def run_live_oos(end_date: str, upload: bool = True):
    logger.info(f"[Live OOS] 运行 {OOS_START} → {end_date}  (V4 TOP_N={LOCKED_V4_TOP_N}, MR RSI={LOCKED_MR_RSI})")

    # ---- 数据预取 ----
    logger.info("[数据预取] 拉取 2025-10-01 ~ {end_date} 价格数据...")
    from app.services.rotation_service import _fetch_backtest_data, run_rotation_backtest
    from app.services.mean_reversion_service import (
        run_mean_reversion_backtest,
        MeanReversionConfig,
    )
    import app.services.mean_reversion_service as _mrsvc

    # 多拉一个月做热身期（均线等指标需要历史数据）
    data_start = "2025-10-01"
    prefetched = await _fetch_backtest_data(data_start, end_date)
    logger.info(f"[数据预取] 完成: {len(prefetched.get('histories', {}))} 只")

    # ---- PIT Universe（2026 年初快照）----
    pit_filter = None
    try:
        from app.services.universe_service import UniverseService
        pit_filter = await UniverseService().get_pit_universe(2026)
        logger.info(f"[PIT] 2026 宇宙快照: {len(pit_filter)} 只")
    except Exception as e:
        logger.warning(f"[PIT] 快照获取失败，不过滤: {e}")

    # ---- V4 OOS ----
    logger.info("[V4] 运行 OOS 回测...")
    v4_result = await run_rotation_backtest(
        start_date=OOS_START,
        end_date=end_date,
        top_n=LOCKED_V4_TOP_N,
        holding_bonus=LOCKED_V4_HB,
        _prefetched=prefetched,
        universe_filter=pit_filter,
    )
    v4_sharpe = v4_result.get("sharpe_ratio", 0.0) if "error" not in v4_result else 0.0
    v4_curve  = v4_result.get("equity_curve", [])
    if v4_curve and isinstance(v4_curve[0], dict):
        v4_curve = [e.get("portfolio", 1.0) for e in v4_curve]
    logger.info(f"[V4] Sharpe={v4_sharpe:.3f}  累计={v4_result.get('cumulative_return', 0):+.2%}")

    # ---- MR OOS ----
    logger.info("[MR] 运行 OOS 回测...")
    mr_prefetched = prefetched.get("histories", {})
    default_rsi = MeanReversionConfig.RSI_ENTRY_THRESHOLD
    MeanReversionConfig.RSI_ENTRY_THRESHOLD = LOCKED_MR_RSI
    _mrsvc.MRC.RSI_ENTRY_THRESHOLD = LOCKED_MR_RSI
    try:
        mr_result = await run_mean_reversion_backtest(
            start_date=OOS_START,
            end_date=end_date,
            _prefetched=mr_prefetched,
        )
    finally:
        MeanReversionConfig.RSI_ENTRY_THRESHOLD = default_rsi
        _mrsvc.MRC.RSI_ENTRY_THRESHOLD = default_rsi
    mr_sharpe = mr_result.get("sharpe_ratio", 0.0) if "error" not in mr_result else 0.0
    mr_curve  = mr_result.get("equity_curve", []) if "error" not in mr_result else []
    logger.info(f"[MR] Sharpe={mr_sharpe:.3f}  累计={mr_result.get('cumulative_return', 0):+.2%}")

    # ---- 组合 Portfolio ----
    valid_curves = {}
    if v4_curve:
        valid_curves["v4"] = v4_curve
    if mr_curve:
        valid_curves["mr"] = mr_curve

    if len(valid_curves) >= 2:
        min_len = min(len(c) for c in valid_curves.values())
        weights = {"v4": V4_WEIGHT, "mr": MR_WEIGHT}
        combined = [
            sum(weights[k] * valid_curves[k][i] for k in valid_curves)
            for i in range(min_len)
        ]
        port_stats = _equity_to_stats(combined)
    elif len(valid_curves) == 1:
        only_curve = list(valid_curves.values())[0]
        combined   = only_curve
        port_stats = _equity_to_stats(combined)
    else:
        combined   = [1.0]
        port_stats = {"sharpe": 0.0, "ytd_return": 0.0, "max_drawdown": 0.0, "trading_days": 0}

    logger.info(
        f"[Portfolio] Sharpe={port_stats['sharpe']:.3f}  "
        f"YTD={port_stats['ytd_return']:+.2%}  "
        f"MaxDD={port_stats['max_drawdown']:.2%}  "
        f"Days={port_stats.get('trading_days', 0)}"
    )

    # ---- SPY YTD ----
    spy_return = None
    try:
        spy_data = prefetched.get("histories", {}).get("SPY", [])
        if spy_data:
            # 找 OOS_START 之后的第一个价格
            oos_prices = [
                d for d in spy_data
                if d.get("date", "") >= OOS_START and d.get("date", "") <= end_date
            ]
            if len(oos_prices) >= 2:
                spy_return = round(oos_prices[-1]["close"] / oos_prices[0]["open"] - 1, 4)
    except Exception as e:
        logger.warning(f"[SPY] 计算失败: {e}")

    # ---- 保存结果 ----
    result = {
        "run_date":    str(date.today()),
        "oos_start":   OOS_START,
        "oos_end":     end_date,
        "strategy":    STRATEGY,
        "ytd_return":  port_stats["ytd_return"],
        "sharpe":      port_stats["sharpe"],
        "max_drawdown":port_stats["max_drawdown"],
        "trading_days":port_stats.get("trading_days", 0),
        "spy_return":  spy_return,
        "equity_curve": combined[:],
        "params": {
            "v4_top_n":   LOCKED_V4_TOP_N,
            "v4_hb":      LOCKED_V4_HB,
            "mr_rsi":     LOCKED_MR_RSI,
            "v4_weight":  V4_WEIGHT,
            "mr_weight":  MR_WEIGHT,
        },
        "note": (
            f"Live OOS W6-preview. Days={port_stats.get('trading_days',0)}, "
            "Sharpe unreliable < 100 days. Locked params from GHA #23423631911."
        ),
    }

    # 本地 JSON
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = RESULTS_DIR / f"live_oos_2026_{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"[保存] {out_file}")

    # Supabase upsert
    if upload:
        try:
            from app.database import get_db
            db = get_db()
            upsert_data = {k: v for k, v in result.items() if k != "equity_curve"}
            upsert_data["equity_curve"] = combined[:]
            db.table("live_oos_tracking").upsert(
                upsert_data,
                on_conflict="run_date,strategy"
            ).execute()
            logger.info("[Supabase] live_oos_tracking upsert 成功")
        except Exception as e:
            logger.error(f"[Supabase] 写入失败: {e}")

    # 打印摘要
    print("\n" + "=" * 60)
    print(f"  2026 Live OOS 追踪 ({OOS_START} → {end_date})")
    print("=" * 60)
    print(f"  Portfolio YTD:   {port_stats['ytd_return']:+.2%}")
    print(f"  Sharpe (参考):   {port_stats['sharpe']:.3f}  ⚠️ 样本量小")
    print(f"  Max Drawdown:    {port_stats['max_drawdown']:.2%}")
    print(f"  SPY YTD:         {spy_return:+.2%}" if spy_return is not None else "  SPY YTD:         N/A")
    print(f"  交易天数:         {port_stats.get('trading_days', 0)}")
    print("=" * 60)

    return result


async def main():
    parser = argparse.ArgumentParser(description="StockQueen 2026 Live OOS 追踪器")
    parser.add_argument(
        "--end",
        default=str(date.today()),
        help=f"追踪截止日期（默认：今日 {date.today()}）",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        default=False,
        help="不写入 Supabase（本地测试用）",
    )
    args = parser.parse_args()
    await run_live_oos(end_date=args.end, upload=not args.no_upload)


if __name__ == "__main__":
    asyncio.run(main())
