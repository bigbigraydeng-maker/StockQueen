"""
StockQueen - Mean Reversion Service
均值回归策略：在价格超卖时买入，均值修复后卖出。

策略逻辑：
  - 体制为 bull / choppy 时激活
  - 入场：RSI < 32 + 布林带下轨 + 放量确认
  - 出场：RSI > 55 或 回到布林带中轨 或 时间止损(8天) 或 ATR硬止损
  - 最大同时持仓：3只
  - 与V4趋势策略互补，在震荡市中补充收益

生产隔离原则：
  - 本服务完全独立，不修改 rotation_service.py
  - 通过 portfolio_manager.py 统一调度资金分配
  - 所有回测操作通过 scripts/test_mean_reversion.py 执行
"""

import logging
import numpy as np
from typing import Optional
from datetime import datetime, timedelta


def _to_dt(d) -> datetime:
    """统一处理 str / Timestamp / datetime → datetime"""
    if isinstance(d, datetime):
        return d
    return datetime.strptime(str(d)[:10], "%Y-%m-%d")

from app.services.alphavantage_client import get_av_client
from app.services.multi_factor_scorer import (
    _compute_rsi,
    _compute_bbands,
    _compute_obv_trend,
)
from app.services.rotation_service import _compute_atr
from app.config.sp100_watchlist import SP100_POOL, SP100_TICKERS, get_sp100_ticker_info

logger = logging.getLogger(__name__)

# ============================================================
# 策略参数配置
# ============================================================

class MeanReversionConfig:
    # 入场信号阈值
    RSI_ENTRY_THRESHOLD: float = 28.0       # 收紧：更深度超卖才入场（原32）
    BB_ENTRY_THRESHOLD: float = 0.05        # 收紧：必须更接近下轨（原0.15）
    VOLUME_FACTOR: float = 1.5              # 收紧：放量要求更高（原1.3）

    # 出场信号阈值
    RSI_EXIT_THRESHOLD: float = 55.0        # RSI 高于此值出场（回到中性区）
    BB_EXIT_THRESHOLD: float = 0.50         # 布林带中轨出场（均值修复完成）

    # 风险控制
    MAX_HOLD_DAYS: int = 8                  # 最大持仓天数（时间止损）
    ATR_STOP_MULT: float = 2.0             # 硬止损：入场价 - 2×ATR
    MAX_POSITIONS: int = 3                  # 最大同时持仓数
    MAX_SECTOR_CONCENTRATION: int = 2       # 同板块最多持有N只

    # 体制过滤：只在 bull 时运行
    # strong_bull：趋势太强，超卖反弹空间小，等待真正回调
    # choppy / bear：趋势不明或下跌，接飞刀风险极高
    ACTIVE_REGIMES: set = frozenset({"bull"})

    # 回测参数
    BACKTEST_SLIPPAGE: float = 0.001        # 单边滑点 0.1%
    BACKTEST_MIN_AVG_VOL: int = 1_000_000  # 最低20日均成交量（比V4更严格）
    LOOKBACK_DAYS: int = 120               # 数据回看天数

MRC = MeanReversionConfig()


# ============================================================
# 入场信号检测
# ============================================================

def detect_entry_signal(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    ticker: str = "",
) -> dict:
    """
    检测均值回归入场信号。
    返回 {signal: bool, rsi, bb_pos, vol_ratio, atr, reason}
    """
    result = {
        "signal": False,
        "rsi": 50.0,
        "bb_pos": 0.5,
        "vol_ratio": 1.0,
        "atr": 0.0,
        "stop_price": 0.0,
        "reason": "",
    }

    if len(closes) < 30:
        result["reason"] = "数据不足"
        return result

    # --- RSI ---
    rsi = _compute_rsi(closes)
    result["rsi"] = rsi

    # --- 布林带位置 ---
    bb = _compute_bbands(closes)
    result["bb_pos"] = bb["position"]

    # --- 成交量比率（vs 20日均量）---
    if len(volumes) >= 21:
        avg_vol_20 = float(np.mean(volumes[-21:-1]))
        vol_ratio = float(volumes[-1] / avg_vol_20) if avg_vol_20 > 0 else 0.0
    else:
        vol_ratio = 1.0
    result["vol_ratio"] = vol_ratio

    # --- ATR（用于止损计算）---
    atr = _compute_atr(highs, lows, closes)
    result["atr"] = atr
    result["stop_price"] = closes[-1] - MRC.ATR_STOP_MULT * atr

    # --- 信号判断（三个条件全满足）---
    cond_rsi = rsi < MRC.RSI_ENTRY_THRESHOLD
    cond_bb = bb["position"] < MRC.BB_ENTRY_THRESHOLD
    cond_vol = vol_ratio >= MRC.VOLUME_FACTOR

    if cond_rsi and cond_bb and cond_vol:
        result["signal"] = True
        result["reason"] = f"RSI={rsi:.1f} BB={bb['position']:.2f} VolRatio={vol_ratio:.2f}"
        logger.info(f"[MR] 入场信号 {ticker}: {result['reason']}")
    else:
        missing = []
        if not cond_rsi:
            missing.append(f"RSI={rsi:.1f}(需<{MRC.RSI_ENTRY_THRESHOLD})")
        if not cond_bb:
            missing.append(f"BB={bb['position']:.2f}(需<{MRC.BB_ENTRY_THRESHOLD})")
        if not cond_vol:
            missing.append(f"Vol={vol_ratio:.2f}(需>{MRC.VOLUME_FACTOR})")
        result["reason"] = "条件不足: " + " | ".join(missing)

    return result


