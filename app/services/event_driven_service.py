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
from app.config.rotation_watchlist import RotationConfig as _RC
_RC_inst = _RC()

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

    优化后流程（v2）：
    1. 调用 AV EARNINGS_CALENDAR 拿全市场未来财报日历（1 次 API 调用）
    2. 过滤出 SP100 内、未来 3 天有财报的标的（通常 0-5 只）
    3. 仅对命中标的拉历史 EPS 质量数据（少量 API 调用）
    原流程每次扫描需 90+ 次 AV 调用，新流程通常 < 10 次。
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

    # C5 散户情绪门控：meme 模式时财报信号失效，跳过所有入场
    try:
        from app.services.retail_sentiment_service import get_today_meme_mode
        meme_mode, meme_rationale = await get_today_meme_mode(current_date)
        if meme_mode:
            logger.warning(
                f"[ED Live] C5 meme_mode=True，跳过所有 ED 入场。原因: {meme_rationale}"
            )
            return []
        logger.info(f"[ED Live] C5 meme_mode=False，ED 正常运行")
    except Exception as _ce:
        logger.warning(f"[ED Live] C5 门控查询失败，继续扫描: {_ce}")

    av = get_av_client()
    sp100_set = {item["ticker"]: item for item in SP100_POOL}

    # ── Step 1：拉财报日历，定位未来 3 天内 SP100 标的 ──────────────
    calendar_hits: list[tuple[str, str]] = []  # [(ticker, report_date), ...]
    try:
        calendar = await av.get_earnings_calendar(horizon="3month")
        for entry in calendar:
            ticker = entry.get("ticker", "")
            report_date = entry.get("report_date", "")
            if ticker not in sp100_set:
                continue
            if not is_within_entry_window(report_date, current_date):
                continue
            calendar_hits.append((ticker, report_date))
    except Exception as e:
        logger.warning(f"[ED Live] EARNINGS_CALENDAR 失败，降级全量扫描: {e}")
        # 降级：全量扫描，依赖 AV EARNINGS 里偶尔携带的未来日期
        calendar_hits = [(item["ticker"], "") for item in SP100_POOL]

    if not calendar_hits:
        logger.info(f"[ED Live] 未来 {EDC.ENTRY_DAYS_BEFORE_EARNINGS} 天内无 SP100 财报，结束")
        return []

    logger.info(f"[ED Live] 日历命中 {len(calendar_hits)} 只: "
                f"{[t for t, _ in calendar_hits]}")

    # ── Step 2：对命中标的逐一拉质量数据 ────────────────────────────
    from app.services.rotation_service import _compute_atr
    candidates = []

    for ticker, report_date in calendar_hits:
        item = sp100_set[ticker]
        try:
            # 价格数据
            h = await av.get_history_arrays(ticker, days=EDC.LOOKBACK_DAYS)
            if not h or len(h.get("close", [])) < 20:
                logger.warning(f"[ED Live] {ticker} 价格数据不足，跳过")
                continue

            # 流动性过滤
            avg_vol = float(np.mean(h["volume"][-20:])) if len(h["volume"]) >= 20 else 0
            if avg_vol < EDC.BACKTEST_MIN_AVG_VOL:
                logger.info(f"[ED Live] {ticker} 流动性 {avg_vol/1e6:.1f}M 不足，跳过")
                continue

            # 历史 EPS 质量
            earnings_data = await av.get_earnings(ticker)
            eq = parse_earnings_quality(earnings_data, as_of_date=current_date)
            if not eq["is_qualified"]:
                logger.info(f"[ED Live] {ticker} 质量不合格: {eq['reason']}")
                continue

            # 日历日期优先（比 AV EARNINGS 历史记录更可靠）
            next_earnings_date = report_date or eq.get("next_earnings_date", "")

            closes = np.array(h["close"])
            highs  = np.array(h["high"])
            lows   = np.array(h["low"])
            atr    = _compute_atr(highs, lows, closes)
            stop_price = round(closes[-1] - EDC.ATR_STOP_MULT * atr, 2)

            candidates.append({
                "ticker": ticker,
                "name": item["name"],
                "sector": item["sector"],
                "current_price": float(closes[-1]),
                "next_earnings_date": next_earnings_date,
                "beat_rate": eq["beat_rate"],
                "last_surprise_pct": eq["last_surprise_pct"],
                "stop_price": stop_price,
                "atr": atr,
                "reason": eq["reason"],
            })
            logger.info(
                f"[ED Live] ✓ {ticker}: 财报日={next_earnings_date} "
                f"beat_rate={eq['beat_rate']:.0%} surprise={eq['last_surprise_pct']:+.1%}"
            )

        except Exception as e:
            logger.warning(f"[ED Live] {ticker} 扫描异常: {e}")

    candidates.sort(key=lambda x: x["beat_rate"], reverse=True)
    logger.info(f"[ED Live] 扫描完成，{len(candidates)} 个合格候选")
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


