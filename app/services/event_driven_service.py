"""
StockQueen - Event Driven Service
事件驱动策略：在财报催化剂前建仓，利用高质量公司的持续超预期概率优势。

策略逻辑：
  - 财报发布前 3 天建仓
  - 入场条件：历史 EPS 超预期率 >= 70% + 分析师预期近期上调
  - 出场：财报发布后次日开盘平仓（不持过夜风险）
  - 全体制运行（不依赖大盘方向，收益来源为公司基本面）
  - 最大同时持仓：4 只（与 V4 / 均值回归独立核算）

生产隔离原则：
  - 本服务完全独立，不修改 rotation_service.py
  - 通过 portfolio_manager.py 统一调度资金分配
  - 所有回测操作通过 scripts/test_strategy_matrix.py 执行
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
from app.services.fmp_client import batch_get_earnings as fmp_batch_get_earnings
from app.services.multi_factor_scorer import _compute_rsi
from app.services.rotation_service import _compute_atr, _compute_ma
from app.config.sp100_watchlist import SP100_POOL, SP100_TICKERS, get_sp100_ticker_info

logger = logging.getLogger(__name__)


# ============================================================
# 策略参数配置
# ============================================================

class EventDrivenConfig:
    # 入场条件
    ENTRY_DAYS_BEFORE_EARNINGS: int = 3     # 财报前 N 天建仓
    MIN_BEAT_RATE: float = 0.60             # 历史超预期率门槛（WF验证：0.60在5个窗口全优）
    MIN_QUARTERS_DATA: int = 4              # 最少需要 N 季度历史数据
    MIN_EPS_SURPRISE_PCT: float = 0.02      # 最近一次超预期幅度 >= 2%

    # 风险控制
    ATR_STOP_MULT: float = 1.5             # 硬止损：入场价 - 1.5×ATR（财报前波动大）
    MAX_POSITIONS: int = 4                  # 最大同时持仓数
    MAX_SECTOR_CONCENTRATION: int = 2       # 同板块最多持有 N 只

    # 回测参数
    BACKTEST_SLIPPAGE: float = 0.001        # 单边滑点 0.1%
    BACKTEST_MIN_AVG_VOL: int = 2_000_000  # 事件驱动需要更高流动性
    LOOKBACK_DAYS: int = 120

    # WF验证：bull/strong_bull时ED失效（2021 OOS=-0.99），只在熊市/震荡期开启
    ACTIVE_REGIMES: set = frozenset({"choppy", "bear"})

EDC = EventDrivenConfig()


# ============================================================
# 财报数据解析
# ============================================================

def parse_earnings_quality(earnings_data: dict, as_of_date: Optional[str] = None) -> dict:
    """
    解析财报质量指标。

    Args:
        earnings_data: Alpha Vantage earnings API返回的数据
        as_of_date: 回测时防止前视偏差，只看该日期之前的财报

    Returns:
        {
            beat_rate: float,           # 历史超预期率
            quarters_analyzed: int,     # 分析了几季度
            last_surprise_pct: float,   # 最近一次超预期幅度
            next_earnings_date: str,    # 下次财报日期
            is_qualified: bool,         # 是否满足入场条件
            reason: str,
        }
    """
    result = {
        "beat_rate": 0.0,
        "quarters_analyzed": 0,
        "last_surprise_pct": 0.0,
        "next_earnings_date": "",
        "is_qualified": False,
        "reason": "",
    }

    if not earnings_data:
        result["reason"] = "无财报数据"
        return result

    # 解析季度EPS数据（兼容 get_earnings 返回的 quarterly 格式）
    quarterly = earnings_data.get("quarterly", earnings_data.get("quarterlyEarnings", []))
    if not quarterly:
        result["reason"] = "无季度EPS数据"
        return result

    # 统一日期字段名（get_earnings 用 "date"，原始API用 "reportedDate"）
    def _q_date(q): return q.get("date") or q.get("reportedDate", "9999-99-99")

    # 过滤掉未来财报（防止前视偏差），统一转为 "YYYY-MM-DD" 字符串
    cutoff = str(as_of_date)[:10] if as_of_date else datetime.now().strftime("%Y-%m-%d")

    # 分离历史/未来季度：FMP 有 is_future 标记，AV 没有（用日期判断）
    def _is_future_q(q):
        return q.get("is_future", False) or _q_date(q) > cutoff

    # 历史季度：日期 <= cutoff 且有实际EPS（is_future=False 或 AV无标记）
    past_quarters = [q for q in quarterly if not _is_future_q(q) and _q_date(q) <= cutoff]

    # 找下次财报日期：日期 > cutoff（含FMP的未来季度和AV的已知future）
    upcoming = [q for q in quarterly if _q_date(q) > cutoff]
    if upcoming:
        next_q = min(upcoming, key=_q_date)
        result["next_earnings_date"] = next_q.get("date") or next_q.get("reportedDate", "")

    if len(past_quarters) < EDC.MIN_QUARTERS_DATA:
        result["reason"] = f"历史数据不足 {len(past_quarters)} 季度（需 {EDC.MIN_QUARTERS_DATA}）"
        return result

    # 计算超预期率（最近 N 季度）
    recent = past_quarters[:EDC.MIN_QUARTERS_DATA]
    beat_count = 0
    last_surprise_pct = 0.0

    for i, q in enumerate(recent):
        try:
            # 兼容两种字段名：get_earnings用snake_case，原始API用camelCase
            reported  = q.get("reported_eps")  or q.get("reportedEPS")
            estimated = q.get("estimated_eps") or q.get("estimatedEPS")
            surprise_direct = q.get("surprise_pct")  # get_earnings 已算好

            if surprise_direct is not None:
                surprise = float(surprise_direct) / 100.0  # 转为小数
            elif reported is not None and estimated is not None:
                reported  = float(reported  or 0)
                estimated = float(estimated or 0)
                surprise  = (reported - estimated) / abs(estimated) if estimated != 0 else 0.0
            else:
                continue

            if surprise > 0:
                beat_count += 1
            if i == 0:
                last_surprise_pct = surprise
        except (ValueError, TypeError):
            continue

    beat_rate = beat_count / EDC.MIN_QUARTERS_DATA
    result["beat_rate"] = beat_rate
    result["quarters_analyzed"] = len(recent)
    result["last_surprise_pct"] = last_surprise_pct

    # 判断是否满足条件
    if beat_rate >= EDC.MIN_BEAT_RATE and last_surprise_pct >= EDC.MIN_EPS_SURPRISE_PCT:
        result["is_qualified"] = True
        result["reason"] = (f"超预期率={beat_rate:.0%} "
                            f"最近超预期={last_surprise_pct:+.1%}")
        logger.debug(f"[ED] 财报质量合格: {result['reason']}")
    else:
        missing = []
        if beat_rate < EDC.MIN_BEAT_RATE:
            missing.append(f"超预期率={beat_rate:.0%}(需>={EDC.MIN_BEAT_RATE:.0%})")
        if last_surprise_pct < EDC.MIN_EPS_SURPRISE_PCT:
            missing.append(f"最近超预期={last_surprise_pct:+.1%}(需>={EDC.MIN_EPS_SURPRISE_PCT:.0%})")
        result["reason"] = "不合格: " + " | ".join(missing)

    return result


def is_within_entry_window(next_earnings_date: str, current_date: str) -> bool:
    """
    判断是否在入场窗口内（财报前 N 天）。
    """
    if not next_earnings_date:
        return False
    try:
        earn_dt = datetime.strptime(str(next_earnings_date)[:10], "%Y-%m-%d")
        curr_dt = datetime.strptime(str(current_date)[:10], "%Y-%m-%d")
        days_until = (earn_dt - curr_dt).days
        return 0 < days_until <= EDC.ENTRY_DAYS_BEFORE_EARNINGS
    except ValueError:
        return False


# ============================================================
# 回测引擎（日级别）
# ============================================================

async def run_event_driven_backtest(
    start_date: str,
    end_date: str,
    regime_series: Optional[dict] = None,
    capital_ratio: float = 1.0,
    _prefetched: Optional[dict] = None,
    _prefetched_fundamentals: Optional[dict] = None,
) -> dict:
    """
    事件驱动策略回测引擎。

    Args:
        start_date: 回测开始日期
        end_date: 回测结束日期
        regime_series: 可选体制序列（组合回测时由portfolio_manager传入）
        capital_ratio: 分配给本策略的资金比例
        _prefetched: 预取的价格数据
        _prefetched_fundamentals: 预取的财报基本面数据

    Returns:
        回测结果字典
    """
    logger.info(f"[ED Backtest] 开始 {start_date} → {end_date} | 资金比例={capital_ratio:.0%}")

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt   = datetime.strptime(end_date,   "%Y-%m-%d")

    # --- 数据获取 ---
    fundamentals: dict = {}
    if _prefetched:
        histories = _prefetched
        if _prefetched_fundamentals:
            fundamentals = _prefetched_fundamentals
        else:
            # 调用方只传了价格数据，自行补充财报
            logger.info("[ED Backtest] 价格已预取，补充获取财报数据...")
            fundamentals = await fetch_ed_fundamentals_only()
    else:
        histories, fundamentals = await _fetch_ed_data(start_date, end_date)
        if _prefetched_fundamentals:
            fundamentals = _prefetched_fundamentals

    if not histories:
        logger.error("[ED Backtest] 数据获取失败")
        return {"error": "数据获取失败"}

    # --- 构建日期序列 ---
    spy_dates = None
    for ticker, h in histories.items():
        if h and "dates" in h:
            spy_dates = [str(d)[:10] for d in h["dates"]
                         if start_dt <= _to_dt(d) <= end_dt]
            break

    if not spy_dates:
        return {"error": "日期序列构建失败"}

    spy_dates = sorted(spy_dates)
    logger.info(f"[ED Backtest] 日期序列: {spy_dates[0]} → {spy_dates[-1]} ({len(spy_dates)}天)")

    # --- 构建 regime 查询表 ---
    # regime_series: {date_str: "bull"/"bear"/"strong_bull"/"choppy"} 或 None
    _regime_map: dict = {}
    if regime_series and isinstance(regime_series, dict):
        _regime_map = {str(k)[:10]: v for k, v in regime_series.items()}

    # --- 回测主循环 ---
    equity = 1.0
    equity_curve = [1.0]
    daily_returns = []
    trades = []
    open_positions = {}   # {ticker: {entry_price, stop_price, earnings_date, hold_days}}

    total_trades = 0
    winning_trades = 0

    for day_idx, date_str in enumerate(spy_dates):

        # 1. 检查持仓出场（财报日次日强制平仓）
        positions_to_close = []
        for ticker, pos in open_positions.items():
            pos["hold_days"] += 1
            h = histories.get(ticker)
            if not h:
                continue

            closes = _get_closes_up_to_ed(h, date_str)
            if closes is None:
                continue

            should_exit = False
            exit_reason = ""
            current_price = closes[-1]

            # 财报已发布（次日出场）
            earn_date = pos.get("earnings_date", "")
            if earn_date and date_str > earn_date:
                should_exit = True
                exit_reason = f"财报后出场 (报告日={earn_date})"

            # ATR硬止损
            elif current_price <= pos["stop_price"]:
                should_exit = True
                exit_reason = f"ATR硬止损 price={current_price:.2f} stop={pos['stop_price']:.2f}"

            # 超时保护（最多持仓10天）
            elif pos["hold_days"] >= 10:
                should_exit = True
                exit_reason = f"超时止损 持仓{pos['hold_days']}天"

            if should_exit:
                exit_price = current_price * (1 - EDC.BACKTEST_SLIPPAGE)
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
                    "exit_reason": exit_reason,
                    "earnings_date": earn_date,
                })
                logger.debug(f"[ED] 平仓 {ticker} {date_str} PnL={pnl:+.2%} | {exit_reason}")

        for ticker in positions_to_close:
            del open_positions[ticker]

        # 2. 扫描新的入场信号
        # Regime 门控：bull/strong_bull 时 ED 完全停止入场（WF验证 2021 OOS=-0.99）
        today_regime = _regime_map.get(date_str, "")
        if today_regime and today_regime not in EDC.ACTIVE_REGIMES:
            continue
        _max_pos_today = EDC.MAX_POSITIONS
        if len(open_positions) < _max_pos_today:
            slots = _max_pos_today - len(open_positions)
            candidates = _scan_event_candidates(
                histories, fundamentals, date_str, open_positions, slots
            )

            for cand in candidates[:slots]:
                ticker = cand["ticker"]
                entry_price = cand["entry_price"] * (1 + EDC.BACKTEST_SLIPPAGE)
                weight = 1.0 / EDC.MAX_POSITIONS

                open_positions[ticker] = {
                    "entry_price": entry_price,
                    "stop_price": cand["stop_price"],
                    "earnings_date": cand["next_earnings_date"],
                    "hold_days": 0,
                    "weight": weight,
                }
                trades.append({
                    "type": "entry",
                    "ticker": ticker,
                    "date": date_str,
                    "entry_price": entry_price,
                    "next_earnings_date": cand["next_earnings_date"],
                    "beat_rate": cand["beat_rate"],
                    "last_surprise_pct": cand["last_surprise_pct"],
                })
                logger.debug(
                    f"[ED] 建仓 {ticker} {date_str} "
                    f"财报日={cand['next_earnings_date']} "
                    f"超预期率={cand['beat_rate']:.0%}"
                )

        # 逐日市值估算（mark-to-market）
        # 组合价值 = 现金部分 + 各持仓当日市值
        # 现金占比 = 1 - 已开仓权重之和
        invested_weight = sum(p["weight"] for p in open_positions.values())
        cash_weight = max(0.0, 1.0 - invested_weight)
        mtm_equity = equity * cash_weight

        for ticker, pos in open_positions.items():
            h = histories.get(ticker)
            if h:
                closes = _get_closes_up_to_ed(h, date_str)
                if closes is not None and len(closes) > 0:
                    current_price = closes[-1]
                    # 该仓位当日市值 = 初始投入 × (1 + 未实现盈亏%)
                    pos_value = equity * pos["weight"] * (current_price / pos["entry_price"])
                    mtm_equity += pos_value
                else:
                    # 无法取到当日价格，按成本价持有
                    mtm_equity += equity * pos["weight"]
            else:
                mtm_equity += equity * pos["weight"]

        equity_curve.append(mtm_equity)
        daily_returns.append(
            (equity_curve[-1] / equity_curve[-2]) - 1 if len(equity_curve) > 1 else 0.0
        )

    # --- 统计 ---
    total_days = len(spy_dates)
    cumulative_return = equity - 1.0
    annualized_return = (equity ** (252 / max(total_days, 1))) - 1
    vol = float(np.std(daily_returns) * np.sqrt(252)) if len(daily_returns) > 1 else 0.0
    sharpe = annualized_return / vol if vol > 0 else 0.0
    max_dd = _compute_max_drawdown_ed(equity_curve)
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

    result = {
        "strategy": "event_driven",
        "period": f"{start_date} → {end_date}",
        "trading_days": total_days,
        "cumulative_return": round(cumulative_return, 4),
        "annualized_return": round(annualized_return, 4),
        "annualized_vol": round(vol, 4),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown": round(max_dd, 4),
        "total_trades": total_trades,
        "win_rate": round(win_rate, 4),
        "equity_curve": equity_curve,
        "trades": trades,
        "config": {
            "entry_days_before": EDC.ENTRY_DAYS_BEFORE_EARNINGS,
            "min_beat_rate": EDC.MIN_BEAT_RATE,
            "min_eps_surprise": EDC.MIN_EPS_SURPRISE_PCT,
            "atr_stop_mult": EDC.ATR_STOP_MULT,
            "max_positions": EDC.MAX_POSITIONS,
        },
    }

    logger.info(
        f"[ED Backtest] 完成 | 累计={cumulative_return:+.2%} "
        f"年化={annualized_return:+.2%} 夏普={sharpe:.2f} "
        f"回撤={max_dd:.2%} 胜率={win_rate:.1%} 交易{total_trades}次"
    )
    return result


# ============================================================
# 实时信号扫描（供 portfolio_manager 调用）
# ============================================================

async def scan_live_events(current_date: Optional[str] = None) -> list[dict]:
    """
    扫描未来 3 天内有财报且历史质量高的公司。
    每日盘后由 portfolio_manager 调用。
    """
    if current_date is None:
        current_date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"[ED Live] 开始扫描事件驱动信号，日期={current_date}")

    # Regime 门控：bull/strong_bull 时 ED 无效，直接跳过
    try:
        from app.services.rotation_service import _detect_regime
        current_regime = await _detect_regime()
        if current_regime not in EDC.ACTIVE_REGIMES:
            logger.info(f"[ED Live] Regime={current_regime}，非 bear/choppy，跳过 ED 扫描")
            return []
    except Exception as _re:
        logger.warning(f"[ED Live] Regime 检测失败，继续扫描: {_re}")

    av = get_av_client()
    candidates = []

    for item in SP100_POOL:
        ticker = item["ticker"]
        try:
            # 获取价格数据
            h = await av.get_history_arrays(ticker, days=EDC.LOOKBACK_DAYS)
            if not h or len(h.get("close", [])) < 20:
                continue

            # 流动性过滤
            avg_vol = float(np.mean(h["volume"][-20:])) if len(h["volume"]) >= 20 else 0
            if avg_vol < EDC.BACKTEST_MIN_AVG_VOL:
                continue

            # 获取财报数据
            earnings_data = await av.get_earnings(ticker)
            eq = parse_earnings_quality(earnings_data, as_of_date=current_date)

            if not eq["is_qualified"]:
                continue

            if not is_within_entry_window(eq["next_earnings_date"], current_date):
                continue

            from app.services.rotation_service import _compute_atr
            closes = np.array(h["close"])
            highs  = np.array(h["high"])
            lows   = np.array(h["low"])
            atr    = _compute_atr(highs, lows, closes)
            stop_price = closes[-1] - EDC.ATR_STOP_MULT * atr

            candidates.append({
                "ticker": ticker,
                "name": item["name"],
                "sector": item["sector"],
                "current_price": float(closes[-1]),
                "next_earnings_date": eq["next_earnings_date"],
                "beat_rate": eq["beat_rate"],
                "last_surprise_pct": eq["last_surprise_pct"],
                "stop_price": stop_price,
                "atr": atr,
                "reason": eq["reason"],
            })
            logger.info(
                f"[ED Live] 信号 {ticker}: 财报日={eq['next_earnings_date']} "
                f"超预期率={eq['beat_rate']:.0%}"
            )

        except Exception as e:
            logger.warning(f"[ED Live] {ticker} 扫描异常: {e}")

    candidates.sort(key=lambda x: x["beat_rate"], reverse=True)
    logger.info(f"[ED Live] 扫描完成，发现 {len(candidates)} 个事件候选")
    return candidates


# ============================================================
# 内部工具函数
# ============================================================

async def _fetch_ed_data(start_date: str, end_date: str) -> tuple[dict, dict]:
    """获取事件驱动策略所需数据（价格 + 财报）。
    - 价格数据：Alpha Vantage（outputsize=full，约3000天历史）
    - 财报数据：FMP /stable/earnings（覆盖1985至今，免费250次/天）
      AV 财报 API 只返回最近12季度，无法回测2018年前；FMP 弥补这一不足。
    """
    av = get_av_client()
    days_needed = 3000  # 覆盖2018至今（约8年历史）

    logger.info(f"[ED] 开始获取价格数据，共 {len(SP100_TICKERS)} 只，拉取 {days_needed} 天历史")
    histories = {}
    failed_price = []

    for ticker in SP100_TICKERS:
        try:
            h = await av.get_history_arrays(ticker, days=days_needed)
            if h and len(h.get("close", [])) >= 20:
                histories[ticker] = h
            else:
                failed_price.append(ticker)
        except Exception as e:
            logger.warning(f"[ED] 价格数据失败 {ticker}: {e}")
            failed_price.append(ticker)

    logger.info(f"[ED] 价格数据完成: {len(histories)}只成功，{len(failed_price)}只失败")

    # 用 FMP 批量获取财报数据（覆盖2018年前历史）
    logger.info(f"[ED] 开始通过 FMP 批量获取财报数据，共 {len(SP100_TICKERS)} 只")
    try:
        fmp_results = await fmp_batch_get_earnings(SP100_TICKERS, concurrency=5)
    except Exception as e:
        logger.warning(f"[ED] FMP 批量请求异常: {e}，降级使用 AV")
        fmp_results = {}

    fundamentals = {}
    for ticker in SP100_TICKERS:
        if ticker in fmp_results:
            fundamentals[ticker] = {"earnings_data": fmp_results[ticker]}
        else:
            # FMP 失败降级：尝试 AV（只有最近12季度，2018回测可能无数据）
            try:
                earnings = await av.get_earnings(ticker)
                if earnings:
                    fundamentals[ticker] = {"earnings_data": earnings}
                    logger.debug(f"[ED] {ticker} 降级使用 AV 财报数据")
            except Exception as e:
                logger.warning(f"[ED] {ticker} AV 财报降级也失败: {e}")

    logger.info(
        f"[ED] 数据获取完成: 价格{len(histories)}只 财报{len(fundamentals)}只 "
        f"(FMP:{len(fmp_results)}只 价格失败{len(failed_price)}只)"
    )
    return histories, fundamentals


async def fetch_ed_fundamentals_only() -> dict:
    """仅获取 ED 策略所需财报数据（不拉价格），供 portfolio_manager 共享预取使用。"""
    logger.info(f"[ED] 仅获取财报数据，共 {len(SP100_TICKERS)} 只")
    av = get_av_client()
    try:
        fmp_results = await fmp_batch_get_earnings(SP100_TICKERS, concurrency=5)
    except Exception as e:
        logger.warning(f"[ED] FMP 批量请求异常: {e}，降级使用 AV")
        fmp_results = {}

    fundamentals = {}
    for ticker in SP100_TICKERS:
        if ticker in fmp_results:
            fundamentals[ticker] = {"earnings_data": fmp_results[ticker]}
        else:
            try:
                earnings = await av.get_earnings(ticker)
                if earnings:
                    fundamentals[ticker] = {"earnings_data": earnings}
            except Exception:
                pass

    logger.info(f"[ED] 财报数据获取完成: {len(fundamentals)} 只")
    return fundamentals


def _scan_event_candidates(
    histories: dict,
    fundamentals: dict,
    date_str: str,
    open_positions: dict,
    slots: int,
) -> list:
    """扫描当日所有事件驱动候选。"""
    from app.services.rotation_service import _compute_atr
    candidates = []
    sector_count = {}

    for item in SP100_POOL:
        ticker = item["ticker"]
        if ticker in open_positions:
            continue

        sector = item["sector"]
        if sector_count.get(sector, 0) >= EDC.MAX_SECTOR_CONCENTRATION:
            continue

        h = histories.get(ticker)
        fund = fundamentals.get(ticker, {})
        earnings_data = fund.get("earnings_data")

        if not h or not earnings_data:
            continue

        eq = parse_earnings_quality(earnings_data, as_of_date=date_str)
        if not eq["is_qualified"]:
            continue

        if not is_within_entry_window(eq["next_earnings_date"], date_str):
            continue

        closes = _get_closes_up_to_ed(h, date_str)
        if closes is None or len(closes) < 20:
            continue

        # 流动性过滤
        vols = h.get("volume", [])
        idx_map = {str(d)[:10]: i for i, d in enumerate(h["dates"])}
        idx = idx_map.get(date_str)
        if idx is None:
            continue
        if idx >= 20:
            avg_vol = float(np.mean(np.array(vols[max(0, idx-20):idx])))
            if avg_vol < EDC.BACKTEST_MIN_AVG_VOL:
                continue

        highs_arr = np.array(h["high"][:idx + 1])
        lows_arr  = np.array(h["low"][:idx + 1])
        atr = _compute_atr(highs_arr, lows_arr, closes)
        stop_price = closes[-1] - EDC.ATR_STOP_MULT * atr

        candidates.append({
            "ticker": ticker,
            "entry_price": float(closes[-1]),
            "stop_price": stop_price,
            "next_earnings_date": eq["next_earnings_date"],
            "beat_rate": eq["beat_rate"],
            "last_surprise_pct": eq["last_surprise_pct"],
        })
        sector_count[sector] = sector_count.get(sector, 0) + 1

    candidates.sort(key=lambda x: x["beat_rate"], reverse=True)
    return candidates[:slots]


def _get_closes_up_to_ed(h: dict, date_str: str) -> Optional[np.ndarray]:
    """获取截止到指定日期的收盘价序列（事件驱动版）。"""
    if not h or "dates" not in h:
        return None
    dates = [str(d)[:10] for d in h["dates"]]  # 统一转字符串
    closes = h["close"]
    idx = None
    for i, d in enumerate(dates):
        if d == date_str:
            idx = i
            break
        elif d < date_str:
            idx = i
    if idx is None or idx < 15:
        return None
    return np.array(closes[:idx + 1])


def _compute_max_drawdown_ed(equity_curve: list) -> float:
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