def detect_exit_signal(
    closes: np.ndarray,
    entry_price: float,
    stop_price: float,
    hold_days: int,
    ticker: str = "",
) -> dict:
    """
    检测均值回归出场信号。
    返回 {signal: bool, reason, exit_type}
    """
    result = {"signal": False, "reason": "", "exit_type": ""}

    if len(closes) < 20:
        return result

    rsi = _compute_rsi(closes)
    bb = _compute_bbands(closes)
    current_price = closes[-1]

    # 出场条件（优先级顺序）
    if current_price <= stop_price:
        result.update({"signal": True, "exit_type": "hard_stop",
                        "reason": f"ATR硬止损触发 price={current_price:.2f} stop={stop_price:.2f}"})
    elif hold_days >= MRC.MAX_HOLD_DAYS:
        result.update({"signal": True, "exit_type": "time_stop",
                        "reason": f"时间止损 持仓{hold_days}天"})
    elif rsi > MRC.RSI_EXIT_THRESHOLD:
        result.update({"signal": True, "exit_type": "rsi_exit",
                        "reason": f"RSI回升={rsi:.1f} > {MRC.RSI_EXIT_THRESHOLD}"})
    elif bb["position"] >= MRC.BB_EXIT_THRESHOLD:
        result.update({"signal": True, "exit_type": "bb_exit",
                        "reason": f"布林带中轨修复 pos={bb['position']:.2f}"})

    if result["signal"]:
        pnl_pct = (current_price - entry_price) / entry_price * 100
        result["pnl_pct"] = pnl_pct
        logger.info(f"[MR] 出场信号 {ticker}: {result['reason']} | PnL={pnl_pct:+.1f}%")

    return result


# ============================================================
# 回测引擎（日级别，独立于V4）
# ============================================================