# ============================================================
# 实盘交易（Live Trading）
# ============================================================

def _get_ed_db():
    from app.database import get_db
    return get_db()


async def get_ed_positions_by_status(status: str) -> list[dict]:
    """查询 event_driven_positions 表中指定状态的仓位。"""
    try:
        db = _get_ed_db()
        result = db.table("event_driven_positions").select("*").eq("status", status).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"[ED Live] get_ed_positions_by_status error: {e}")
        return []


async def create_ed_pending_entries(candidates: list[dict]) -> int:
    """
    将当日 ED 扫描候选写入 event_driven_positions 表（pending_entry）。

    逻辑：
    - 已有 active / pending_entry 的 ticker 跳过（不重复建仓）
    - 候选为空时，取消所有过期的 pending_entry（earnings_date 已过）
    返回新建记录数。
    """
    db = _get_ed_db()
    today = datetime.now().strftime("%Y-%m-%d")

    # 查询已有活跃/待入场仓位
    existing_active = await get_ed_positions_by_status("active")
    existing_pending = await get_ed_positions_by_status("pending_entry")
    occupied = {p["ticker"] for p in existing_active + existing_pending}

    # 取消 earnings_date 已过的 pending_entry
    for pos in existing_pending:
        ed = pos.get("earnings_date", "") or ""
        if ed and ed < today:
            try:
                db.table("event_driven_positions").update(
                    {"status": "cancelled"}
                ).eq("id", pos["id"]).execute()
                logger.info(f"[ED Live] 取消过期 pending_entry: {pos['ticker']} (earnings={ed})")
            except Exception as e:
                logger.warning(f"[ED Live] 取消过期记录失败 {pos['ticker']}: {e}")

    if not candidates:
        logger.info("[ED Live] 无 ED 候选，跳过写入")
        return 0

    created = 0
    for c in candidates:
        ticker = c.get("ticker", "")
        if not ticker or ticker in occupied:
            continue
        try:
            row = {
                "ticker": ticker,
                "status": "pending_entry",
                "earnings_date": c.get("next_earnings_date", ""),
                "beat_rate": c.get("beat_rate"),
                "last_surprise_pct": c.get("last_surprise_pct"),
                "signal_price": c.get("current_price"),
                "stop_loss": round(c.get("stop_price", 0), 2) if c.get("stop_price") else None,
                "atr14": round(c.get("atr", 0), 4) if c.get("atr") else None,
            }
            db.table("event_driven_positions").insert(row).execute()
            logger.info(
                f"[ED Live] 创建 pending_entry: {ticker} "
                f"earnings={row['earnings_date']} beat_rate={row['beat_rate']:.0%}"
            )
            created += 1
        except Exception as e:
            err = str(e).lower()
            if "duplicate" in err or "unique" in err or "23505" in err:
                logger.warning(f"[ED Live] {ticker} 已存在，跳过")
            else:
                logger.error(f"[ED Live] 写入 pending_entry 失败 {ticker}: {e}")

    logger.info(f"[ED Live] create_ed_pending_entries 完成，新建 {created} 条")
    return created


async def _activate_ed_position(
    position_id: str,
    ticker: str,
    entry_price: float,
    atr: float,
    stop_loss: float,
) -> bool:
    """
    激活一个 ED pending_entry 仓位，向 Tiger 下 MKT 买单。
    返回 True 表示下单成功。
    """
    import asyncio
    from app.services.order_service import get_tiger_trade_client, calculate_position_size
    from app.services.portfolio_manager import ALLOCATION_MATRIX
    from app.services.rotation_service import _detect_regime

    db = _get_ed_db()
    today = datetime.now().strftime("%Y-%m-%d")

    update_data = {
        "status": "active",
        "entry_price": round(entry_price, 4),
        "entry_date": today,
        "current_price": round(entry_price, 4),
        "stop_loss": round(stop_loss, 2),
        "atr14": round(atr, 4),
    }

    try:
        tiger = get_tiger_trade_client()
        regime = await _detect_regime()
        ed_fraction = ALLOCATION_MATRIX.get(regime, ALLOCATION_MATRIX["bull"])["event_driven"]
        qty = await calculate_position_size(
            tiger, entry_price,
            max_positions=EDC.MAX_POSITIONS,
            equity_fraction=ed_fraction,
        )

        if qty > 0:
            if not _RC_inst.AUTO_EXECUTE_ORDERS:
                logger.info(
                    f"[SIGNAL ONLY] ED BUY {ticker} qty={qty} @ ${entry_price:.2f} "
                    f"ed_fraction={ed_fraction:.0%} — AUTO_EXECUTE_ORDERS=False，等待人工确认"
                )
            else:
                result = await tiger.place_buy_order(ticker, qty, order_type="MKT")
                if result:
                    order_id = str(result.get("id") or result.get("order_id") or "")
                    update_data["quantity"] = qty
                    update_data["tiger_order_id"] = order_id
                    update_data["tiger_order_status"] = "submitted"
                    logger.info(
                        f"[ED Live] 下单成功 {ticker} qty={qty} "
                        f"ed_fraction={ed_fraction:.0%} order_id={order_id}"
                    )

                    # 5 秒后轮询成交价
                    async def _poll_ed_fill(pos_id: str, oid: str, atr_val: float):
                        await asyncio.sleep(5)
                        try:
                            fill = await tiger.get_order_status(int(oid))
                            if "FILLED" in str(fill.get("status", "")).upper():
                                fp = float(fill.get("avg_fill_price") or 0)
                                if fp > 0:
                                    new_sl = round(fp - EDC.ATR_STOP_MULT * atr_val, 2)
                                    _get_ed_db().table("event_driven_positions").update({
                                        "entry_price": fp,
                                        "current_price": fp,
                                        "stop_loss": new_sl,
                                        "tiger_order_status": "filled",
                                    }).eq("id", pos_id).execute()
                        except Exception as pe:
                            logger.debug(f"[ED Live] fill poll skipped: {pe}")

                    asyncio.create_task(_poll_ed_fill(position_id, order_id, atr))
                else:
                    logger.warning(f"[ED Live] Tiger 返回空结果 {ticker}，仍标记 active")
        else:
            logger.warning(f"[ED Live] 仓位大小为 0，跳过下单 {ticker}")

    except Exception as e:
        logger.error(f"[ED Live] Tiger 下单异常 {ticker}: {e}", exc_info=True)

    # 无论下单是否成功，更新 DB 状态（至少记录入场时间）
    try:
        db.table("event_driven_positions").update(update_data).eq("id", position_id).execute()
    except Exception as e:
        logger.error(f"[ED Live] DB 更新失败 {position_id}: {e}")

    return update_data.get("tiger_order_id") is not None