async def run_mean_reversion_backtest(
    start_date: str,
    end_date: str,
    regime_series: Optional[dict] = None,   # {date_str: regime} 可由portfolio_manager传入
    capital_ratio: float = 1.0,             # 分配给本策略的资金比例（portfolio_manager调用时传入）
    _prefetched: Optional[dict] = None,
) -> dict:
    """
    均值回归策略回测引擎（日级别）。

    Args:
        start_date: 回测开始日期 "YYYY-MM-DD"
        end_date: 回测结束日期 "YYYY-MM-DD"
        regime_series: 可选，由外部传入的体制序列（组合回测时使用）
        capital_ratio: 分配给本策略的资金比例
        _prefetched: 预取的市场数据（避免重复API调用）

    Returns:
        回测结果字典，格式与V4保持一致，便于portfolio_manager整合
    """
    logger.info(f"[MR Backtest] 开始 {start_date} → {end_date} | 资金比例={capital_ratio:.0%}")

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt   = datetime.strptime(end_date,   "%Y-%m-%d")

    # --- 数据获取 ---
    if _prefetched:
        histories = _prefetched
        logger.info(f"[MR Backtest] 使用预取数据，共 {len(histories)} 只股票")
    else:
        histories = await _fetch_mr_data(start_date, end_date)

    if not histories:
        logger.error("[MR Backtest] 数据获取失败，无法回测")
        return {"error": "数据获取失败"}

    # --- 构建日期序列 ---
    # 使用SPY的日期序列作为基准
    spy_dates = None
    for ticker, h in histories.items():
        if h and "dates" in h:
            spy_dates = [str(d)[:10] for d in h["dates"]
                         if start_dt <= _to_dt(d) <= end_dt]
            break

    if not spy_dates:
        logger.error("[MR Backtest] 无法构建日期序列")
        return {"error": "日期序列构建失败"}

    spy_dates = sorted(spy_dates)
    logger.info(f"[MR Backtest] 回测日期序列: {spy_dates[0]} → {spy_dates[-1]} ({len(spy_dates)}天)")

    # --- 回测主循环 ---
    equity = 1.0
    equity_curve = [1.0]
    daily_returns = []
    trades = []
    open_positions = {}   # {ticker: {entry_price, stop_price, entry_date, hold_days}}

    total_trades = 0
    winning_trades = 0
    regime_skips = 0

    for day_idx, date_str in enumerate(spy_dates):
        date_dt = _to_dt(date_str)

        # 体制检查
        regime = _get_regime_for_date(date_str, regime_series, histories)
        if regime not in MRC.ACTIVE_REGIMES:
            regime_skips += 1
            # 持仓照常管理，只是不开新仓
            equity_curve.append(equity)
            daily_returns.append(0.0)
            _update_positions_daily(open_positions, histories, date_str, trades)
            continue

        # 1. 检查现有持仓的出场信号
        positions_to_close = []
        for ticker, pos in open_positions.items():
            h = histories.get(ticker)
            if not h:
                continue
            closes_up_to = _get_closes_up_to(h, date_str)
            if closes_up_to is None or len(closes_up_to) < 20:
                continue

            pos["hold_days"] += 1
            exit_sig = detect_exit_signal(
                closes_up_to,
                pos["entry_price"],
                pos["stop_price"],
                pos["hold_days"],
                ticker=ticker,
            )
            if exit_sig["signal"]:
                exit_price = closes_up_to[-1] * (1 - MRC.BACKTEST_SLIPPAGE)
                pnl = (exit_price - pos["entry_price"]) / pos["entry_price"]
                equity *= (1 + pnl * pos["weight"])
                positions_to_close.append(ticker)
                total_trades += 1
                if pnl > 0:
                    winning_trades += 1
                trades.append({
                    "type": "exit",
                    "ticker": ticker,
                    "date": date_str,
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_price,
                    "pnl_pct": pnl * 100,
                    "hold_days": pos["hold_days"],
                    "exit_type": exit_sig["exit_type"],
                    "regime": regime,
                })
                logger.debug(f"[MR] 平仓 {ticker} {date_str} PnL={pnl:+.2%} {exit_sig['exit_type']}")

        for ticker in positions_to_close:
            del open_positions[ticker]

        # 2. 扫描新的入场信号（仓位未满时）
        if len(open_positions) < MRC.MAX_POSITIONS:
            slots_available = MRC.MAX_POSITIONS - len(open_positions)
            candidates = _scan_entry_signals(histories, date_str, open_positions, slots_available)

            for candidate in candidates[:slots_available]:
                ticker = candidate["ticker"]
                entry_price = candidate["entry_price"] * (1 + MRC.BACKTEST_SLIPPAGE)
                weight = 1.0 / MRC.MAX_POSITIONS   # 等权分配
                open_positions[ticker] = {
                    "entry_price": entry_price,
                    "stop_price": candidate["stop_price"],
                    "entry_date": date_str,
                    "hold_days": 0,
                    "weight": weight,
                }
                trades.append({
                    "type": "entry",
                    "ticker": ticker,
                    "date": date_str,
                    "entry_price": entry_price,
                    "rsi": candidate["rsi"],
                    "bb_pos": candidate["bb_pos"],
                    "regime": regime,
                })
                logger.debug(f"[MR] 建仓 {ticker} {date_str} RSI={candidate['rsi']:.1f}")

        equity_curve.append(equity)
        daily_returns.append((equity_curve[-1] / equity_curve[-2]) - 1 if len(equity_curve) > 1 else 0.0)

    # --- 统计指标 ---
    total_days = len(spy_dates)
    cumulative_return = equity - 1.0
    annualized_return = (equity ** (252 / max(total_days, 1))) - 1 if total_days > 0 else 0.0

    vol = float(np.std(daily_returns) * np.sqrt(252)) if len(daily_returns) > 1 else 0.0
    sharpe = annualized_return / vol if vol > 0 else 0.0
    max_dd = _compute_max_drawdown(equity_curve)
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

    result = {
        "strategy": "mean_reversion",
        "period": f"{start_date} → {end_date}",
        "trading_days": total_days,
        "cumulative_return": round(cumulative_return, 4),
        "annualized_return": round(annualized_return, 4),
        "annualized_vol": round(vol, 4),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown": round(max_dd, 4),
        "total_trades": total_trades,
        "win_rate": round(win_rate, 4),
        "regime_skip_days": regime_skips,
        "equity_curve": equity_curve,
        "trades": trades,
        "config": {
            "rsi_entry": MRC.RSI_ENTRY_THRESHOLD,
            "rsi_exit": MRC.RSI_EXIT_THRESHOLD,
            "bb_entry": MRC.BB_ENTRY_THRESHOLD,
            "max_hold_days": MRC.MAX_HOLD_DAYS,
            "atr_stop_mult": MRC.ATR_STOP_MULT,
            "max_positions": MRC.MAX_POSITIONS,
            "active_regimes": list(MRC.ACTIVE_REGIMES),
        },
    }

    logger.info(
        f"[MR Backtest] 完成 | 累计={cumulative_return:+.2%} "
        f"年化={annualized_return:+.2%} 夏普={sharpe:.2f} "
        f"回撤={max_dd:.2%} 胜率={win_rate:.1%} 交易{total_trades}次"
    )
    return result