async def run_ed_entry_check() -> list[dict]:
    """
    ED 每日入场检查（09:41 NZT，收盘数据到位后）。

    与 V4 不同，ED 自动激活：财报窗口时间紧迫，不等人工确认。
    条件：
    - pending_entry 状态
    - earnings_date 在今天或未来（窗口未过期）
    - 当日入场窗口 is_within_entry_window() 返回 True

    TODO（对应 rotation_service.py 注释）：这是 AI 事件信号上线，已开放自动激活。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    pending = await get_ed_positions_by_status("pending_entry")
    if not pending:
        logger.info("[ED Live] run_ed_entry_check: 无 pending_entry，跳过")
        return []

    executed = []
    av = get_av_client()

    for pos in pending:
        ticker = pos["ticker"]
        earnings_date = pos.get("earnings_date", "") or ""

        # 若 earnings_date 已过 → 取消
        if earnings_date and earnings_date < today:
            try:
                _get_ed_db().table("event_driven_positions").update(
                    {"status": "cancelled"}
                ).eq("id", pos["id"]).execute()
                logger.info(f"[ED Live] entry_check 取消过期仓位: {ticker} (earnings={earnings_date})")
            except Exception as e:
                logger.warning(f"[ED Live] 取消失败 {ticker}: {e}")
            continue

        # 检查入场窗口
        if not is_within_entry_window(earnings_date, today):
            logger.info(f"[ED Live] {ticker} 不在入场窗口（earnings={earnings_date}），跳过")
            continue

        # 获取最新价格
        try:
            h = await av.get_history_arrays(ticker, days=30)
            if not h or not h.get("close"):
                logger.warning(f"[ED Live] {ticker} 无价格数据，跳过")
                continue

            closes = np.array(h["close"])
            highs  = np.array(h["high"])
            lows   = np.array(h["low"])
            entry_price = float(closes[-1])
            from app.services.rotation_service import _compute_atr
            atr = _compute_atr(highs, lows, closes)
            stop_loss = round(entry_price - EDC.ATR_STOP_MULT * atr, 2)

        except Exception as e:
            logger.warning(f"[ED Live] {ticker} 价格获取失败: {e}")
            continue

        # 激活仓位
        success = await _activate_ed_position(
            position_id=pos["id"],
            ticker=ticker,
            entry_price=entry_price,
            atr=atr,
            stop_loss=stop_loss,
        )
        if success:
            executed.append({"ticker": ticker, "entry_price": entry_price, "earnings_date": earnings_date})

    logger.info(f"[ED Live] run_ed_entry_check 完成，激活 {len(executed)} 只")
    return executed


async def run_ed_exit_check() -> list[dict]:
    """
    ED 每日出场检查（09:46 NZT）。

    出场条件（优先级顺序）：
    1. 财报后次日：today > earnings_date → 立即平仓（锁住涨幅）
    2. 止损触发：current_price <= stop_loss
    3. 时间止损：持仓超过 ENTRY_DAYS_BEFORE_EARNINGS + 3 天仍未出场
    """
    MAX_HOLD_DAYS = EDC.ENTRY_DAYS_BEFORE_EARNINGS + 3  # 最多持仓 6 天

    today = datetime.now().strftime("%Y-%m-%d")
    active = await get_ed_positions_by_status("active")
    if not active:
        logger.info("[ED Live] run_ed_exit_check: 无 active 仓位，跳过")
        return []

    exited = []
    av = get_av_client()

    for pos in active:
        ticker = pos["ticker"]
        pos_id = pos["id"]
        earnings_date = pos.get("earnings_date", "") or ""
        stop_loss = float(pos.get("stop_loss") or 0)
        entry_date = pos.get("entry_date", "") or ""
        qty = int(pos.get("quantity") or 0)

        exit_reason = None

        # 1. 财报后次日平仓
        if earnings_date and today > earnings_date:
            exit_reason = "post_earnings"

        # 2. 止损（需当前价格）
        if not exit_reason and stop_loss > 0:
            try:
                h = await av.get_history_arrays(ticker, days=5)
                if h and h.get("close"):
                    current_price = float(np.array(h["close"])[-1])
                    # 更新当前价格
                    try:
                        pnl = (current_price / float(pos.get("entry_price") or current_price)) - 1
                        _get_ed_db().table("event_driven_positions").update({
                            "current_price": round(current_price, 4),
                            "unrealized_pnl_pct": round(pnl, 4),
                            "highest_price": round(
                                max(current_price, float(pos.get("highest_price") or 0)), 4
                            ),
                        }).eq("id", pos_id).execute()
                    except Exception:
                        pass

                    if current_price <= stop_loss:
                        exit_reason = "stop_loss"
            except Exception as e:
                logger.warning(f"[ED Live] {ticker} 价格获取失败，跳过止损检查: {e}")

        # 3. 时间止损
        if not exit_reason and entry_date:
            try:
                held_days = (datetime.strptime(today, "%Y-%m-%d") -
                             datetime.strptime(entry_date, "%Y-%m-%d")).days
                if held_days >= MAX_HOLD_DAYS:
                    exit_reason = "time_stop"
            except ValueError:
                pass

        if not exit_reason:
            continue

        # 执行平仓
        logger.info(f"[ED Live] 触发出场 {ticker} reason={exit_reason} qty={qty}")
        exit_price = None

        try:
            if qty > 0:
                if not _RC_inst.AUTO_EXECUTE_ORDERS:
                    logger.info(f"[SIGNAL ONLY] ED SELL {ticker} qty={qty} reason={exit_reason} — AUTO_EXECUTE_ORDERS=False，等待人工确认")
                else:
                    from app.services.order_service import get_tiger_trade_client
                    tiger = get_tiger_trade_client()
                    result = await tiger.place_sell_order(ticker, qty, order_type="MKT")
                    if result:
                        exit_order_id = str(result.get("id") or result.get("order_id") or "")
                        _get_ed_db().table("event_driven_positions").update(
                            {"tiger_exit_order_id": exit_order_id}
                        ).eq("id", pos_id).execute()
                        logger.info(f"[ED Live] SELL 已提交 {ticker} qty={qty} order={exit_order_id}")
        except Exception as e:
            logger.error(f"[ED Live] Tiger SELL 异常 {ticker}: {e}", exc_info=True)

        # 更新 DB 状态
        try:
            _get_ed_db().table("event_driven_positions").update({
                "status": "closed",
                "exit_date": today,
                "exit_reason": exit_reason,
                "exit_price": exit_price,
            }).eq("id", pos_id).execute()
        except Exception as e:
            logger.error(f"[ED Live] DB 平仓更新失败 {ticker}: {e}")

        exited.append({"ticker": ticker, "exit_reason": exit_reason, "qty": qty})

    logger.info(f"[ED Live] run_ed_exit_check 完成，平仓 {len(exited)} 只")
    return exited