# ============================================================
# 实时信号扫描（供 portfolio_manager 调用）
# ============================================================

async def scan_live_signals(regime: str) -> list[dict]:
    """
    扫描实时均值回归信号。
    供 portfolio_manager 每日盘后调用。

    Returns:
        符合条件的入场候选列表，按信号强度排序
    """
    if regime not in MRC.ACTIVE_REGIMES:
        logger.info(f"[MR Live] 当前体制 {regime} 不在激活范围，跳过扫描")
        return []

    logger.info(f"[MR Live] 开始扫描，体制={regime}，候选池={len(SP100_TICKERS)}只")
    av = get_av_client()
    candidates = []

    for item in SP100_POOL:
        ticker = item["ticker"]
        try:
            h = await av.get_history_arrays(ticker, days=MRC.LOOKBACK_DAYS)
            if not h or len(h.get("close", [])) < 30:
                continue

            # 最低流动性过滤
            avg_vol = float(np.mean(h["volume"][-20:])) if len(h["volume"]) >= 20 else 0
            if avg_vol < MRC.BACKTEST_MIN_AVG_VOL:
                continue

            sig = detect_entry_signal(
                np.array(h["close"]),
                np.array(h["high"]),
                np.array(h["low"]),
                np.array(h["volume"]),
                ticker=ticker,
            )

            if sig["signal"]:
                candidates.append({
                    "ticker": ticker,
                    "name": item["name"],
                    "sector": item["sector"],
                    "current_price": float(h["close"][-1]),
                    "rsi": sig["rsi"],
                    "bb_pos": sig["bb_pos"],
                    "vol_ratio": sig["vol_ratio"],
                    "atr": sig["atr"],
                    "stop_price": sig["stop_price"],
                    "signal_strength": _compute_signal_strength(sig),
                    "reason": sig["reason"],
                })

        except Exception as e:
            logger.warning(f"[MR Live] {ticker} 扫描异常: {e}")

    # 按信号强度排序
    candidates.sort(key=lambda x: x["signal_strength"], reverse=True)
    logger.info(f"[MR Live] 扫描完成，发现 {len(candidates)} 个候选信号")
    return candidates


# ============================================================
# 内部工具函数
# ============================================================

async def _fetch_mr_data(start_date: str, end_date: str) -> dict:
    """获取均值回归策略所需的市场数据。
    固定拉取1800天（约5年）历史，确保覆盖任意回测区间。
    """
    av = get_av_client()
    days_needed = 3000  # 覆盖2018至今（约8年历史）

    # 额外拉取 SPY/QQQ 用于体制识别
    REGIME_TICKERS = ["SPY", "QQQ"]
    all_tickers = REGIME_TICKERS + [t for t in SP100_TICKERS if t not in REGIME_TICKERS]

    logger.info(f"[MR] 开始获取数据，共 {len(all_tickers)} 只股票（含SPY/QQQ体制识别），拉取 {days_needed} 天历史")
    histories = {}
    failed = []

    for ticker in all_tickers:
        try:
            h = await av.get_history_arrays(ticker, days=days_needed)
            if h and len(h.get("close", [])) >= 30:
                histories[ticker] = h
            else:
                failed.append(ticker)
        except Exception as e:
            logger.warning(f"[MR] 数据获取失败 {ticker}: {e}")
            failed.append(ticker)

    logger.info(f"[MR] 数据获取完成: {len(histories)}只成功, {len(failed)}只失败")
    if failed:
        logger.debug(f"[MR] 失败列表: {failed}")
    return histories


def _get_closes_up_to(h: dict, date_str: str) -> Optional[np.ndarray]:
    """获取截止到指定日期的收盘价序列。"""
    if not h or "dates" not in h or "close" not in h:
        return None
    dates = [str(d)[:10] for d in h["dates"]]  # 统一转字符串
    closes = h["close"]
    idx = None
    for i, d in enumerate(dates):
        if d == date_str:
            idx = i
            break
    if idx is None:
        # 找最近的日期
        for i, d in enumerate(dates):
            if d <= date_str:
                idx = i
    if idx is None or idx < 20:
        return None
    return np.array(closes[:idx + 1])


def _get_regime_for_date(date_str: str, regime_series: Optional[dict], histories: dict) -> str:
    """获取指定日期的体制状态。"""
    if regime_series and date_str in regime_series:
        return regime_series[date_str]
    # 简化版体制识别（用SPY MA50）
    spy_h = histories.get("SPY") or histories.get("QQQ")
    if not spy_h:
        return "bull"   # 默认 bull
    closes = _get_closes_up_to(spy_h, date_str)
    if closes is None or len(closes) < 50:
        return "bull"
    spy_cur = closes[-1]
    ma50 = float(np.mean(closes[-50:]))
    ma20 = float(np.mean(closes[-20:]))
    if spy_cur > ma50 * 1.02 and spy_cur > ma20:
        return "strong_bull"
    elif spy_cur > ma50:
        return "bull"
    elif spy_cur > ma50 * 0.97:
        return "choppy"
    else:
        return "bear"


def _scan_entry_signals(
    histories: dict,
    date_str: str,
    open_positions: dict,
    slots: int,
) -> list:
    """扫描当日所有候选股的入场信号。"""
    candidates = []
    sector_count = {}

    for item in SP100_POOL:
        ticker = item["ticker"]
        if ticker in open_positions:
            continue

        # 板块集中度控制
        sector = item["sector"]
        if sector_count.get(sector, 0) >= MRC.MAX_SECTOR_CONCENTRATION:
            continue

        h = histories.get(ticker)
        if not h:
            continue

        closes = _get_closes_up_to(h, date_str)
        if closes is None or len(closes) < 30:
            continue

        # 最低流动性过滤（回测期间）
        vols = h.get("volume", [])
        if len(vols) >= 20:
            avg_vol = float(np.mean(np.array(vols)[-20:]))
            if avg_vol < MRC.BACKTEST_MIN_AVG_VOL:
                continue

        # 构建OHLCV数组
        idx_map = {str(d)[:10]: i for i, d in enumerate(h["dates"])}
        idx = idx_map.get(date_str)
        if idx is None:
            continue

        closes_arr = np.array(h["close"][:idx + 1])
        highs_arr  = np.array(h["high"][:idx + 1])
        lows_arr   = np.array(h["low"][:idx + 1])
        vols_arr   = np.array(h["volume"][:idx + 1])

        sig = detect_entry_signal(closes_arr, highs_arr, lows_arr, vols_arr, ticker=ticker)
        if sig["signal"]:
            candidates.append({
                "ticker": ticker,
                "entry_price": float(closes_arr[-1]),
                "stop_price": sig["stop_price"],
                "rsi": sig["rsi"],
                "bb_pos": sig["bb_pos"],
                "signal_strength": _compute_signal_strength(sig),
            })
            sector_count[sector] = sector_count.get(sector, 0) + 1

    # 按信号强度排序，取最强的
    candidates.sort(key=lambda x: x["signal_strength"], reverse=True)
    return candidates[:slots]


def _update_positions_daily(open_positions: dict, histories: dict, date_str: str, trades: list):
    """非激活体制日，持仓照常更新 hold_days。"""
    for ticker, pos in open_positions.items():
        pos["hold_days"] += 1


def _compute_signal_strength(sig: dict) -> float:
    """
    计算信号强度评分（0-1），用于候选股排序。
    RSI越低 + 布林带位置越低 = 信号越强。
    """
    rsi_score = max(0, (MRC.RSI_ENTRY_THRESHOLD - sig["rsi"]) / MRC.RSI_ENTRY_THRESHOLD)
    bb_score  = max(0, (MRC.BB_ENTRY_THRESHOLD - sig["bb_pos"]) / MRC.BB_ENTRY_THRESHOLD)
    vol_score = min(1.0, (sig["vol_ratio"] - MRC.VOLUME_FACTOR) / 2.0)
    return rsi_score * 0.4 + bb_score * 0.4 + vol_score * 0.2


def _compute_max_drawdown(equity_curve: list) -> float:
    """计算最大回撤。"""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return max_dd
