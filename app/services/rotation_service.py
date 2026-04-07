"""
StockQueen 破浪 - 宝典V4 Rotation Service
Weekly momentum rotation + daily entry/exit timing for ETFs and mid-cap US stocks.
Uses Alpha Vantage for market data (replaces yfinance).
"""

import logging
import asyncio
import os
import numpy as np
from typing import Optional
from datetime import datetime, date, timedelta
import pytz

from app.database import get_db
from app.config.rotation_watchlist import (
    RotationConfig,
    OFFENSIVE_ETFS, DEFENSIVE_ETFS, MIDCAP_STOCKS, INVERSE_ETFS,
    INVERSE_ETF_INDEX_MAP, LARGECAP_STOCKS,
    get_offensive_tickers, get_defensive_tickers, get_inverse_tickers,
    get_ticker_info, normalize_sector,
)
from app.models import (
    RotationScore, RotationSnapshot, RotationPosition, DailyTimingSignal,
)
from app.services.alphavantage_client import get_av_client

logger = logging.getLogger(__name__)
RC = RotationConfig

# === Regime 进程内缓存（防止单次调度周期内多次调用 AV API）===
# TTL = 30 分钟，一个调度周期内所有 _detect_regime() 调用共享同一结果
import time as _time_module
_regime_session: dict = {"regime": None, "ts": 0.0}
_REGIME_CACHE_TTL: float = 1800.0  # 30 分钟

# 安全默认 regime：choppy 是最保守的中性值，不会触发牛市选股也不会全面对冲
_SAFE_DEFAULT_REGIME = "choppy"


def _get_last_db_regime() -> str:
    """从 regime_history 表读取最近一条确认的 regime，作为 API 故障时的安全降级。"""
    try:
        db = get_db()
        result = (db.table("regime_history")
                  .select("regime")
                  .order("date", desc=True)
                  .limit(1)
                  .execute())
        if result.data and result.data[0].get("regime"):
            return result.data[0]["regime"]
    except Exception as e:
        logger.warning(f"[REGIME] 无法从 regime_history 读取降级值: {e}")
    return _SAFE_DEFAULT_REGIME


# ============================================================
# HELPERS — Alpha Vantage data fetch
# ============================================================

async def _fetch_history(ticker: str, days: int = RC.LOOKBACK_DAYS) -> Optional[dict]:
    """
    Fetch OHLCV history via Alpha Vantage.
    Returns dict with 'close', 'volume' numpy arrays and 'dates' index,
    or None on failure.
    """
    try:
        av = get_av_client()
        result = await av.get_history_arrays(ticker, days=days)
        if result is None:
            return None
        # Ensure minimum data length
        if len(result["close"]) < 20:
            return None
        return result
    except Exception as e:
        logger.warning(f"Alpha Vantage fetch failed for {ticker}: {e}")
        return None


def _compute_return(closes: np.ndarray, days: int) -> float:
    """Period return over last N trading days."""
    if len(closes) < days + 1:
        return 0.0
    return float((closes[-1] / closes[-days - 1]) - 1.0)


def _compute_volatility(closes: np.ndarray, period: int = RC.VOL_LOOKBACK) -> float:
    """Annualized volatility over lookback period."""
    if len(closes) < period + 1:
        return 0.0
    daily_returns = np.diff(closes[-period - 1:]) / closes[-period - 1:-1]
    return float(np.std(daily_returns) * np.sqrt(252))


def _compute_ma(closes: np.ndarray, period: int) -> float:
    """Simple moving average of last N closes."""
    if len(closes) < period:
        return 0.0
    return float(np.mean(closes[-period:]))


def _compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                 period: int = RC.ATR_PERIOD) -> float:
    """Average True Range."""
    if len(closes) < period + 1:
        return 0.0
    tr_list = []
    for i in range(-period, 0):
        h_l = highs[i] - lows[i]
        h_pc = abs(highs[i] - closes[i - 1])
        l_pc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(h_l, h_pc, l_pc))
    return float(np.mean(tr_list))


# ============================================================
# LOCAL TECHNICAL INDICATORS — for backtest (no API calls)
# ============================================================

def _compute_rsi(closes: np.ndarray, period: int = 14) -> float:
    """Compute RSI locally from close prices. Returns 0-100."""
    if len(closes) < period + 1:
        return 50.0  # neutral default
    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = float(np.mean(gains))
    avg_loss = float(np.mean(losses))
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_macd(closes: np.ndarray) -> dict:
    """Compute MACD(12,26,9) locally. Returns {macd, signal, histogram}."""
    if len(closes) < 35:
        return {"macd": 0, "signal": 0, "histogram": 0}
    # EMA helper using exponential weights
    def _ema(data, span):
        alpha = 2.0 / (span + 1)
        result = np.empty_like(data, dtype=float)
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    signal_line = _ema(macd_line, 9)
    histogram = macd_line - signal_line
    return {
        "macd": float(macd_line[-1]),
        "signal": float(signal_line[-1]),
        "histogram": float(histogram[-1]),
    }


def _compute_bbands(closes: np.ndarray, period: int = 20) -> dict:
    """Compute Bollinger Bands locally. Returns {upper, middle, lower, position}."""
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "position": 0.5}
    window = closes[-period:]
    middle = float(np.mean(window))
    std = float(np.std(window))
    upper = middle + 2 * std
    lower = middle - 2 * std
    current = float(closes[-1])
    band_width = upper - lower
    position = (current - lower) / band_width if band_width > 0 else 0.5
    return {"upper": upper, "middle": middle, "lower": lower, "position": position}


def _compute_obv_trend(closes: np.ndarray, volumes: np.ndarray) -> str:
    """Compute OBV trend locally. Returns 'rising', 'falling', or 'flat'."""
    if len(closes) < 6 or len(volumes) < 6:
        return "flat"
    # Compute OBV for last 20 data points
    n = min(20, len(closes))
    obv = np.zeros(n)
    for i in range(1, n):
        idx = len(closes) - n + i
        if closes[idx] > closes[idx - 1]:
            obv[i] = obv[i - 1] + volumes[idx]
        elif closes[idx] < closes[idx - 1]:
            obv[i] = obv[i - 1] - volumes[idx]
        else:
            obv[i] = obv[i - 1]
    avg_obv = float(np.mean(obv[-5:]))
    latest_obv = float(obv[-1])
    if avg_obv == 0:
        return "flat"
    pct_diff = (latest_obv - avg_obv) / abs(avg_obv) if avg_obv != 0 else 0
    if pct_diff > 0.02:
        return "rising"
    elif pct_diff < -0.02:
        return "falling"
    return "flat"


def _compute_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                 period: int = 14) -> float:
    """Compute ADX locally. Returns 0-100."""
    n = len(closes)
    if n < period + 1:
        return 0.0
    # True Range, +DM, -DM
    tr_list = []
    plus_dm = []
    minus_dm = []
    for i in range(1, n):
        h_l = highs[i] - lows[i]
        h_pc = abs(highs[i] - closes[i - 1])
        l_pc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(h_l, h_pc, l_pc))
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)

    # Smoothed averages (Wilder's smoothing)
    if len(tr_list) < period:
        return 0.0
    atr = float(np.mean(tr_list[-period:]))
    avg_plus_dm = float(np.mean(plus_dm[-period:]))
    avg_minus_dm = float(np.mean(minus_dm[-period:]))

    if atr == 0:
        return 0.0
    plus_di = 100 * avg_plus_dm / atr
    minus_di = 100 * avg_minus_dm / atr
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0.0
    dx = 100 * abs(plus_di - minus_di) / di_sum
    return float(dx)


def _evaluate_tech_local(closes: np.ndarray, volumes: np.ndarray,
                         highs: np.ndarray, lows: np.ndarray) -> float:
    """
    Evaluate technical indicators locally and return adjustment score.
    Mirrors signal_service.py's _evaluate_tech_indicators logic.
    Returns value in range [-2.0, +2.0].
    """
    long_score = 0
    short_score = 0

    # RSI
    rsi = _compute_rsi(closes)
    if rsi < 30:
        long_score += 1   # oversold → bullish
    elif rsi > 70:
        short_score += 1  # overbought → bearish

    # MACD
    macd = _compute_macd(closes)
    if macd["histogram"] > 0:
        long_score += 1   # bullish momentum
    elif macd["histogram"] < 0:
        short_score += 1  # bearish momentum

    # Bollinger Bands
    bb = _compute_bbands(closes)
    if bb["position"] < 0.2:
        long_score += 1   # near lower band → oversold
    elif bb["position"] > 0.8:
        short_score += 1  # near upper band → overbought

    # OBV
    obv = _compute_obv_trend(closes, volumes)
    if obv == "rising":
        long_score += 1
    elif obv == "falling":
        short_score += 1

    # ADX (trend strength amplifier)
    adx = _compute_adx(highs, lows, closes)
    if adx > 25:
        # Strong trend — amplify the dominant direction
        if long_score > short_score:
            long_score += 1
        elif short_score > long_score:
            short_score += 1

    # Net score: normalize to [-2, +2]
    # Max possible: long=6,short=0 → net=6 → capped at 2
    # Min possible: long=0,short=6 → net=-6 → capped at -2
    net = long_score - short_score
    return max(-2.0, min(2.0, net * 0.5))


# ============================================================
# 1. WEEKLY ROTATION — score, regime, select top N
# ============================================================

# US market holidays (NYSE) — fixed dates and observed rules
_US_HOLIDAYS_FIXED = {
    (1, 1),   # New Year's Day
    (6, 19),  # Juneteenth
    (7, 4),   # Independence Day
    (12, 25), # Christmas Day
}


def _is_us_trading_day(d: date | None = None) -> bool:
    """
    Check if a date is a US stock trading day (NYSE).
    Skips weekends and major holidays. Not exhaustive but covers 95%+ cases.
    """
    if d is None:
        # Use US Eastern time to determine "today"
        eastern = pytz.timezone("US/Eastern")
        d = datetime.now(eastern).date()

    # Weekend check
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    # Fixed holidays (simplified — does not handle observed Monday/Friday shifts)
    if (d.month, d.day) in _US_HOLIDAYS_FIXED:
        return False

    # Floating holidays (approximate)
    # MLK Day: 3rd Monday of January
    # Presidents Day: 3rd Monday of February
    # Good Friday: varies (skip for now)
    # Memorial Day: last Monday of May
    # Labor Day: 1st Monday of September
    # Thanksgiving: 4th Thursday of November
    import calendar
    if d.month == 1 and d.weekday() == 0:  # MLK: 3rd Mon Jan
        if 15 <= d.day <= 21:
            return False
    if d.month == 2 and d.weekday() == 0:  # Presidents: 3rd Mon Feb
        if 15 <= d.day <= 21:
            return False
    if d.month == 5 and d.weekday() == 0:  # Memorial: last Mon May
        if d.day >= 25:
            return False
    if d.month == 9 and d.weekday() == 0:  # Labor: 1st Mon Sep
        if d.day <= 7:
            return False
    if d.month == 11 and d.weekday() == 3:  # Thanksgiving: 4th Thu Nov
        if 22 <= d.day <= 28:
            return False

    return True


def _last_trading_day() -> date:
    """Return the most recent US trading day (today if trading, else previous)."""
    eastern = pytz.timezone("US/Eastern")
    d = datetime.now(eastern).date()
    while not _is_us_trading_day(d):
        d -= timedelta(days=1)
    return d


async def run_rotation(trigger_source: str = "scheduler", dry_run: bool = False) -> dict:
    """
    Weekly rotation entry point.
    Steps: detect regime → score universe → select top N → persist snapshot → manage positions.
    trigger_source: 'scheduler' | 'manual_api' | 'weekly_report' | 'weekly_report_push' | 'restart'
    dry_run: if True, compute scores and show what WOULD change, but do NOT modify positions or place orders.
    """
    import asyncio
    logger.info("=" * 50)
    logger.info(f"Starting Rotation Scan (source={trigger_source}, dry_run={dry_run})")
    logger.info("=" * 50)

    # --- Trading day guard (skip on weekends/holidays for auto triggers) ---
    if trigger_source == "scheduler" and not _is_us_trading_day(_last_trading_day()):
        logger.info("Skipping rotation: no recent US trading day")
        return {"skipped": True, "reason": "non_trading_day"}

    # --- Cooldown guard: prevent position changes if rotation already executed today ---
    # (scoring/snapshot is allowed; only position management is gated)
    trading_day = _last_trading_day()
    _rotation_cooldown_bypass = False
    if trigger_source != "scheduler":
        try:
            _cd_db = get_db()
            _cd_result = _cd_db.table("rotation_snapshots").select("id, trigger_source").eq(
                "snapshot_date", trading_day.isoformat()
            ).order("created_at", desc=True).limit(1).execute()
            if _cd_result.data:
                _prev_source = _cd_result.data[0].get("trigger_source", "")
                logger.warning(
                    f"Rotation cooldown: snapshot already exists for {trading_day} "
                    f"(source={_prev_source}). Position changes will be skipped unless dry_run."
                )
                _rotation_cooldown_bypass = True
        except Exception as e:
            logger.warning(f"Cooldown check failed (proceeding): {e}")

    # 1. Detect market regime
    regime = await _detect_regime()
    logger.info(f"Market regime: {regime}")

    # 2. Determine scoring universe based on regime
    #    - selection_universe: tickers eligible for position selection
    #    - full_universe: ALL tickers scored for heatmap/display (always includes all pools)
    #    If USE_DYNAMIC_UNIVERSE is enabled, replace static LARGECAP+MIDCAP with dynamic pool
    stock_pool = LARGECAP_STOCKS + MIDCAP_STOCKS  # default: static watchlist
    if RC.USE_DYNAMIC_UNIVERSE:
        from app.services.universe_service import UniverseService
        _univ_items = UniverseService().get_universe_items()
        if _univ_items:
            stock_pool = _univ_items
            logger.info(f"Using dynamic universe: {len(stock_pool)} stocks")
        else:
            logger.warning("Dynamic universe empty, falling back to static watchlist")

    # 纯 Alpha 模式：评分系统自决，不按 Regime 限制选股池
    # WF 5窗口验证（2020-2024）：去掉硬过滤平均 Sharpe +2.14
    # 熊市时反向ETF评分自然上升（动量/趋势因子高），无需硬过滤
    selection_universe = DEFENSIVE_ETFS + OFFENSIVE_ETFS + stock_pool
    inverse_scores: list[RotationScore] = []
    if regime == "bear":
        inverse_scores = await _score_inverse_etfs(regime)  # 仍评分补充候选池

    # Always score the full universe so heatmap has all sectors
    full_universe = list({
        item["ticker"]: item
        for pool in [DEFENSIVE_ETFS, OFFENSIVE_ETFS] + [stock_pool]
        for item in pool
    }.values())
    selection_tickers = {item["ticker"] for item in selection_universe}

    # 3. Score all tickers (with RAG + relative strength adjustment)
    from app.services.knowledge_service import get_knowledge_service
    ks = get_knowledge_service()

    # Fetch SPY closes for relative strength calculation
    spy_data = await _fetch_history(RC.REGIME_TICKER, days=RC.LOOKBACK_DAYS)
    spy_closes = spy_data["close"] if spy_data else None

    # ML-V3A：预备存储字典（USE_ML_ENHANCE=True 时收集 scorer_result + OHLCV）
    _ml_store: Optional[dict] = {} if RC.USE_ML_ENHANCE else None

    scores: list[RotationScore] = []
    # Concurrent scoring — Massive API has no rate limit
    # 1830 stocks: CONCURRENCY=30 → 61 batches; CONCURRENCY=50 → 37 batches (2x faster)
    CONCURRENCY = 50
    _sem = asyncio.Semaphore(CONCURRENCY)

    async def _score_one(item):
        async with _sem:
            try:
                # 单个 scorer 超时保护：30 秒
                return await asyncio.wait_for(
                    _score_ticker(item, regime, ks, spy_closes=spy_closes, ml_store=_ml_store),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Scorer timeout for {item['ticker']}")
                return None

    results = await asyncio.gather(*[_score_one(item) for item in full_universe],
                                    return_exceptions=True)
    _score_errors = 0
    for r in results:
        if isinstance(r, RotationScore):
            scores.append(r)
        elif isinstance(r, Exception):
            _score_errors += 1

    # ── 零评分告警：如果 universe 非空但评分全部失败，通常是 API key 缺失 ──
    if len(full_universe) > 0 and len(scores) == 0:
        logger.error(
            f"[CRITICAL] 0/{len(full_universe)} tickers scored (errors={_score_errors}). "
            f"Check MASSIVE_API_KEY is configured on this service (WORKER_ROLE={os.environ.get('WORKER_ROLE', 'unknown')})"
        )

    # Merge inverse ETF scores (bear regime only)
    if inverse_scores:
        scores.extend(inverse_scores)

    # Holding inertia: give bonus to already-held tickers to reduce turnover
    current_holdings = await _get_previous_selected()
    if current_holdings:
        for s in scores:
            if s.ticker in current_holdings:
                s.score += RC.HOLDING_BONUS
                logger.info(f"  Holding bonus +{RC.HOLDING_BONUS} for {s.ticker}")

    # Sort descending by score
    scores.sort(key=lambda s: s.score, reverse=True)

    # Apply minimum score threshold — only select from regime-eligible tickers
    # (e.g. bear → only defensive/inverse; full universe still scored for heatmap)
    selectable = [s for s in scores if s.ticker in selection_tickers or s.ticker in {inv.ticker for inv in inverse_scores}]
    # 动态 Regime 门控 (V5)：不同市场环境使用不同入场阈值
    # strong_bull 放宽(-0.1)，bear 收紧(0.5)，实验验证 Sharpe +22%
    _regime_threshold = RC.MIN_SCORE_BY_REGIME.get(regime, RC.MIN_SCORE_THRESHOLD)
    qualified = [s for s in selectable if s.score >= _regime_threshold]

    # ── TOP 20 Fallback：当合格候选不足 TOP_N 时，从全体 selectable 中选最高分 ──
    # 熊市下 MIN_SCORE=0.5 可能过滤掉所有候选，此时用 TOP 20 池的最高分填补，
    # 配合 bear ATR 止损收紧(1.0x) + Hedge Overlay 控制风险。
    _used_fallback = False
    if len(qualified) < RC.TOP_N and len(selectable) > 0:
        _fallback_pool = sorted(selectable, key=lambda s: s.score, reverse=True)[:RC.BACKUP_DEPTH]
        _n_shortfall = RC.TOP_N - len(qualified)
        _fallback_candidates = [s for s in _fallback_pool if s not in qualified][:_n_shortfall]
        qualified = qualified + _fallback_candidates
        _used_fallback = True
        logger.warning(
            f"[FALLBACK] qualified ({len(qualified) - len(_fallback_candidates)}) < TOP_N ({RC.TOP_N}), "
            f"补充 {len(_fallback_candidates)} 只从 TOP {RC.BACKUP_DEPTH} 池: "
            f"{[f'{s.ticker}({s.score:+.3f})' for s in _fallback_candidates]}"
        )

    # ── ML-V3A 重排（如已启用且模型存在，熊市跳过：池子太小且特征失效）──
    if RC.USE_ML_ENHANCE and _ml_store and regime not in ("bear",):
        _ml_ranker = _get_live_ml_ranker()
        if _ml_ranker is not None:
            try:
                from app.services.ml_scorer import ml_rerank_candidates
                scored_tuples = [(s.ticker, s.score) for s in qualified]
                ml_scorer_results = {
                    t: v["result"] for t, v in _ml_store.items()
                    if t in {s.ticker for s in qualified}
                }
                ml_histories = {
                    t: {"close": v["closes"], "volume": v["volumes"], "high": v["highs"]}
                    for t, v in _ml_store.items()
                    if t in {s.ticker for s in qualified}
                }
                ml_selected_pairs = ml_rerank_candidates(
                    scored_list=scored_tuples,
                    scorer_results=ml_scorer_results,
                    regime=regime,
                    ranker=_ml_ranker,
                    top_n=RC.TOP_N,
                    rerank_pool=RC.ML_RERANK_POOL,
                    histories=ml_histories,
                    date_idx=-1,
                )
                selected = [t for t, _ in ml_selected_pairs]
                logger.info(f"[ML-V3A] 重排完成 → {selected}")
            except Exception as e:
                logger.warning(f"[ML-V3A] 重排失败，回退规则选股: {e}")
                selected = [s.ticker for s in qualified[:RC.TOP_N]]
        else:
            selected = [s.ticker for s in qualified[:RC.TOP_N]]
    else:
        selected = [s.ticker for s in qualified[:RC.TOP_N]]

    # ── Trend Hold Exempt D2 (V5.1): 高分持仓跌出 TOP_N 给一次保留周 ──
    # WF验证: score>75th + RS>0.05, avg Sharpe +0.132 (5/6窗口改善)
    if RC.TREND_HOLD_EXEMPT and current_holdings:
        _scores_map_live = {s.ticker: s.score for s in scores}
        _sorted_q = sorted([(s.ticker, s.score) for s in qualified], key=lambda x: x[1])
        _pct_idx = max(0, int(len(_sorted_q) * RC.EXEMPT_SCORE_PCT) - 1)
        _pct_score = _sorted_q[_pct_idx][1] if _sorted_q else 0
        _exempt_added = []
        for _t in current_holdings:
            if _t not in selected:
                _t_score = _scores_map_live.get(_t, -999)
                if _t_score > _pct_score and _t_score > 0:
                    _t_data = await _fetch_history(_t, days=40)
                    if _t_data and spy_closes:
                        _t_rs = _compute_relative_strength(_t_data["close"], spy_closes, period=21)
                        if _t_rs > RC.EXEMPT_RS_MIN:
                            selected.append(_t)
                            _exempt_added.append(_t)
                            logger.info(f"[Hold Exempt D2] {_t} preserved: score={_t_score:.2f} RS={_t_rs:.3f}")
        if _exempt_added:
            logger.info(f"[Hold Exempt D2] 本周保留豁免: {_exempt_added}")

    # ── Hedge Overlay: 独立对冲层 ──
    hedge_info = None
    if RC.HEDGE_OVERLAY_ENABLED:
        _hedge_alloc = RC.HEDGE_ALLOC_BY_REGIME.get(regime, 0.0)
        if _hedge_alloc > 0:
            # 选择原指数最弱的反向ETF
            _best_inv, _best_w = None, -999
            for _inv_tk, _idx_tk in INVERSE_ETF_INDEX_MAP.items():
                _idx_data = await _fetch_history(_idx_tk, days=30)
                if not _idx_data or len(_idx_data["close"]) < 22:
                    continue
                _c = _idx_data["close"]
                _r1w = (_c[-1] / _c[-5]) - 1 if len(_c) >= 5 else 0
                _r1m = (_c[-1] / _c[-22]) - 1 if len(_c) >= 22 else 0
                _w = -(0.4 * _r1w + 0.6 * _r1m)
                if _w > _best_w:
                    _best_w = _w
                    _best_inv = _inv_tk
            if _best_inv:
                hedge_info = {
                    "ticker": _best_inv,
                    "alloc_pct": round(_hedge_alloc * 100, 1),
                    "underlying_weakness": round(_best_w, 4),
                    "regime": regime,
                }
                logger.info(f"Hedge Overlay: {_best_inv} @ {_hedge_alloc:.0%} (regime={regime})")

    n_qualified = len(qualified)
    n_excluded = len(scores) - n_qualified
    if n_excluded > 0:
        excluded_tickers = [f"{s.ticker}({s.score:+.2f})" for s in scores if s.score < _regime_threshold]
        logger.info(f"Score filter: excluded {n_excluded} below threshold {_regime_threshold:.2f} (regime={regime}): {excluded_tickers}")

    logger.info(f"Top {len(selected)} (qualified {n_qualified}/{len(scores)}): {selected}")
    for s in scores[:10]:
        logger.info(f"  {s.ticker:6s} score={s.score:+.2f}  "
                     f"1w={s.return_1w:+.1%} 1m={s.return_1m:+.1%} 3m={s.return_3m:+.1%}  "
                     f"vol={s.volatility:.1%} MA20={'Y' if s.above_ma20 else 'N'}")

    # 4. Load previous snapshot for comparison
    previous_tickers = await _get_previous_selected()
    added = [t for t in selected if t not in previous_tickers]
    removed = [t for t in previous_tickers if t not in selected]

    # 5. Save snapshot (use last trading day as snapshot_date, not today)
    #    复用已有 spy_closes（第 437 行），避免重复调用 AV API 导致 rate limit → spy_price=0
    trading_day = _last_trading_day()
    if spy_closes is not None and len(spy_closes) > 0:
        spy_price = float(spy_closes[-1])
        spy_ma50 = _compute_ma(spy_closes, RC.REGIME_MA_PERIOD) if len(spy_closes) >= RC.REGIME_MA_PERIOD else 0.0
    else:
        # 最后手段：从 regime_history 取最近 spy_price
        try:
            _rh_db = get_db()
            _rh_result = (_rh_db.table("regime_history")
                          .select("spy_price")
                          .order("date", desc=True)
                          .limit(1)
                          .execute())
            spy_price = float(_rh_result.data[0]["spy_price"]) if _rh_result.data else 0.0
        except Exception:
            spy_price = 0.0
        spy_ma50 = 0.0
        logger.warning(f"[ROTATION] spy_closes 不可用，从 regime_history 降级获取 spy_price={spy_price}")

    # --- Dedup: skip if same date + regime + selection already exists ---
    try:
        dup_db = get_db()
        dup_result = dup_db.table("rotation_snapshots").select("id, selected_tickers, regime").eq(
            "snapshot_date", trading_day.isoformat()
        ).order("created_at", desc=True).limit(1).execute()
        if dup_result.data:
            last = dup_result.data[0]
            if last["regime"] == regime and sorted(last.get("selected_tickers") or []) == sorted(selected):
                logger.info(f"Dedup: identical snapshot already exists for {trading_day}, skipping save")
                # Save current scores immediately, then background-score full universe
                await _save_sector_snapshots(scores, regime, trading_day)
                await _persist_all_scores_to_cache(scores, regime)
                import asyncio
                asyncio.create_task(_score_full_universe_background(scores, regime, ks, spy_closes, trading_day, inverse_scores))
                return {
                    "regime": regime,
                    "selected": selected,
                    "added": added,
                    "removed": removed,
                    "scores_top10": [s.model_dump() for s in scores[:10]],
                    "snapshot_id": last["id"],
                    "deduplicated": True,
                    "hedge": hedge_info,
                }
    except Exception as e:
        logger.warning(f"Dedup check failed (proceeding anyway): {e}")

    # --- 快照合法性校验：防止 AV 故障导致错误 regime/spy_price 写入 ---
    _valid_regimes = {"strong_bull", "bull", "choppy", "bear"}
    if regime not in _valid_regimes:
        logger.error(f"[ROTATION] ❌ 非法 regime '{regime}'，中止快照保存")
        return {"error": f"invalid regime: {regime}"}
    if spy_price <= 0:
        logger.error(f"[ROTATION] ❌ spy_price={spy_price}，数据异常，中止快照保存")
        return {"error": f"invalid spy_price: {spy_price}"}
    # 交叉校验：与 regime_history 最近记录比较，差异超过1级时告警
    _db_regime = _get_last_db_regime()
    _regime_severity = {"strong_bull": 3, "bull": 2, "choppy": 1, "bear": 0}
    _diff = abs(_regime_severity.get(regime, 1) - _regime_severity.get(_db_regime, 1))
    if _diff >= 2:
        logger.warning(
            f"[ROTATION] ⚠️ regime 跳变告警: 快照={regime}, DB最近={_db_regime} (差{_diff}级)。"
            f"可能是 AV 降级导致，请关注飞书通知。"
        )

    snapshot = RotationSnapshot(
        snapshot_date=trading_day.isoformat(),
        regime=regime,
        spy_price=spy_price,
        spy_ma50=spy_ma50,
        scores=[s.model_dump() for s in scores[:20]],
        selected_tickers=selected,
        previous_tickers=previous_tickers,
        changes={"added": added, "removed": removed},
    )
    snapshot_id = await _save_snapshot(snapshot, trigger_source=trigger_source)

    # 6. Manage positions (skip if dry_run or cooldown triggered for manual runs)
    _skip_position_mgmt = dry_run or _rotation_cooldown_bypass
    if _skip_position_mgmt:
        _reason = "dry_run" if dry_run else "cooldown (already executed today)"
        logger.info(f"Skipping position management: {_reason}")
    else:
        hedge_ticker = hedge_info.get("ticker") if hedge_info else None
        hedge_alloc = RC.HEDGE_ALLOC_BY_REGIME.get(regime, 0.0)
        await _manage_positions_on_rotation(selected, removed, snapshot_id,
                                             hedge_ticker=hedge_ticker,
                                             hedge_alloc=hedge_alloc)

    # 7. Persist regime-filtered scores to cache + sector snapshots immediately
    await _persist_all_scores_to_cache(scores, regime)
    await _save_sector_snapshots(scores, regime, trading_day)
    await _log_selection_sectors(selected, scores, regime, trading_day)

    # 8. Fire-and-forget: score remaining tickers in background for full sector data
    import asyncio
    asyncio.create_task(_score_full_universe_background(scores, regime, ks, spy_closes, trading_day, inverse_scores))

    result = {
        "regime": regime,
        "selected": selected,
        "added": added,
        "removed": removed,
        "scores_top10": [s.model_dump() for s in scores[:10]],
        "snapshot_id": snapshot_id,
        "hedge": hedge_info,
    }
    if dry_run:
        result["dry_run"] = True
        result["positions_changed"] = False
    if _rotation_cooldown_bypass:
        result["cooldown"] = True
        result["positions_changed"] = False
    return result


async def _persist_all_scores_to_cache(scores: list[RotationScore], regime: str) -> None:
    """Persist ALL rotation scores to cache_store (not just top 20) for sector detail fallback."""
    try:
        scores_payload = {
            "regime": regime,
            "count": len(scores),
            "scores": [s.model_dump() for s in scores],
        }
        cache_db = get_db()
        cache_db.table("cache_store").upsert({
            "key": "rotation_scores",
            "value": scores_payload,
        }).execute()
        logger.info(f"Rotation scores persisted to cache_store ({len(scores)} total)")
    except Exception as e:
        logger.warning(f"Failed to persist scores to cache_store: {e}")


async def _score_full_universe_background(
    initial_scores: list[RotationScore],
    regime: str,
    ks,
    spy_closes,
    trading_day,
    inverse_scores: list[RotationScore],
) -> None:
    """Background task: score all tickers not yet scored (in batches), then update sector snapshots."""
    import asyncio
    try:
        full_universe = OFFENSIVE_ETFS + DEFENSIVE_ETFS + LARGECAP_STOCKS + MIDCAP_STOCKS + INVERSE_ETFS
        scored_tickers = {s.ticker for s in initial_scores}
        extra_items = [item for item in full_universe if item["ticker"] not in scored_tickers]
        if not extra_items:
            logger.info("[BG] All tickers already scored, skipping")
            return

        logger.info(f"[BG] Scoring {len(extra_items)} extra tickers for full sector snapshots...")
        all_scores = list(initial_scores)  # copy

        # Concurrent scoring — Massive API has no rate limit
        BG_CONCURRENCY = 30
        _sem = asyncio.Semaphore(BG_CONCURRENCY)

        async def _bg_score(item):
            async with _sem:
                return await _score_ticker(item, regime, ks, spy_closes=spy_closes)

        results = await asyncio.gather(
            *[_bg_score(item) for item in extra_items],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, RotationScore):
                all_scores.append(r)
        logger.info(f"[BG] Scored {sum(1 for r in results if isinstance(r, RotationScore))}/{len(extra_items)} extra tickers")

        # Also score inverse ETFs if not already included
        if not inverse_scores:
            inv_extra = await _score_inverse_etfs(regime)
            for s in inv_extra:
                if s.ticker not in scored_tickers:
                    all_scores.append(s)

        # Overwrite sector snapshots + cache with full data
        await _save_sector_snapshots(all_scores, regime, trading_day)
        await _persist_all_scores_to_cache(all_scores, regime)
        logger.info(f"[BG] Full universe sector snapshots saved: {len(all_scores)} tickers")
    except Exception as e:
        logger.error(f"[BG] Failed to score full universe: {e}")


async def _save_sector_snapshots(scores: list[RotationScore], regime: str, snapshot_date) -> None:
    """Aggregate scores by sector and persist to sector_snapshots for trend tracking."""
    sector_map: dict[str, dict] = {}
    for s in scores:
        sec = s.sector or "other"
        if not sec:
            continue
        if sec not in sector_map:
            sector_map[sec] = {"score_sum": 0, "ret_sum": 0, "count": 0, "tickers": []}
        sector_map[sec]["score_sum"] += s.score
        sector_map[sec]["ret_sum"] += s.return_1w
        sector_map[sec]["count"] += 1
        sector_map[sec]["tickers"].append({
            "ticker": s.ticker,
            "name": s.name,
            "score": round(s.score, 2),
            "return_1w": round(s.return_1w * 100, 2),
            "current_price": s.current_price,
        })

    try:
        db = get_db()
        rows = []
        for sec, data in sector_map.items():
            n = data["count"]
            data["tickers"].sort(key=lambda x: x["score"], reverse=True)
            rows.append({
                "snapshot_date": snapshot_date.isoformat() if hasattr(snapshot_date, 'isoformat') else str(snapshot_date),
                "sector": sec,
                "avg_score": round(data["score_sum"] / n, 4),
                "avg_ret_1w": round(data["ret_sum"] / n, 4),
                "stock_count": n,
                "top_tickers": data["tickers"][:15],
                "regime": regime,
            })
        if rows:
            db.table("sector_snapshots").upsert(
                rows, on_conflict="snapshot_date,sector"
            ).execute()
            logger.info(f"Saved {len(rows)} sector snapshots for {snapshot_date}")
    except Exception as e:
        logger.warning(f"Failed to save sector snapshots: {e}")


async def _log_selection_sectors(
    selected: list[str],
    scores: list,
    regime: str,
    snapshot_date,
) -> None:
    """记录本次 TOP_N 选股的行业分布到 selection_sector_log 表。"""
    if not selected:
        return
    try:
        score_map = {s.ticker: s for s in scores}
        breakdown: dict[str, int] = {}
        for ticker in selected:
            sec = getattr(score_map.get(ticker), "sector", None) or "unknown"
            breakdown[sec] = breakdown.get(sec, 0) + 1

        dominant = max(breakdown, key=breakdown.get) if breakdown else None
        dominant_pct = round(breakdown[dominant] / len(selected) * 100, 2) if dominant else None

        db = get_db()
        db.table("selection_sector_log").insert({
            "snapshot_date":    snapshot_date.isoformat() if hasattr(snapshot_date, "isoformat") else str(snapshot_date),
            "regime":           regime,
            "selected_tickers": selected,
            "sector_breakdown": breakdown,
            "dominant_sector":  dominant,
            "dominant_pct":     dominant_pct,
        }).execute()
        logger.info(f"Selection sector log saved: {breakdown} (dominant={dominant} {dominant_pct}%)")
    except Exception as e:
        logger.warning(f"Failed to log selection sectors: {e}")


def _compute_regime_score(closes: np.ndarray) -> tuple[str, int]:
    """
    纯函数：从 SPY closes 计算原始 regime 和打分（无 IO，可复用）。
    返回 (regime_str, score_int)。
    """
    ma50 = _compute_ma(closes, 50)
    ma20 = _compute_ma(closes, 20)
    current = float(closes[-1])

    vol_arr = np.diff(closes[-22:]) / closes[-22:-1] if len(closes) > 22 else np.array([0])
    vol_21d = float(np.std(vol_arr) * np.sqrt(252))
    ret_1m = (current / float(closes[-22])) - 1 if len(closes) > 22 else 0

    score = 0
    if current > ma50 * 1.02:   score += 2
    elif current > ma50:         score += 1
    elif current < ma50 * 0.98:  score -= 2
    else:                        score -= 1

    if current > ma20:   score += 1
    else:                score -= 1

    if vol_21d > 0.25:   score -= 1
    elif vol_21d < 0.12: score += 1

    if ret_1m > 0.03:    score += 1
    elif ret_1m < -0.03: score -= 1

    if score >= 4:    regime = "strong_bull"
    elif score >= 1:  regime = "bull"
    elif score >= -1: regime = "choppy"
    else:             regime = "bear"

    return regime, score


async def _confirm_regime(raw_regime: str, raw_score: int, spy_price: float) -> str:
    """
    N 日确认逻辑 + 写入 regime_history。

    规则：新 regime 需连续出现 REGIME_CONFIRM_DAYS 天才正式确认切换。
    期间保持上一次已确认的 regime，避免单日噪声触发仓位轮动。

    每天 upsert 一次今日原始观测到 regime_history 表（date 为唯一键）。
    """
    today = date.today().isoformat()
    n = RC.REGIME_CONFIRM_DAYS  # = 3
    try:
        db = get_db()
        # 读取最近 N+1 条历史（+1 以防今天已写入，需排除后仍有足够数据）
        rows = (db.table("regime_history")
                .select("date, regime")
                .order("date", desc=True)
                .limit(n + 1)
                .execute())
        # 过滤掉今天（避免今天已有旧 upsert 影响判断）
        history = [r for r in (rows.data or []) if r["date"] != today]
        last_confirmed = history[0]["regime"] if history else raw_regime

        # 写入今天原始观测（upsert on date）
        db.table("regime_history").upsert({
            "date": today,
            "regime": raw_regime,
            "score": raw_score,
            "spy_price": spy_price,
            "changed_from": last_confirmed if raw_regime != last_confirmed else None,
        }, on_conflict="date").execute()

        if raw_regime == last_confirmed:
            return raw_regime  # 无变化，直接确认

        # Regime 出现变化：需要最近 N-1 天历史均为 raw_regime 才确认切换
        recent = [r["regime"] for r in history[: n - 1]]
        if len(recent) >= n - 1 and all(r == raw_regime for r in recent):
            logger.info(f"[REGIME] ✅ 连续 {n} 天确认切换: {last_confirmed} → {raw_regime}")
            return raw_regime

        days_seen = sum(1 for r in recent if r == raw_regime)
        logger.info(
            f"[REGIME] ⏳ 信号指向 {raw_regime}（近 {len(recent)} 天中 {days_seen} 天），"
            f"未达 {n} 天确认阈值，保持 {last_confirmed}"
        )
        return last_confirmed

    except Exception as e:
        logger.warning(f"[REGIME] 确认逻辑异常（使用原始结果）: {e}")
        return raw_regime


async def _detect_regime() -> str:
    """
    Detect market regime，集成三项改进：
    1. 进程内缓存（30min TTL）：一个调度周期内多次调用只查一次 AV，避免 rate limit
    2. N 日确认（REGIME_CONFIRM_DAYS=3）：连续 3 天同向才切换，防单日噪声轮动
    3. 每日写入 regime_history：为过期检查和 dashboard 提供历史数据

    Returns one of: 'strong_bull', 'bull', 'choppy', 'bear'
    """
    global _regime_session
    now = _time_module.time()

    # 命中缓存：同一进程内 30 分钟内直接返回
    if _regime_session["regime"] and (now - _regime_session["ts"]) < _REGIME_CACHE_TTL:
        logger.debug(f"[REGIME] 命中缓存: {_regime_session['regime']}")
        return _regime_session["regime"]

    data = await _fetch_history(RC.REGIME_TICKER, days=80)
    if not data:
        cached = _regime_session.get("regime") or _get_last_db_regime()
        logger.warning(f"[REGIME] AV 数据获取失败，使用缓存/DB降级值: {cached}")
        return cached

    closes = data["close"]
    if len(closes) < 63:
        fallback = _regime_session.get("regime") or _get_last_db_regime()
        logger.warning(f"[REGIME] 数据不足({len(closes)}条)，使用缓存/DB降级值: {fallback}")
        return fallback

    raw_regime, raw_score = _compute_regime_score(closes)
    spy_price = float(closes[-1])
    ma50 = _compute_ma(closes, 50)
    ma20 = _compute_ma(closes, 20)

    logger.info(
        f"[REGIME] 原始检测: score={raw_score} → {raw_regime}  "
        f"(SPY={spy_price:.1f}, MA50={ma50:.1f}, MA20={ma20:.1f})"
    )

    # N 日确认 + 写入 regime_history
    confirmed = await _confirm_regime(raw_regime, raw_score, spy_price)
    if confirmed != raw_regime:
        logger.info(f"[REGIME] 平滑后: {confirmed}（原始 {raw_regime} 尚未满足 {RC.REGIME_CONFIRM_DAYS} 天确认）")

    # 更新缓存
    _regime_session = {"regime": confirmed, "ts": now}
    return confirmed


async def detect_regime_details() -> dict:
    """
    返回 regime 的详细诊断信息，用于 Regime Transition Map 可视化。
    包含：当前 regime、总分、每个信号的贡献、以及到相邻 regime 的距离。
    """
    data = await _fetch_history(RC.REGIME_TICKER, days=80)
    if not data:
        fallback = _get_last_db_regime()
        return {"regime": fallback, "score": 0, "signals": [], "transitions": {}, "error": "no_data"}

    closes = data["close"]
    if len(closes) < 63:
        fallback = _get_last_db_regime()
        return {"regime": fallback, "score": 0, "signals": [], "transitions": {}, "error": "insufficient_data"}

    ma50 = _compute_ma(closes, 50)
    ma20 = _compute_ma(closes, 20)
    current = float(closes[-1])

    vol_arr = np.diff(closes[-22:]) / closes[-22:-1] if len(closes) > 22 else np.array([0])
    vol_21d = float(np.std(vol_arr) * np.sqrt(252))

    ret_1m = (current / float(closes[-22])) - 1 if len(closes) > 22 else 0

    # --- 逐信号计算 ---
    signals = []

    # Signal 1: SPY vs MA50
    spy_ma50_pct = (current / ma50 - 1) * 100  # e.g. +2.3%
    if current > ma50 * 1.02:
        s1 = 2
    elif current > ma50:
        s1 = 1
    elif current < ma50 * 0.98:
        s1 = -2
    else:
        s1 = -1
    signals.append({
        "name": "SPY vs MA50",
        "description": "趋势方向",
        "value": round(spy_ma50_pct, 2),
        "unit": "%",
        "contribution": s1,
        "range": [-2, 2],
        "thresholds": [
            {"label": "强看空", "condition": "< -2%", "points": -2, "met": current < ma50 * 0.98},
            {"label": "看空", "condition": "-2% ~ 0%", "points": -1, "met": ma50 * 0.98 <= current < ma50},
            {"label": "看多", "condition": "0% ~ +2%", "points": 1, "met": ma50 <= current < ma50 * 1.02},
            {"label": "强看多", "condition": "> +2%", "points": 2, "met": current >= ma50 * 1.02},
        ],
        "key_levels": {"MA50": round(ma50, 2), "+2%线": round(ma50 * 1.02, 2), "-2%线": round(ma50 * 0.98, 2)},
    })

    # Signal 2: SPY vs MA20
    spy_ma20_pct = (current / ma20 - 1) * 100
    s2 = 1 if current > ma20 else -1
    signals.append({
        "name": "SPY vs MA20",
        "description": "短期动量",
        "value": round(spy_ma20_pct, 2),
        "unit": "%",
        "contribution": s2,
        "range": [-1, 1],
        "thresholds": [
            {"label": "看空", "condition": "< MA20", "points": -1, "met": current <= ma20},
            {"label": "看多", "condition": "> MA20", "points": 1, "met": current > ma20},
        ],
        "key_levels": {"MA20": round(ma20, 2)},
    })

    # Signal 3: 21d Volatility
    vol_pct = round(vol_21d * 100, 1)
    if vol_21d > 0.25:
        s3 = -1
    elif vol_21d < 0.12:
        s3 = 1
    else:
        s3 = 0
    signals.append({
        "name": "波动率 (21d)",
        "description": "市场压力",
        "value": vol_pct,
        "unit": "%",
        "contribution": s3,
        "range": [-1, 1],
        "thresholds": [
            {"label": "高压", "condition": "> 25%", "points": -1, "met": vol_21d > 0.25},
            {"label": "中性", "condition": "12% ~ 25%", "points": 0, "met": 0.12 <= vol_21d <= 0.25},
            {"label": "平静", "condition": "< 12%", "points": 1, "met": vol_21d < 0.12},
        ],
        "key_levels": {"高压线": 25.0, "平静线": 12.0},
    })

    # Signal 4: 1M Return
    ret_pct = round(ret_1m * 100, 1)
    if ret_1m > 0.03:
        s4 = 1
    elif ret_1m < -0.03:
        s4 = -1
    else:
        s4 = 0
    signals.append({
        "name": "1个月回报",
        "description": "动量确认",
        "value": ret_pct,
        "unit": "%",
        "contribution": s4,
        "range": [-1, 1],
        "thresholds": [
            {"label": "下跌", "condition": "< -3%", "points": -1, "met": ret_1m < -0.03},
            {"label": "中性", "condition": "-3% ~ +3%", "points": 0, "met": -0.03 <= ret_1m <= 0.03},
            {"label": "上涨", "condition": "> +3%", "points": 1, "met": ret_1m > 0.03},
        ],
        "key_levels": {"上涨线": 3.0, "下跌线": -3.0},
    })

    score = s1 + s2 + s3 + s4

    if score >= 4:
        regime = "strong_bull"
    elif score >= 1:
        regime = "bull"
    elif score >= -1:
        regime = "choppy"
    else:
        regime = "bear"

    # --- 到各 regime 边界的距离 ---
    # score thresholds: strong_bull >= 4, bull >= 1, choppy >= -1, bear < -1
    transitions = {
        "strong_bull": {"threshold": 4, "distance": 4 - score, "direction": "up"},
        "bull":        {"threshold": 1, "distance": 1 - score, "direction": "up" if score < 1 else "down"},
        "choppy":      {"threshold": -1, "distance": -1 - score, "direction": "up" if score < -1 else "down"},
        "bear":        {"threshold": -2, "distance": score - (-2), "direction": "down"},
    }

    return {
        "regime": regime,
        "score": score,
        "score_range": [-5, 5],
        "spy_price": round(current, 2),
        "signals": signals,
        "transitions": transitions,
        "regime_thresholds": [
            {"regime": "strong_bull", "label": "强牛市", "min_score": 4, "max_score": 5},
            {"regime": "bull", "label": "牛市", "min_score": 1, "max_score": 3},
            {"regime": "choppy", "label": "震荡市", "min_score": -1, "max_score": 0},
            {"regime": "bear", "label": "熊市", "min_score": -5, "max_score": -2},
        ],
    }


async def _score_ticker(item: dict, regime: str, ks=None,
                        spy_closes: Optional[np.ndarray] = None,
                        ml_store: Optional[dict] = None) -> Optional[RotationScore]:
    """
    Compute multi-factor score for a single ticker via unified MultiFactorScorer.
    Fetches OHLCV + fundamental/earnings/cashflow/sentiment data from knowledge base.
    """
    from app.services.multi_factor_scorer import compute_multi_factor_score

    ticker = item["ticker"]
    data = await _fetch_history(ticker)
    if not data:
        return None

    closes = data["close"]
    volumes = data["volume"]
    highs = data["high"]
    lows = data["low"]

    # Fetch fundamental data from knowledge base
    overview = None
    earnings_data = None
    cashflow_data = None
    sentiment_value = None
    sector_returns = None
    sector_flow = None

    if ks:
        try:
            factor_data = await ks.get_factor_data_for_scorer(ticker)
            overview = factor_data.get("overview")
            earnings_data = factor_data.get("earnings_data")
            cashflow_data = factor_data.get("cashflow_data")
            sentiment_value = factor_data.get("sentiment_value")
            sector_returns = factor_data.get("sector_returns")
            sector_flow = factor_data.get("sector_flow")
        except Exception:
            pass

    # Unified multi-factor scoring
    result = compute_multi_factor_score(
        closes=closes,
        volumes=volumes,
        highs=highs,
        lows=lows,
        spy_closes=spy_closes,
        regime=regime,
        overview=overview,
        earnings_data=earnings_data,
        cashflow_data=cashflow_data,
        sentiment_value=sentiment_value,
        sector_returns=sector_returns,
        sector_flow=sector_flow,
        ticker_sector=item.get("sector", ""),
    )

    score = result["total_score"]
    factors = result["factors"]

    # ── 为 ML-V3A 存储完整 scorer_result + OHLCV（供重排使用）──
    if ml_store is not None:
        ml_store[ticker] = {
            "result": result,
            "closes": closes,
            "volumes": volumes,
            "highs": highs,
        }

    # Extract components from MultiFactorScorer output
    mom = factors.get("momentum", {})
    trend = factors.get("trend", {})

    # Determine asset type
    t_set = {e["ticker"] for e in OFFENSIVE_ETFS}
    d_set = {e["ticker"] for e in DEFENSIVE_ETFS}
    i_set = {e["ticker"] for e in INVERSE_ETFS}
    if ticker in t_set:
        asset_type = "etf_offensive"
    elif ticker in d_set:
        asset_type = "etf_defensive"
    elif ticker in i_set:
        asset_type = "inverse_etf"
    else:
        asset_type = "stock"

    return RotationScore(
        ticker=ticker,
        name=item.get("name", ""),
        asset_type=asset_type,
        sector=normalize_sector(item.get("sector", "")),
        return_1w=mom.get("ret_1w", 0),
        return_1m=mom.get("ret_1m", 0),
        return_3m=mom.get("ret_3m", 0),
        volatility=mom.get("vol", 0),
        above_ma20=trend.get("above_ma20", False),
        score=score,
        current_price=float(closes[-1]),
    )


async def _score_inverse_etfs(regime: str) -> list[RotationScore]:
    """
    Score inverse ETFs by underlying index weakness (NOT multi-factor).
    Fetches SPY/QQQ/IWM/DIA returns; the weaker the index, the higher
    the corresponding inverse ETF scores.
    """
    from app.config.rotation_watchlist import INVERSE_ETF_INDEX_MAP, INVERSE_ETFS

    index_weakness: dict[str, dict] = {}
    for inv_etf in INVERSE_ETFS:
        idx_ticker = INVERSE_ETF_INDEX_MAP.get(inv_etf["ticker"])
        if not idx_ticker:
            continue
        data = await _fetch_history(idx_ticker, days=RC.LOOKBACK_DAYS)
        if not data or len(data["close"]) < 21:
            continue
        closes = data["close"]
        ret_1w = _compute_return(closes, 5)
        ret_1m = _compute_return(closes, 21)
        # Higher weakness = index dropped more = inverse ETF more attractive
        weakness = -(0.4 * ret_1w + 0.6 * ret_1m)
        index_weakness[inv_etf["ticker"]] = {
            "weakness": weakness,
            "idx_ret_1w": ret_1w,
            "idx_ret_1m": ret_1m,
        }

    scores: list[RotationScore] = []
    for inv_etf in INVERSE_ETFS:
        tk = inv_etf["ticker"]
        if tk not in index_weakness:
            continue
        w = index_weakness[tk]
        # Fetch the inverse ETF's own price data for display fields
        inv_data = await _fetch_history(tk, days=RC.LOOKBACK_DAYS)
        if not inv_data or len(inv_data["close"]) < 21:
            continue
        inv_closes = inv_data["close"]

        score = round(w["weakness"] * 10, 2)  # Scale to match multi-factor range

        scores.append(RotationScore(
            ticker=tk,
            name=inv_etf["name"],
            asset_type="inverse_etf",
            sector=normalize_sector(inv_etf.get("sector", "")),
            return_1w=_compute_return(inv_closes, 5),
            return_1m=_compute_return(inv_closes, 21),
            return_3m=_compute_return(inv_closes, 63) if len(inv_closes) >= 63 else 0,
            volatility=_compute_volatility(inv_closes),
            above_ma20=float(inv_closes[-1]) > _compute_ma(inv_closes, 20),
            score=score,
            current_price=float(inv_closes[-1]),
        ))

    logger.info(f"Inverse ETF scores (index weakness): {[(s.ticker, s.score) for s in scores]}")
    return scores


# ============================================================
# 信号过期检查（替代旧的 VIX Spike Guard）
# ============================================================

async def _check_signal_staleness() -> tuple[bool, str]:
    """
    信号过期检查：对比最新轮动快照生成时的 regime 与当前 regime。

    原理：信号过期的本质不是 VIX 涨了多少，而是"生成信号时的市场结构"
    与"现在的市场结构"是否一致。VIX 10% 日涨幅与此无关（且触发频率过高）。

    触发条件：snapshot.regime ≠ 当前 confirmed regime
    fail-open：若无快照或检测异常，不阻断执行（返回 False）。
    """
    try:
        db = get_db()
        snap = (db.table("rotation_snapshots")
                .select("regime, snapshot_date")
                .order("snapshot_date", desc=True)
                .limit(1)
                .execute())
        if not snap.data:
            logger.info("[STALENESS] 无轮动快照，跳过检查（fail-open）")
            return False, ""

        snapshot_regime = snap.data[0].get("regime", "")
        snapshot_date   = snap.data[0].get("snapshot_date", "")
        if not snapshot_regime:
            return False, ""

        current_regime = await _detect_regime()

        if snapshot_regime != current_regime:
            reason = (
                f"信号过期：快照生成时 regime={snapshot_regime}（{snapshot_date}），"
                f"当前 regime={current_regime} — 市场结构已发生切换，"
                f"请确认信号方向后再执行"
            )
            logger.warning(f"[STALENESS] {reason}")
            return True, reason

        logger.info(f"[STALENESS] regime 一致（{current_regime}），信号有效")
        return False, ""
    except Exception as e:
        logger.warning(f"[STALENESS] 检查异常（fail-open，继续执行）: {e}")
        return False, ""


# ============================================================
# 2. DAILY ENTRY CHECK
# ============================================================

async def run_daily_entry_check() -> list[DailyTimingSignal]:
    """
    Daily entry confirmation for pending_entry positions.
    Conditions: close > MA5 AND volume > 20-day avg.
    前置检查：VIX 日涨幅 > 10% 时暂停所有入场，防止执行基于过期信号的错误方向交易。

    自动递补机制：
    - 当 pending_entry 连续 ENTRY_FALLBACK_AFTER_DAYS 天未通过进场检查时，
      从快照 backup 候选（BACKUP_DEPTH）中找下一个符合 MA5+Volume 条件的股票替换。
    - 避免因单只股票迟迟不满足条件而浪费整周的槽位。
    """
    logger.info("Starting Daily Entry Check")
    signals: list[DailyTimingSignal] = []

    # ── 信号过期检查（regime 是否已切换）──────────────────────────────────────
    _stale, _stale_reason = await _check_signal_staleness()
    if _stale:
        logger.warning(f"[ENTRY CHECK PAUSED] {_stale_reason}")
        return signals  # 不执行任何入场，返回空信号列表

    positions = await _get_positions_by_status("pending_entry")
    if not positions:
        logger.info("No pending_entry positions")
        return signals

    # Detect current regime for regime-aware ATR multipliers
    regime = await _detect_regime()
    stop_mult = RC.ATR_STOP_BY_REGIME.get(regime, RC.ATR_STOP_MULTIPLIER)
    target_mult = RC.ATR_TARGET_BY_REGIME.get(regime, RC.ATR_TARGET_MULTIPLIER)
    logger.info(f"Entry check regime={regime}: stop_mult={stop_mult}, target_mult={target_mult}")

    # ── 预加载信号原价（用于 ATR 漂移验证）──────────────────────────────────
    # 从最新轮动快照的 scores 里取每只股票的 current_price（即信号生成时价格）。
    # 与 midweek_replacement 保持一致：>1 ATR 漂移则跳过，防追高/信号失效入场。
    _snapshot_signal_prices: dict[str, float] = {}
    try:
        _snap = (get_db().table("rotation_snapshots")
                 .select("scores")
                 .order("snapshot_date", desc=True)
                 .limit(1)
                 .execute())
        if _snap.data:
            for _s in (_snap.data[0].get("scores") or []):
                if _s.get("ticker") and float(_s.get("current_price", 0)) > 0:
                    _snapshot_signal_prices[_s["ticker"]] = float(_s["current_price"])
        logger.info(f"[ENTRY DRIFT] 已加载 {len(_snapshot_signal_prices)} 只快照信号价")
    except Exception as _e:
        logger.warning(f"[ENTRY DRIFT] 快照价格加载失败（跳过漂移检查）: {_e}")

    for pos in positions:
        ticker = pos["ticker"]
        data = await _fetch_history(ticker, days=30)
        if not data:
            continue

        closes = data["close"]
        volumes = data["volume"]
        highs = data["high"]
        lows = data["low"]

        ma5 = _compute_ma(closes, RC.ENTRY_MA_PERIOD)
        avg_vol = float(np.mean(volumes[-RC.ENTRY_VOL_PERIOD:])) if len(volumes) >= RC.ENTRY_VOL_PERIOD else 0

        current_price = float(closes[-1])
        current_vol = float(volumes[-1])

        conditions = []
        above_ma5 = current_price > ma5
        vol_ok = current_vol > avg_vol if avg_vol > 0 else False

        if above_ma5:
            conditions.append(f"close ${current_price:.2f} > MA5 ${ma5:.2f}")
        if vol_ok:
            conditions.append(f"vol {current_vol/1e6:.1f}M > avg {avg_vol/1e6:.1f}M")

        if above_ma5 and vol_ok:
            # Entry confirmed — compute ATR stop/target (regime-aware)
            atr = _compute_atr(highs, lows, closes)

            # ── ATR 漂移验证（与 midweek_replacement 一致）────────────────
            _signal_price = _snapshot_signal_prices.get(ticker, 0.0)
            if _signal_price > 0 and atr > 0:
                _drift = current_price - _signal_price
                _drift_atr = abs(_drift) / atr
                if current_price > _signal_price + 1.0 * atr:
                    logger.info(
                        f"[ENTRY DRIFT] {ticker} 追高 {_drift_atr:.2f} ATR "
                        f"(信号=${_signal_price:.2f} 当前=${current_price:.2f})，跳过入场"
                    )
                    continue
                if current_price < _signal_price - 1.0 * atr:
                    logger.info(
                        f"[ENTRY DRIFT] {ticker} 信号失效 {_drift_atr:.2f} ATR "
                        f"(信号=${_signal_price:.2f} 当前=${current_price:.2f})，跳过入场"
                    )
                    continue
                conditions.append(f"drift={_drift:+.2f} ({_drift_atr:.2f}ATR)")
            # ────────────────────────────────────────────────────────────────

            stop_loss = current_price - stop_mult * atr
            take_profit = current_price + target_mult * atr

            signal = DailyTimingSignal(
                ticker=ticker,
                signal_type="entry",
                trigger_conditions=conditions,
                current_price=current_price,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
            )
            signals.append(signal)

            # NOTE: 不自动激活持仓。仅发出信号供人工决策是否下单。
            logger.info(f"ENTRY signal (no auto-activate): {ticker} @ ${current_price:.2f} "
                         f"SL=${stop_loss:.2f} TP=${take_profit:.2f}")
        else:
            # Check if fallback or max wait exceeded
            created = pos.get("created_at", "")
            days_waiting = _days_since(created)

            if days_waiting >= RC.ENTRY_MAX_WAIT_DAYS:
                await _close_position(pos["id"], reason="entry_timeout")
                logger.info(f"Entry timeout for {ticker} after {days_waiting} days, closing position")

            elif days_waiting >= RC.ENTRY_FALLBACK_AFTER_DAYS:
                # ── 自动递补：从快照 backup 找下一个满足条件的候选 ──
                logger.info(f"[FALLBACK] {ticker} 已等 {days_waiting} 天未进场，尝试递补")
                fallback_signal = await _try_entry_fallback(
                    pos, _snapshot_signal_prices, regime, stop_mult, target_mult
                )
                if fallback_signal:
                    signals.append(fallback_signal)

    return signals


async def _try_entry_fallback(
    stale_pos: dict,
    snapshot_signal_prices: dict[str, float],
    regime: str,
    stop_mult: float,
    target_mult: float,
) -> DailyTimingSignal | None:
    """
    自动递补：当 pending_entry 连续 N 天未通过进场检查时，
    从快照 backup 候选中找下一个满足全部验证的股票替换。

    流程：
    1. 读取最新快照的全量打分（BACKUP_DEPTH 范围内）
    2. 排除已持有/pending 的 ticker
    3. 基本面质量硬卡（EPS + 现金流），不过直接跳过
    4. 强制重新评分 + MIN_SCORE_BY_REGIME 校验
    5. 逐个验证 MA5 + Volume + ATR漂移
    6. 第一个通过的 → 关闭原 pending_entry(replaced_by_fallback)，新建 pending_entry 并发出信号
    """
    stale_ticker = stale_pos["ticker"]
    db = get_db()

    # 1. 取最新快照的全量打分
    try:
        snap_result = (
            db.table("rotation_snapshots")
            .select("id, scores, snapshot_date")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not snap_result.data:
            return None
        snapshot_row = snap_result.data[0]
        snapshot_id = snapshot_row.get("id")
        scores = snapshot_row.get("scores") or []
    except Exception as e:
        logger.error(f"[FALLBACK] 快照读取失败: {e}")
        return None

    if not scores:
        return None

    # 2. 收集所有已占用的 ticker（active + pending_entry + pending_exit）
    from app.config.rotation_watchlist import INVERSE_ETF_INDEX_MAP
    _hedge_set = set(INVERSE_ETF_INDEX_MAP.keys())

    active = await _get_positions_by_status("active")
    pending_entry = await _get_positions_by_status("pending_entry")
    pending_exit = await _get_positions_by_status("pending_exit")
    occupied_tickers = {p["ticker"] for p in active + pending_entry + pending_exit}

    # 3. 按分数排序，取 BACKUP_DEPTH 范围内的非占用候选
    sorted_scores = sorted(scores, key=lambda s: s.get("score", 0), reverse=True)
    candidates = [
        s for s in sorted_scores[:RC.BACKUP_DEPTH]
        if s.get("ticker") not in occupied_tickers
        and s.get("ticker") != stale_ticker
        and s.get("ticker") not in _hedge_set
    ]

    if not candidates:
        logger.info(f"[FALLBACK] {stale_ticker}: 无可用递补候选")
        return None

    # ── 准备基本面验证 + 重新评分所需的服务 ──
    from app.services.knowledge_service import get_knowledge_service
    ks = get_knowledge_service()
    min_score = RC.MIN_SCORE_BY_REGIME.get(regime, RC.MIN_SCORE_THRESHOLD)

    # 4. 逐个验证：基本面 → 重新评分 → MA5 + Volume + ATR漂移
    for candidate in candidates:
        ticker = candidate.get("ticker", "")
        signal_price = float(candidate.get("current_price", 0))
        if not ticker or signal_price <= 0:
            continue

        # ── 4a. 基本面质量硬卡（与 universe_service 同标准） ──
        try:
            factor_data = await ks.get_factor_data_for_scorer(ticker)
            earnings_data = factor_data.get("earnings_data")
            cashflow_data = factor_data.get("cashflow_data")

            # EPS 检查：最近4季中至少 N 季 > 0
            if not earnings_data or not earnings_data.get("quarterly"):
                logger.info(f"[FALLBACK] {ticker}: 无盈利数据，跳过")
                continue
            e_quarters = earnings_data["quarterly"]
            eps_pos = sum(
                1 for q in e_quarters[:4]
                if q.get("reported_eps") is not None and q["reported_eps"] > 0
            )
            if eps_pos < RC.UNIVERSE_QUALITY_EPS_MIN_POSITIVE:
                logger.info(
                    f"[FALLBACK] {ticker}: 基本面不合格 — EPS正数{eps_pos}/4季 "
                    f"(需≥{RC.UNIVERSE_QUALITY_EPS_MIN_POSITIVE})，跳过"
                )
                continue

            # 现金流检查：最近2季中至少 N 季 OperatingCF > 0
            if not cashflow_data or not cashflow_data.get("quarterly"):
                logger.info(f"[FALLBACK] {ticker}: 无现金流数据，跳过")
                continue
            c_quarters = cashflow_data["quarterly"]
            cf_pos = sum(
                1 for q in c_quarters[:2]
                if q.get("operating_cashflow") is not None and q["operating_cashflow"] > 0
            )
            if cf_pos < RC.UNIVERSE_QUALITY_CF_MIN_POSITIVE:
                logger.info(
                    f"[FALLBACK] {ticker}: 基本面不合格 — CF正数{cf_pos}/2季 "
                    f"(需≥{RC.UNIVERSE_QUALITY_CF_MIN_POSITIVE})，跳过"
                )
                continue
        except Exception as e:
            logger.warning(f"[FALLBACK] {ticker}: 基本面验证异常 ({e})，保守跳过")
            continue

        # ── 4b. 强制重新评分（实时数据，非快照旧分数） ──
        try:
            fresh_score = await _score_ticker(
                {"ticker": ticker, "sector": candidate.get("sector", "")},
                regime, ks,
            )
            if not fresh_score:
                logger.info(f"[FALLBACK] {ticker}: 重新评分失败，跳过")
                continue
            live_score = fresh_score.score
            if live_score < min_score:
                logger.info(
                    f"[FALLBACK] {ticker}: 实时评分 {live_score:.3f} < "
                    f"MIN_SCORE({regime})={min_score:.2f}，跳过"
                )
                continue
        except Exception as e:
            logger.warning(f"[FALLBACK] {ticker}: 重新评分异常 ({e})，跳过")
            continue

        # ── 4c. 技术面验证：MA5 + Volume + ATR漂移 ──
        data = await _fetch_history(ticker, days=30)
        if not data:
            continue

        closes = data["close"]
        volumes = data["volume"]
        highs = data["high"]
        lows = data["low"]

        ma5 = _compute_ma(closes, RC.ENTRY_MA_PERIOD)
        avg_vol = float(np.mean(volumes[-RC.ENTRY_VOL_PERIOD:])) if len(volumes) >= RC.ENTRY_VOL_PERIOD else 0
        current_price = float(closes[-1])
        current_vol = float(volumes[-1])

        above_ma5 = current_price > ma5
        vol_ok = current_vol > avg_vol if avg_vol > 0 else False

        if not (above_ma5 and vol_ok):
            logger.info(f"[FALLBACK] {ticker}: MA5={'✅' if above_ma5 else '❌'} Vol={'✅' if vol_ok else '❌'}，跳过")
            continue

        # ATR 漂移检查
        atr = _compute_atr(highs, lows, closes)
        if atr > 0 and signal_price > 0:
            drift_atr = abs(current_price - signal_price) / atr
            if current_price > signal_price + 1.0 * atr:
                logger.info(f"[FALLBACK] {ticker}: 追高 {drift_atr:.2f} ATR，跳过")
                continue
            if current_price < signal_price - 1.0 * atr:
                logger.info(f"[FALLBACK] {ticker}: 信号失效 {drift_atr:.2f} ATR，跳过")
                continue

        # ✅ 递补成功：关闭原 pending_entry，新建递补 pending_entry
        stop_loss = round(current_price - stop_mult * atr, 2)
        take_profit = round(current_price + target_mult * atr, 2)

        await _close_position(stale_pos["id"], reason="replaced_by_fallback")
        logger.info(f"[FALLBACK] 关闭 {stale_ticker} (replaced_by_fallback)")

        try:
            row: dict = {
                "ticker": ticker,
                "status": "pending_entry",
                "notes": f"fallback from {stale_ticker} | rescore={live_score:.3f} regime={regime}",
            }
            if snapshot_id:
                row["snapshot_id"] = snapshot_id
            db.table("rotation_positions").insert(row).execute()
        except Exception as e:
            logger.error(f"[FALLBACK] 创建 {ticker} pending_entry 失败: {e}")
            return None

        conditions = [
            f"close ${current_price:.2f} > MA5 ${ma5:.2f}",
            f"vol {current_vol/1e6:.1f}M > avg {avg_vol/1e6:.1f}M",
            f"rescore {live_score:.3f} ≥ min {min_score:.2f} ({regime})",
            f"EPS+{eps_pos}/4季 CF+{cf_pos}/2季",
            f"fallback from {stale_ticker}",
        ]

        signal = DailyTimingSignal(
            ticker=ticker,
            signal_type="entry",
            trigger_conditions=conditions,
            current_price=current_price,
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        logger.info(
            f"[FALLBACK] ✅ {stale_ticker} → {ticker} @ ${current_price:.2f} "
            f"SL=${stop_loss} TP=${take_profit} (rescore={live_score:.3f}, "
            f"EPS+{eps_pos}/4, CF+{cf_pos}/2)"
        )
        return signal

    logger.info(f"[FALLBACK] {stale_ticker}: 所有 backup 候选均未通过递补验证（基本面+评分+技术面）")
    return None


# ============================================================
# 3. DAILY EXIT CHECK
# ============================================================

async def run_daily_exit_check() -> list[DailyTimingSignal]:
    """
    Daily exit check for active positions.
    - ATR stop loss: close < entry - 2*ATR       （VIX spike 时仍执行）
    - ATR take profit: close > entry + 3*ATR     （VIX spike 时仍执行）
    - Rotation exit: kicked from top N AND close < MA5  （VIX spike 时暂停）
    VIX 涨幅 > 10% 时，只允许止损/止盈出场，禁止基于过期轮动信号的 rotation_exit。
    """
    logger.info("Starting Daily Exit Check")
    signals: list[DailyTimingSignal] = []

    positions = await _get_positions_by_status("active")
    if not positions:
        logger.info("No active positions")
        return signals

    # ── 信号过期检查（仅屏蔽 rotation_exit，SL/TP 不受影响）────────────────
    _stale, _stale_reason = await _check_signal_staleness()
    if _stale:
        logger.warning(f"[EXIT CHECK] rotation_exit 已暂停（regime 已切换）：{_stale_reason}")

    # Get current top N for rotation exit check
    current_selected = await _get_latest_selected()

    for pos in positions:
        # ── Hedge 仓位跳过所有 SL/TP / rotation_exit 检查 ──────────────────
        # Hedge（如 RWM）是战略对冲层，只随 regime 切换时由 _manage_positions_on_rotation 管理退出。
        # 若被 ATR 止损踢出，熊市对冲层将在最需要的时候缺位。
        if pos.get("position_type") == "hedge":
            logger.debug(f"[EXIT] {pos.get('ticker')} 是 hedge 仓位，跳过 SL/TP/rotation_exit 检查")
            continue

        ticker = pos["ticker"]
        entry_price = float(pos.get("entry_price", 0))
        stop_loss = float(pos.get("stop_loss", 0))
        take_profit = float(pos.get("take_profit", 0))

        atr14 = float(pos.get("atr14", 0) or 0)
        highest_price = float(pos.get("highest_price", 0) or 0)

        data = await _fetch_history(ticker, days=30)
        if not data:
            continue

        closes = data["close"]
        current_price = float(closes[-1])

        # Update highest price for trailing stop
        if highest_price <= 0:
            highest_price = max(current_price, entry_price)
        else:
            highest_price = max(highest_price, current_price)

        # Update current price + highest_price in DB
        pnl_pct = (current_price / entry_price - 1.0) if entry_price > 0 else 0.0
        await _update_position_price(pos["id"], current_price, pnl_pct,
                                     highest_price=highest_price)

        exit_reason = None
        conditions = []

        # Compute effective stop (static or trailing, whichever is higher)
        effective_sl = stop_loss
        if RC.TRAILING_STOP_ENABLED and atr14 > 0 and entry_price > 0:
            profit = highest_price - entry_price
            if profit >= RC.TRAILING_ACTIVATE_ATR * atr14:
                trailing_sl = highest_price - RC.TRAILING_STOP_ATR_MULT * atr14
                if trailing_sl > effective_sl:
                    effective_sl = trailing_sl

        # Check stop loss (static or trailing)
        if effective_sl > 0 and current_price < effective_sl:
            is_trailing = effective_sl > stop_loss
            exit_reason = "trailing_stop" if is_trailing else "stop_loss"
            conditions.append(f"close ${current_price:.2f} < {'TSL' if is_trailing else 'SL'} ${effective_sl:.2f}"
                              f" (high=${highest_price:.2f})")

        # Check take profit
        elif take_profit > 0 and current_price > take_profit:
            exit_reason = "take_profit"
            conditions.append(f"close ${current_price:.2f} > TP ${take_profit:.2f}")

        # Check rotation exit: not in top N AND below MA5
        # regime 已切换时跳过：信号基于过期结构，方向未必正确
        elif ticker not in current_selected and not _stale:
            ma5 = _compute_ma(closes, RC.ENTRY_MA_PERIOD)
            if current_price < ma5:
                exit_reason = "rotation_exit"
                conditions.append(f"not in top {RC.TOP_N}")
                conditions.append(f"close ${current_price:.2f} < MA5 ${ma5:.2f}")

        if exit_reason:
            signal = DailyTimingSignal(
                ticker=ticker,
                signal_type="exit",
                trigger_conditions=conditions,
                current_price=current_price,
                entry_price=entry_price,
                exit_reason=exit_reason,
            )
            signals.append(signal)

            pos_qty = int(pos.get("quantity", 0) or 0)
            await _close_position(pos["id"], reason=exit_reason,
                                  exit_price=current_price,
                                  ticker=ticker, quantity=pos_qty)
            logger.info(f"EXIT {exit_reason}: {ticker} @ ${current_price:.2f} "
                         f"(entry ${entry_price:.2f}, pnl {pnl_pct:+.1%})")

    return signals


# ============================================================
# 4. MID-WEEK REPLACEMENT
# ============================================================

async def run_midweek_replacement() -> list[dict]:
    """
    周中补位：当持仓在周中退出后，从本周轮动备选名单中找替代仓位。

    信号有效性验证（ATR漂移检测）：
    - drift < 0.5 ATR  → 有效，直接建仓
    - drift 0.5~1.0 ATR → 有效，按当前价重算 SL/TP
    - drift > 1.0 ATR  → 无效，跳过找下一候选

    方向判断：
    - 当前价 > 信号价 + 1 ATR → 追高风险，跳过
    - 当前价 < 信号价 - 1 ATR → 信号失效，跳过
    """
    logger.info("Starting Mid-week Replacement Check")
    replacements = []

    # 1. 统计当前仓位占用（active + pending_entry 占槽，pending_exit 正在退出不计）
    # hedge ETF（SH/PSQ/RWM/DOG）不占 alpha TOP_N 名额，独立管理
    active = await _get_positions_by_status("active")
    pending_entry = await _get_positions_by_status("pending_entry")
    pending_exit = await _get_positions_by_status("pending_exit")

    from app.config.rotation_watchlist import INVERSE_ETF_INDEX_MAP
    _hedge_set = set(INVERSE_ETF_INDEX_MAP.keys())

    occupied_tickers = {p["ticker"] for p in active + pending_entry + pending_exit}
    occupied_count = sum(1 for p in active + pending_entry if p["ticker"] not in _hedge_set)

    if occupied_count >= RC.TOP_N:
        logger.info(f"Mid-week replacement: no open alpha slots ({occupied_count}/{RC.TOP_N}), skip")
        return replacements

    open_slots = RC.TOP_N - occupied_count
    logger.info(f"Mid-week replacement: {open_slots} open slot(s), occupied={occupied_tickers}")

    # 2. 读取最新轮动快照的全量打分（按 created_at 排序，避免同日多快照歧义）
    try:
        db = get_db()
        snap_result = (
            db.table("rotation_snapshots")
            .select("id, scores, snapshot_date, regime")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not snap_result.data:
            logger.info("Mid-week replacement: no rotation snapshot found")
            return replacements
        snapshot_row = snap_result.data[0]
        snapshot_id = snapshot_row.get("id")
        snapshot_date = snapshot_row.get("snapshot_date", "")
        scores = snapshot_row.get("scores") or []
    except Exception as e:
        logger.error(f"Mid-week replacement: error fetching snapshot: {e}")
        return replacements

    if not scores:
        logger.info("Mid-week replacement: snapshot has no scores")
        return replacements

    # 3. 按分数降序排列，过滤已占用的 ticker
    candidates = sorted(
        [s for s in scores if s.get("ticker") not in occupied_tickers],
        key=lambda s: s.get("score", 0),
        reverse=True,
    )

    if not candidates:
        logger.info("Mid-week replacement: no backup candidates available")
        return replacements

    # 4. 当前 Regime 的 SL/TP 乘数
    regime = await _detect_regime()
    stop_mult = RC.ATR_STOP_BY_REGIME.get(regime, RC.ATR_STOP_MULTIPLIER)
    target_mult = RC.ATR_TARGET_BY_REGIME.get(regime, RC.ATR_TARGET_MULTIPLIER)

    # 5. 逐一验证候选，填满空槽
    slots_filled = 0
    for candidate in candidates:
        if slots_filled >= open_slots:
            break

        ticker = candidate.get("ticker", "")
        signal_price = float(candidate.get("current_price", 0))

        if not ticker or signal_price <= 0:
            continue

        # 拉取历史数据计算当前价格和 ATR
        data = await _fetch_history(ticker, days=30)
        if not data:
            logger.info(f"Mid-week replacement: no history for {ticker}, skip")
            continue

        closes = data["close"]
        highs = data["high"]
        lows = data["low"]
        current_price = float(closes[-1])
        atr14 = _compute_atr(highs, lows, closes)

        if atr14 <= 0:
            logger.info(f"Mid-week replacement: ATR=0 for {ticker}, skip")
            continue

        # ATR 漂移检测
        price_drift = abs(current_price - signal_price)
        drift_in_atr = price_drift / atr14

        if current_price > signal_price + 1.0 * atr14:
            logger.info(
                f"Mid-week replacement: {ticker} drifted UP {drift_in_atr:.2f} ATR "
                f"(signal=${signal_price:.2f} current=${current_price:.2f}), skip"
            )
            continue

        if current_price < signal_price - 1.0 * atr14:
            logger.info(
                f"Mid-week replacement: {ticker} drifted DOWN {drift_in_atr:.2f} ATR "
                f"(signal=${signal_price:.2f} current=${current_price:.2f}), skip"
            )
            continue

        # 以当前价格重算 SL/TP（保证 R:R 一致性）
        new_sl = round(current_price - stop_mult * atr14, 2)
        new_tp = round(current_price + target_mult * atr14, 2)

        # 创建 pending_entry
        try:
            row: dict = {"ticker": ticker, "status": "pending_entry"}
            if snapshot_id:
                row["snapshot_id"] = snapshot_id
            db.table("rotation_positions").insert(row).execute()

            logger.info(
                f"Mid-week replacement: queued pending_entry for {ticker} "
                f"signal=${signal_price:.2f} current=${current_price:.2f} "
                f"drift={drift_in_atr:.2f}ATR SL=${new_sl} TP=${new_tp} regime={regime}"
            )

            replacements.append({
                "ticker": ticker,
                "signal_price": signal_price,
                "current_price": current_price,
                "drift_in_atr": round(drift_in_atr, 2),
                "new_sl": new_sl,
                "new_tp": new_tp,
                "regime": regime,
                "snapshot_date": snapshot_date,
            })
            slots_filled += 1

        except Exception as e:
            logger.error(f"Mid-week replacement: error creating pending_entry for {ticker}: {e}")

    logger.info(f"Mid-week replacement complete: {slots_filled} replacement(s) queued")
    return replacements


# ============================================================
# 5. BACKTEST
# ============================================================

# Sector → representative ETF mapping for backtest sector_wind factor
_SECTOR_ETF_MAP = {
    "tech": "XLK",
    "semi": "SOXX",
    "bio": "IBB",
    "consumer": "XLC",      # closest proxy: Communication Services
    "industrial": "XLI",
    "fintech": "XLF",       # closest proxy: Financials
    "saas": "XLK",          # map to Technology
    "space": "XLI",         # closest proxy: Industrials
    "china": "VWO",         # closest proxy: Emerging Markets
    "ai": "XLK",            # map to Technology
}


def _compute_sector_returns_at(histories: dict, bar_index: int,
                                lookback: int = 21) -> Optional[dict]:
    """
    Compute 1-month sector returns from historical ETF data at a given bar index.
    Used in backtest to populate the sector_wind factor (instead of passing None).

    Returns: {"tech": 0.05, "semi": -0.02, ...} or None if data insufficient.
    """
    if bar_index < lookback + 1:
        return None

    sector_returns = {}
    for sector, etf in _SECTOR_ETF_MAP.items():
        h = histories.get(etf)
        if h is None or bar_index >= len(h["close"]):
            continue
        closes = h["close"]
        current = closes[bar_index]
        prev = closes[bar_index - lookback]
        if prev > 0:
            sector_returns[sector] = float((current / prev) - 1)

    return sector_returns if sector_returns else None


def _compute_relative_strength(ticker_closes: np.ndarray, spy_closes: np.ndarray,
                                period: int = 21) -> float:
    """
    Compute relative strength vs SPY over period.
    RS > 0 means outperforming SPY, RS < 0 means underperforming.
    """
    if len(ticker_closes) < period + 1 or len(spy_closes) < period + 1:
        return 0.0
    ticker_ret = (ticker_closes[-1] / ticker_closes[-period - 1]) - 1
    spy_ret = (spy_closes[-1] / spy_closes[-period - 1]) - 1
    return float(ticker_ret - spy_ret)


def _graduated_trend_bonus(closes: np.ndarray) -> float:
    """
    Graduated trend bonus based on price position relative to multiple MAs.
    Returns 0 ~ 3.0 (replaces binary MA20 bonus of 2.0).
    - Above MA10: +0.5
    - Above MA20: +1.0
    - Above MA50: +1.0
    - MA20 sloping up: +0.5
    """
    if len(closes) < 50:
        return 0.0
    bonus = 0.0
    current = float(closes[-1])
    ma10 = float(np.mean(closes[-10:]))
    ma20 = float(np.mean(closes[-20:]))
    ma50 = float(np.mean(closes[-50:]))

    if current > ma10:
        bonus += 0.5
    if current > ma20:
        bonus += 1.0
    if current > ma50:
        bonus += 1.0
    # MA20 slope: compare current MA20 vs 5 days ago MA20
    if len(closes) >= 25:
        ma20_prev = float(np.mean(closes[-25:-5]))
        if ma20 > ma20_prev:
            bonus += 0.5
    return bonus


def _apply_sector_cap(scored: list[tuple], histories: dict,
                      max_per_sector: int = RC.MAX_SECTOR_CONCENTRATION,
                      top_n: int = RC.TOP_N) -> list[str]:
    """
    Select top_n tickers with sector concentration limit.
    Returns list of selected tickers.
    """
    selected = []
    sector_count = {}
    for ticker, score in scored:
        item = histories.get(ticker, {}).get("item", {})
        sector = item.get("sector", item.get("asset_type", "etf"))
        if not sector:
            sector = "etf"
        count = sector_count.get(sector, 0)
        if count >= max_per_sector:
            continue
        selected.append(ticker)
        sector_count[sector] = count + 1
        if len(selected) >= top_n:
            break
    return selected


def _bt_entry_price(h: dict, i: int) -> float:
    """Get backtest entry price: next-day open (i+1) if enabled, else close(i)."""
    if RC.BACKTEST_NEXT_OPEN and i + 1 < len(h.get("open", h["close"])):
        return float(h.get("open", h["close"])[i + 1])
    return float(h["close"][i])


def _bt_exit_price(h: dict, i: int, step: int) -> float:
    """Get backtest exit price: close at i+step (held for full week)."""
    idx = min(i + step, len(h["close"]) - 1)
    return float(h["close"][idx])


def _score_weighted_returns(selected: list, scores_map: dict,
                            histories: dict, i: int, step: int,
                            prev_selected: list = None) -> float:
    """
    Compute score-weighted portfolio return (instead of equal weight).
    Higher scored tickers get proportionally larger allocation.
    Includes slippage for entry/exit and turnover.
    """
    weights = []
    returns = []
    slippage = RC.BACKTEST_SLIPPAGE
    added = set(selected) - set(prev_selected or [])
    removed = set(prev_selected or []) - set(selected)

    for t in selected:
        h = histories.get(t)
        if h is None or i + step >= len(h["close"]):
            continue
        entry_px = _bt_entry_price(h, i)
        exit_px = _bt_exit_price(h, i, step)
        week_ret = (exit_px / entry_px) - 1
        # Slippage: charge on entry for new positions, on exit for removed next week
        if t in added and slippage > 0:
            week_ret -= slippage  # entry slippage
        raw_score = max(scores_map.get(t, 0), 0.01)
        weights.append(raw_score)
        returns.append(week_ret)

    # Also charge exit slippage for positions being removed
    if slippage > 0 and removed:
        # Approximate: removed positions' exit slippage reduces total return
        n_total = len(selected) + len(removed)
        if n_total > 0:
            removed_slip = len(removed) * slippage / max(len(selected), 1)
            returns = [r - removed_slip / max(len(returns), 1) for r in returns]

    if not weights:
        return 0.0

    total_w = sum(weights)
    if total_w <= 0:
        return sum(returns) / len(returns) if returns else 0.0

    return sum(w / total_w * r for w, r in zip(weights, returns))


# ── Full-range OHLCV cache for sub-range slicing ──
# Stored by scheduler after weekly pre-compute; allows custom date ranges
# to slice from cached data instead of re-fetching 500 tickers from AV.
# Persisted to disk via pickle so it survives server restarts.
import os as _os
import pickle as _pickle

_PREFETCHED_FULL: dict = {}  # {"histories": {...}, "bt_fundamentals": {...}, "start": str, "end": str}

# ── ML-V3A 全局单例（懒加载，启动后第一次 run_rotation 时初始化）──
_ML_RANKER_INSTANCE = None

def _get_live_ml_ranker():
    """懒加载并缓存 ML 排序模型（仅在 USE_ML_ENHANCE=True 时调用）。"""
    global _ML_RANKER_INSTANCE
    if _ML_RANKER_INSTANCE is not None:
        return _ML_RANKER_INSTANCE
    try:
        from app.services.ml_scorer import MLRanker
        r = MLRanker()
        if r.load():
            _ML_RANKER_INSTANCE = r
            logger.info("[ML-V3A] 模型加载成功，启用 ML 重排")
        else:
            logger.info("[ML-V3A] 未找到训练模型，ML 重排禁用")
    except Exception as e:
        logger.warning(f"[ML-V3A] 模型加载失败: {e}")
    return _ML_RANKER_INSTANCE
_PREFETCHED_DISK_PATH = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
    ".cache", "prefetched_full.pkl"
)


def set_prefetched_full(data: dict, start_date: str, end_date: str):
    """Cache full-range pre-fetched data for sub-range slicing (memory + disk)."""
    global _PREFETCHED_FULL
    _PREFETCHED_FULL = {**data, "start": start_date, "end": end_date}
    logger.info(f"Cached full-range OHLCV data: {start_date} to {end_date}, "
                f"{len(data.get('histories', {}))} tickers")
    # Persist to disk
    try:
        _os.makedirs(_os.path.dirname(_PREFETCHED_DISK_PATH), exist_ok=True)
        with open(_PREFETCHED_DISK_PATH, "wb") as f:
            _pickle.dump(_PREFETCHED_FULL, f, protocol=_pickle.HIGHEST_PROTOCOL)
        size_mb = _os.path.getsize(_PREFETCHED_DISK_PATH) / 1024 / 1024
        logger.info(f"Saved prefetched data to disk ({size_mb:.1f} MB)")
    except Exception as e:
        logger.warning(f"Failed to save prefetched data to disk: {e}")


def _load_prefetched_from_disk():
    """Load cached full-range data from disk if available."""
    global _PREFETCHED_FULL
    if _PREFETCHED_FULL and "histories" in _PREFETCHED_FULL:
        return  # Already loaded
    if not _os.path.exists(_PREFETCHED_DISK_PATH):
        return
    try:
        with open(_PREFETCHED_DISK_PATH, "rb") as f:
            _PREFETCHED_FULL = _pickle.load(f)
        logger.info(f"Loaded prefetched data from disk: "
                    f"{_PREFETCHED_FULL.get('start')} to {_PREFETCHED_FULL.get('end')}, "
                    f"{len(_PREFETCHED_FULL.get('histories', {}))} tickers")
    except Exception as e:
        logger.warning(f"Failed to load prefetched data from disk: {e}")


async def run_ml_retrain(months_lookback: int = 18) -> dict:
    """
    月度 ML 模型增量重训（ML-V3A 非对称标签）。

    策略：
      - 训练窗口 = [TODAY - months_lookback 个月, TODAY - 1 个月]
      - 用动态选股池对该区间做回测，收集每周快照
      - 用非对称 z-score 标签重训 XGBRanker
      - 保存到 models/ml_ranker/ml_ranker.pkl
      - 热更新内存中的 _ML_RANKER_INSTANCE

    设计原则：
      - 只拉近 18 个月数据（AV API 负担可控，约 500 次请求 ~7 分钟）
      - 保持与 V3A 完全相同的特征/标签配置
      - 失败时 Feishu 告警，不影响生产轮动
    """
    import time as _time
    from datetime import date, timedelta
    import calendar

    logger.info("[ML-Retrain] ── 开始月度 ML 重训 ──")
    t_start = _time.time()

    # 计算训练窗口（滑动18个月）
    today = date.today()
    # 结束：上个月最后一天
    first_of_month = today.replace(day=1)
    train_end = (first_of_month - timedelta(days=1)).isoformat()
    # 开始：months_lookback 个月前
    y = today.year
    m = today.month - months_lookback
    while m <= 0:
        m += 12
        y -= 1
    train_start = date(y, m, 1).isoformat()

    logger.info(f"[ML-Retrain] 训练窗口: {train_start} → {train_end}")

    try:
        # ── 1. 拉取数据 ──
        logger.info("[ML-Retrain] 拉取历史数据...")
        prefetched = await _fetch_backtest_data(train_start, train_end)
        if "error" in prefetched:
            return {"error": f"数据拉取失败: {prefetched['error']}"}

        n_tickers = len(prefetched.get("histories", {}))
        logger.info(f"[ML-Retrain] 数据就绪: {n_tickers} 只标的")

        # ── 2. 收集训练快照（完整回测，每周快照）──
        logger.info("[ML-Retrain] 收集每周评分快照...")
        train_snapshots = []
        await run_rotation_backtest(
            start_date=train_start,
            end_date=train_end,
            _prefetched=prefetched,
            ml_enhance=False,
            _collect_snapshots=train_snapshots,
        )
        logger.info(f"[ML-Retrain] 收集到 {len(train_snapshots)} 个周快照")

        if len(train_snapshots) < 10:
            return {"error": f"快照不足（{len(train_snapshots)}），至少需要10周"}

        # ── 3. 构建训练数据（非对称 z-score 标签）──
        from app.services.ml_scorer import MLRanker, build_training_data
        X_train, y_train, groups_train = build_training_data(
            train_snapshots,
            prefetched["histories"],
            lookahead_days=5,
            asymmetric=True,  # V3A 标签
        )
        logger.info(
            f"[ML-Retrain] 训练数据: {len(X_train)} 样本, {len(groups_train)} 组"
            + (f", label [{y_train.min():.2f}, {y_train.max():.2f}]" if len(y_train) > 0 else "")
        )

        if len(X_train) < 50:
            return {"error": f"训练样本不足（{len(X_train)}），至少需要50个"}

        # ── 4. 训练模型 ──
        logger.info("[ML-Retrain] 训练 XGBRanker (V3A)...")
        ranker = MLRanker()
        metrics = ranker.train(X_train, y_train, groups_train)
        logger.info(
            f"[ML-Retrain] 训练完成: corr={metrics.get('correlation', 0):.3f}, "
            f"rank_spread={metrics.get('rank_spread_train', 0):.3f}"
        )

        # ── 5. 保存模型 ──
        ranker.save()
        logger.info("[ML-Retrain] 模型已保存到 models/ml_ranker/ml_ranker.pkl")

        # ── 6. 热更新内存实例 ──
        global _ML_RANKER_INSTANCE
        _ML_RANKER_INSTANCE = ranker
        logger.info("[ML-Retrain] 内存中 _ML_RANKER_INSTANCE 已更新")

        elapsed = _time.time() - t_start
        result = {
            "status": "success",
            "train_start": train_start,
            "train_end": train_end,
            "n_tickers": n_tickers,
            "n_snapshots": len(train_snapshots),
            "n_samples": int(len(X_train)),
            "correlation": round(metrics.get("correlation", 0), 4),
            "rank_spread": round(metrics.get("rank_spread_train", 0), 4),
            "elapsed_seconds": round(elapsed, 1),
            "trained_at": metrics.get("trained_at", ""),
        }
        logger.info(f"[ML-Retrain] ✓ 完成，耗时 {elapsed:.0f}s")

        # ── 7. Feishu 通知 ──
        try:
            from app.services.feishu_service import send_feishu_message
            top_feats = sorted(
                metrics.get("feature_importance", {}).items(),
                key=lambda x: x[1], reverse=True
            )[:3]
            feat_str = ", ".join(f"{k}={v:.3f}" for k, v in top_feats)
            await send_feishu_message(
                f"🤖 ML-V3A 月度重训完成\n"
                f"训练窗口: {train_start} ~ {train_end}\n"
                f"样本: {len(X_train)} ({len(train_snapshots)}周快照)\n"
                f"Corr: {metrics.get('correlation', 0):.3f} | "
                f"Spread: {metrics.get('rank_spread_train', 0):.3f}\n"
                f"Top特征: {feat_str}\n"
                f"耗时: {elapsed:.0f}s"
            )
        except Exception:
            pass

        return result

    except Exception as e:
        logger.error(f"[ML-Retrain] 失败: {e}", exc_info=True)
        try:
            from app.services.feishu_service import send_feishu_message
            await send_feishu_message(f"❌ ML-V3A 月度重训失败\n错误: {e}")
        except Exception:
            pass
        return {"error": str(e)}


def _build_prefetched_from_av_disk_cache(start_date: str, end_date: str) -> Optional[dict]:
    """
    当主预取缓存（2022+）不覆盖目标时间段时，尝试从 AV Client 的磁盘 OHLCV 缓存
    构建等效的 prefetched dict，支持 2018+ 历史回测。
    前提：需先运行 scripts/populate_ohlcv_cache.py 填充磁盘缓存。
    """
    import pandas as pd
    from app.services.alphavantage_client import get_av_client

    av = get_av_client()
    if not av._daily_cache:
        return None

    # 包含6个月热身期
    ts_start = pd.Timestamp(start_date) - pd.DateOffset(months=6)
    ts_end   = pd.Timestamp(end_date)

    # 取所有已缓存的 full OHLCV ticker（key 格式 "TICKER:full"）
    histories = {}
    for cache_key, entry in list(av._daily_cache.items()):
        if not cache_key.endswith(":full"):
            continue
        ticker = cache_key[:-5]  # strip ":full"
        if not ticker or ":" in ticker:
            continue  # 跳过 "daily:TICKER:full" 的旧格式key
        try:
            _, df = entry
            if not hasattr(df, "index"):
                continue
            mask = (df.index >= ts_start) & (df.index <= ts_end)
            df_s = df.loc[mask]
            if len(df_s) < 50:
                continue
            histories[ticker] = {
                "close":  df_s["Close"].values,
                "open":   df_s["Open"].values,
                "high":   df_s["High"].values,
                "low":    df_s["Low"].values,
                "volume": df_s["Volume"].values,
                "dates":  df_s.index,
                "item":   {"symbol": ticker},
            }
        except Exception:
            continue

    if len(histories) < 50 or "SPY" not in histories:
        logger.warning(
            f"[slice_prefetched] AV磁盘缓存不足以覆盖 {start_date}→{end_date}，"
            f"仅找到 {len(histories)} 支股票。请运行 scripts/populate_ohlcv_cache.py。"
        )
        return None

    logger.info(
        f"[slice_prefetched] 使用 AV 磁盘 OHLCV 缓存构建历史回测数据: "
        f"{start_date}→{end_date}, {len(histories)} tickers"
    )
    return {"histories": histories, "bt_fundamentals": {}}


def _slice_prefetched(start_date: str, end_date: str) -> Optional[dict]:
    """
    Slice the cached full-range data to a sub-range.
    Returns prefetched dict suitable for run_rotation_backtest(_prefetched=...),
    or None if cached data doesn't cover the requested range.

    回退逻辑：
      1. 内存预取（最快）→ 2. 磁盘 pickle（重启后）→ 3. AV 磁盘 OHLCV 缓存（历史 2018+）
    """
    # Try loading from disk if not in memory
    if not _PREFETCHED_FULL or "histories" not in _PREFETCHED_FULL:
        _load_prefetched_from_disk()

    if not _PREFETCHED_FULL or "histories" not in _PREFETCHED_FULL:
        # 主缓存不可用，直接尝试 AV 磁盘缓存
        return _build_prefetched_from_av_disk_cache(start_date, end_date)

    cached_start = _PREFETCHED_FULL.get("start", "")
    cached_end = _PREFETCHED_FULL.get("end", "")
    if start_date < cached_start or end_date > cached_end:
        # 请求范围超出主缓存 → 回退到 AV 磁盘缓存
        logger.info(
            f"[slice_prefetched] 请求 {start_date}→{end_date} 超出主缓存范围 "
            f"{cached_start}→{cached_end}，尝试 AV 磁盘缓存..."
        )
        return _build_prefetched_from_av_disk_cache(start_date, end_date)

    # If requesting the full range, return directly (no slicing needed)
    if start_date == cached_start and end_date == cached_end:
        return {
            "histories": _PREFETCHED_FULL["histories"],
            "bt_fundamentals": _PREFETCHED_FULL.get("bt_fundamentals", {}),
        }

    import pandas as pd
    ts_start = pd.Timestamp(start_date)
    ts_end = pd.Timestamp(end_date)

    # Include 6 months of lookback before start_date for momentum/MA calculations
    # (backtest needs ≥63 trading days before start_idx).
    # Clamp to cache start so we use all available data even if 6mo exceeds cache.
    lookback_start = max(
        ts_start - pd.DateOffset(months=6),
        pd.Timestamp(cached_start),
    )

    sliced_histories = {}
    for ticker, h in _PREFETCHED_FULL["histories"].items():
        dates = h["dates"]
        mask = (dates >= lookback_start) & (dates <= ts_end)
        if mask.sum() > 20:
            sliced_histories[ticker] = {
                "close": h["close"][mask],
                "open": h["open"][mask],
                "volume": h["volume"][mask],
                "high": h["high"][mask],
                "low": h["low"][mask],
                "dates": dates[mask],
                "item": h["item"],
            }

    if not sliced_histories or "SPY" not in sliced_histories:
        return None

    return {
        "histories": sliced_histories,
        "bt_fundamentals": _PREFETCHED_FULL.get("bt_fundamentals", {}),
    }


async def _fetch_backtest_ohlcv_only(start_date: str, end_date: str) -> dict:
    """
    Lightweight startup prefetch: OHLCV only, skip fundamentals.
    ~500 API calls (~6.5 min) vs full fetch with fundamentals.
    Enough for _slice_prefetched() to serve custom date ranges.
    """
    import time as _time
    t0 = _time.time()

    av = get_av_client()
    stock_pool = LARGECAP_STOCKS + MIDCAP_STOCKS
    if RC.USE_DYNAMIC_UNIVERSE:
        from app.services.universe_service import UniverseService
        _univ_items = UniverseService().get_universe_items()
        if _univ_items:
            stock_pool = _univ_items
            logger.info(f"OHLCV prefetch using dynamic universe: {len(stock_pool)} stocks")
    all_items = OFFENSIVE_ETFS + stock_pool + DEFENSIVE_ETFS + INVERSE_ETFS
    histories = {}
    fetched = 0
    failed = 0
    for item in all_items:
        ticker = item["ticker"]
        try:
            hist = await av.get_daily_history_range(ticker, start_date, end_date)
            if hist is not None and not hist.empty and len(hist) > 20:
                histories[ticker] = {
                    "close": hist["Close"].values,
                    "open": hist["Open"].values if "Open" in hist.columns else hist["Close"].values,
                    "volume": hist["Volume"].values,
                    "high": hist["High"].values,
                    "low": hist["Low"].values,
                    "dates": hist.index,
                    "item": item,
                }
                fetched += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.debug(f"Failed to fetch {ticker}: {e}")
        total_done = fetched + failed
        if total_done % 20 == 0:
            logger.info(f"OHLCV-only progress: {total_done}/{len(all_items)} "
                        f"(OK: {fetched}, failed: {failed})")

    elapsed = _time.time() - t0
    logger.info(f"OHLCV-only fetch complete in {elapsed:.1f}s: "
                f"{fetched}/{len(all_items)} tickers OK, {failed} failed")

    if not histories:
        return {"error": f"No data fetched (tried {len(all_items)} tickers, all failed)."}
    if "SPY" not in histories:
        return {"error": "SPY data not available — cannot compute benchmark"}

    return {"histories": histories, "bt_fundamentals": {}}


async def _fetch_backtest_data(start_date: str, end_date: str) -> dict:
    """
    Fetch all OHLCV + fundamental data needed for backtesting.
    Returns {'histories': {...}, 'bt_fundamentals': {...}} or {'error': '...'}.
    Call once and pass to run_rotation_backtest() to avoid repeated API calls.

    Uses the AV client's built-in 1-hour cache: first call is slow (~3-4min),
    subsequent calls within 1 hour are nearly instant.

    NEW: If full-range data is cached (from scheduler), slices from it instead
    of re-fetching from Alpha Vantage.
    """
    # Try slicing from cached full-range data first
    sliced = _slice_prefetched(start_date, end_date)
    if sliced:
        logger.info(f"Using cached full-range data sliced to {start_date}..{end_date} "
                    f"({len(sliced['histories'])} tickers)")
        return sliced

    import time as _time
    t0 = _time.time()

    av = get_av_client()
    stock_pool = LARGECAP_STOCKS + MIDCAP_STOCKS
    if RC.USE_DYNAMIC_UNIVERSE:
        from app.services.universe_service import UniverseService
        _univ_items = UniverseService().get_universe_items()
        if _univ_items:
            stock_pool = _univ_items
            logger.info(f"Backtest using dynamic universe: {len(stock_pool)} stocks")
        else:
            logger.warning("Dynamic universe empty, falling back to static watchlist")
    all_items = OFFENSIVE_ETFS + stock_pool + DEFENSIVE_ETFS + INVERSE_ETFS
    histories = {}
    fetched = 0
    failed = 0
    for item in all_items:
        ticker = item["ticker"]
        try:
            hist = await av.get_daily_history_range(ticker, start_date, end_date)
            if hist is not None and not hist.empty and len(hist) > 20:
                histories[ticker] = {
                    "close": hist["Close"].values,
                    "open": hist["Open"].values if "Open" in hist.columns else hist["Close"].values,
                    "volume": hist["Volume"].values,
                    "high": hist["High"].values,
                    "low": hist["Low"].values,
                    "dates": hist.index,
                    "item": item,
                }
                fetched += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.debug(f"Failed to fetch {ticker}: {e}")

        # Progress logging every 20 tickers
        total_done = fetched + failed
        if total_done % 20 == 0:
            logger.info(f"OHLCV progress: {total_done}/{len(all_items)} "
                        f"(OK: {fetched}, failed: {failed})")

    t1 = _time.time()
    logger.info(f"OHLCV fetch complete in {t1 - t0:.1f}s: "
                f"{fetched}/{len(all_items)} tickers OK, {failed} failed")

    if not histories:
        return {"error": f"No data fetched (tried {len(all_items)} tickers, all failed). "
                         f"Check Alpha Vantage API key and rate limits."}
    if "SPY" not in histories:
        return {"error": "SPY data not available — cannot compute benchmark"}

    # ── Fetch fundamentals for midcap stocks ──
    # Only earnings + cashflow (overview DISABLED due to look-ahead bias —
    # AV OVERVIEW returns current-snapshot data, not point-in-time).
    # The auto-normalize in compute_multi_factor_score() redistributes weight.
    bt_fundamentals = {}
    stock_items = stock_pool  # uses dynamic universe if enabled, else static
    midcap_tickers = [s["ticker"] for s in stock_items if s["ticker"] in histories]
    fund_count = 0

    for ticker in midcap_tickers:
        fund = {}
        try:
            earnings = await av.get_earnings(ticker)
            if earnings and earnings.get("quarterly"):
                fund["earnings_data"] = earnings
            cashflow = await av.get_cash_flow(ticker)
            if cashflow and cashflow.get("quarterly"):
                fund["cashflow_data"] = cashflow
            # NOTE: overview (COMPANY_OVERVIEW) intentionally skipped —
            # it returns current values, not point-in-time historical data,
            # causing look-ahead bias in backtesting.
            if fund:
                bt_fundamentals[ticker] = fund
                fund_count += 1
        except Exception:
            pass
        # Progress logging every 15 tickers
        done = midcap_tickers.index(ticker) + 1
        if done % 15 == 0:
            logger.info(f"Fundamental progress: {done}/{len(midcap_tickers)} tickers "
                        f"({fund_count} with data)")

    t2 = _time.time()
    logger.info(f"Fundamental fetch complete in {t2 - t1:.1f}s: "
                f"{fund_count}/{len(midcap_tickers)} tickers with data")

    logger.info(f"Pre-fetched data: {len(histories)} tickers, {len(bt_fundamentals)} fundamentals")

    return {"histories": histories, "bt_fundamentals": bt_fundamentals}


async def run_rotation_backtest(
    start_date: str = "2023-04-01",
    end_date: str = "2026-03-01",
    top_n: int = RC.TOP_N,
    holding_bonus: float = RC.HOLDING_BONUS,
    _prefetched: dict = None,
    regime_version: str = "v1",
    ml_enhance: bool = False,
    ml_ranker: object = None,
    ml_rerank_pool: int = 10,
    disable_regime_filter: bool = False,  # 纯 Alpha 模式：禁用 Regime 门控，纯评分 Top-N
    _collect_snapshots: list = None,
    universe_filter: Optional[set] = None,
    hedge_overlay: bool = False,  # 启用对冲叠加层（独立于 Top-N 选股）
    trend_hold_exempt: bool = False,  # 趋势保留豁免：高分持仓跌出 TOP_N 时给一次保留周
    exempt_score_pct: float = 0.75,  # 豁免分数门槛（D2: 75th pct，WF验证+0.132 Sharpe）
    exempt_rs_min: float = 0.05,     # 豁免 RS 最低阈值（D2: >0.05，过滤弱相对强度）
    exempt_loss_cap: float = None,   # 豁免股当周亏损保护（None=关闭, -0.02=-2%止损）
) -> dict:
    """
    Historical backtest of the rotation strategy with alpha enhancements.
    Pass _prefetched (from _fetch_backtest_data) to skip redundant API calls.

    Args:
        universe_filter: Optional set of ticker strings for Point-in-Time survivorship
                         bias correction. When provided, only tickers in this set (plus
                         all ETF/benchmark tickers) are eligible for scoring each week.
                         Build via UniverseService.get_pit_universe(year).
    """
    logger.info(f"Running rotation backtest: {start_date} to {end_date}, top {top_n}")

    # Use pre-fetched data or fetch fresh
    if _prefetched and "histories" in _prefetched:
        histories = dict(_prefetched["histories"])  # shallow copy — we filter below
        bt_fundamentals = _prefetched.get("bt_fundamentals", {})
    else:
        data = await _fetch_backtest_data(start_date, end_date)
        if "error" in data:
            return data
        histories = data["histories"]
        bt_fundamentals = data["bt_fundamentals"]

    if not histories:
        return {"error": "No data fetched"}

    # ── Point-in-Time universe filter (Phase 1.5 survivorship bias fix) ────────
    # ETF tickers and SPY/QQQ benchmarks are always retained regardless of filter.
    if universe_filter is not None:
        always_keep = {e["ticker"] for e in OFFENSIVE_ETFS + DEFENSIVE_ETFS + INVERSE_ETFS}
        always_keep.update(["SPY", "QQQ"])
        before = len(histories)
        histories = {
            t: h for t, h in histories.items()
            if t in universe_filter or t in always_keep
        }
        logger.info(
            f"PIT universe_filter applied: {len(histories)}/{before} tickers retained "
            f"(pit_set={len(universe_filter)}, etfs+benchmarks={len(always_keep)})"
        )

    # Use SPY + QQQ as benchmarks
    spy_hist = histories.get("SPY")
    if not spy_hist:
        return {"error": "SPY data not available"}
    qqq_hist = histories.get("QQQ")  # Nasdaq benchmark (may be None)

    # Pre-compute sets for regime filtering
    defensive_set = {e["ticker"] for e in DEFENSIVE_ETFS}
    inverse_set = {e["ticker"] for e in INVERSE_ETFS}
    offensive_set = {e["ticker"] for e in OFFENSIVE_ETFS}
    largecap_set = {e["ticker"] for e in LARGECAP_STOCKS}

    # Simulate week by week
    spy_dates = spy_hist["dates"]

    # ── Align all tickers to SPY's trading calendar ──────────────────────────
    # Critical fix: stocks that IPO'd after PREFETCH_START have shorter arrays.
    # Without alignment, h["close"][i] for such stocks returns a price from a
    # *future* date (the stock's i-th bar ≠ spy_dates[i]), causing massive
    # look-ahead bias that inflates backtest returns to absurd levels.
    import pandas as pd
    _spy_dates_idx = pd.DatetimeIndex(spy_dates) if not isinstance(spy_dates, pd.DatetimeIndex) else spy_dates
    _aligned = {}
    for _tk, _h in histories.items():
        _t_dates = _h["dates"]
        _t_idx = pd.DatetimeIndex(_t_dates) if not isinstance(_t_dates, pd.DatetimeIndex) else _t_dates
        if len(_t_idx) == len(_spy_dates_idx) and _t_idx.equals(_spy_dates_idx):
            _aligned[_tk] = _h  # already aligned
            continue
        try:
            _df = pd.DataFrame({
                "close":  _h["close"],
                "open":   _h["open"],
                "high":   _h["high"],
                "low":    _h["low"],
                "volume": _h["volume"],
            }, index=_t_idx)
            # ffill only — NO bfill. Stocks not yet trading stay NaN.
            # bfill would back-propagate a 2022-IPO price into 2018-2021,
            # creating severe look-ahead bias in the backtest.
            _df = _df.reindex(_spy_dates_idx).ffill()
            _close_arr = _df["close"].values

            # Auto-detect listed_since from first non-NaN close.
            # Ensures stocks without metadata listed_since are still
            # correctly excluded from periods before their IPO.
            _item = _h["item"]
            if not _item.get("listed_since"):
                _valid = ~np.isnan(_close_arr)
                if _valid.any():
                    _first_ym = str(_spy_dates_idx[int(np.argmax(_valid))])[:7]
                    _item = dict(_item)  # don't mutate shared item reference
                    _item["listed_since"] = _first_ym

            _aligned[_tk] = {
                **_h,
                "close":  _close_arr,
                "open":   _df["open"].values,
                "high":   _df["high"].values,
                "low":    _df["low"].values,
                "volume": _df["volume"].values,
                "dates":  _spy_dates_idx,
                "item":   _item,
            }
        except Exception as _e:
            logger.warning(f"Date alignment failed for {_tk}: {_e}, using original")
            _aligned[_tk] = _h
    histories = _aligned
    spy_hist  = histories["SPY"]
    qqq_hist  = histories.get("QQQ")

    # ── Universe lock: exclude stocks that IPO'd after start_date ──
    # Prevents look-ahead bias from survivorship: only trade stocks that
    # actually existed at the backtest start date.
    _bench_tickers = (
        {e["ticker"] for e in OFFENSIVE_ETFS}
        | {e["ticker"] for e in DEFENSIVE_ETFS}
        | {e["ticker"] for e in INVERSE_ETFS}
        | {"SPY", "QQQ"}
    )
    _start_ym = start_date[:7]  # "YYYY-MM"
    _before_lock = len(histories)
    histories = {
        tk: h for tk, h in histories.items()
        if tk in _bench_tickers
        or not h["item"].get("listed_since")
        or h["item"]["listed_since"] <= _start_ym
    }
    _locked_out = _before_lock - len(histories)
    if _locked_out:
        logger.info(f"Universe lock: removed {_locked_out} tickers listed after {_start_ym}")
    spy_hist  = histories["SPY"]
    qqq_hist  = histories.get("QQQ")

    # ── Date-range filter: find index bounds for start_date / end_date ──
    _sd = pd.Timestamp(start_date)
    _ed = pd.Timestamp(end_date)
    start_idx = 63
    for _si in range(len(spy_dates)):
        if spy_dates[_si] >= _sd:
            start_idx = max(_si, 63)
            break
    end_idx = len(spy_dates)
    for _ei in range(len(spy_dates) - 1, -1, -1):
        if spy_dates[_ei] <= _ed:
            end_idx = _ei + 1
            break

    weekly_returns = []
    spy_weekly_returns = []
    qqq_weekly_returns = []
    holdings = []
    equity_curve = []
    trade_log = []
    weekly_details = []
    cum_port_val = 1.0
    cum_spy_val = 1.0
    cum_qqq_val = 1.0
    prev_selected = []
    _exempt_used = set()  # 趋势保留豁免：每只股票只豁免一次

    # ATR stop-loss tracking: {ticker: {"stop": px, "entry": px, "high": px, "atr": atr}}
    active_stops = {}
    stop_triggered_count = 0
    trailing_triggered_count = 0

    # Walk through time in weekly steps (within the date range)
    step = 5  # ~1 trading week
    for i in range(start_idx, min(end_idx, len(spy_dates)) - step, step):
        # ── Regime detection ──
        spy_closes_so_far = spy_hist["close"][:i + 1]
        ma50_bt = float(np.mean(spy_closes_so_far[-50:])) if len(spy_closes_so_far) >= 50 else 0
        ma20_bt = float(np.mean(spy_closes_so_far[-20:])) if len(spy_closes_so_far) >= 20 else 0
        spy_cur = float(spy_closes_so_far[-1])

        vol_arr_bt = np.diff(spy_closes_so_far[-22:]) / spy_closes_so_far[-22:-1] if len(spy_closes_so_far) > 22 else np.array([0])
        vol_bt = float(np.std(vol_arr_bt) * np.sqrt(252))
        ret_1m_bt = (spy_cur / float(spy_closes_so_far[-22])) - 1 if len(spy_closes_so_far) > 22 else 0

        rscore = 0
        if spy_cur > ma50_bt * 1.02: rscore += 2
        elif spy_cur > ma50_bt: rscore += 1
        elif spy_cur < ma50_bt * 0.98: rscore -= 2
        else: rscore -= 1
        if spy_cur > ma20_bt: rscore += 1
        else: rscore -= 1
        if vol_bt > 0.25: rscore -= 1
        elif vol_bt < 0.12: rscore += 1
        if ret_1m_bt > 0.03: rscore += 1
        elif ret_1m_bt < -0.03: rscore -= 1

        # V2: bounce detection — faster bear→choppy transition
        if regime_version == "v2" and len(spy_closes_so_far) >= 10:
            recent_low = float(np.min(spy_closes_so_far[-10:]))
            if recent_low > 0:
                bounce_pct = (spy_cur - recent_low) / recent_low
                if bounce_pct >= 0.05 and spy_cur > ma20_bt:
                    rscore += 2

        if rscore >= 4: regime = "strong_bull"
        elif rscore >= 1: regime = "bull"
        elif rscore >= -1: regime = "choppy"
        else: regime = "bear"

        # ── Score tickers via unified MultiFactorScorer ──
        from app.services.multi_factor_scorer import compute_multi_factor_score

        scored = []
        scores_map = {}
        scorer_results_map = {}  # {ticker: compute_multi_factor_score() output} for ML
        spy_closes_for_rs = spy_hist["close"][:i + 1]

        # as_of_date for fundamental data (prevent lookahead bias)
        bt_date = str(spy_dates[i].date()) if hasattr(spy_dates[i], "date") else str(spy_dates[i])[:10]

        for ticker, h in histories.items():
            if i >= len(h["close"]):
                continue
            closes = h["close"][:i + 1]
            if len(closes) < 63:
                continue
            if np.isnan(closes[-1]):  # stock not yet trading (pre-IPO NaN)
                continue

            # ── IPO date filter: skip tickers not yet listed at bt_date ──
            listed_since = h["item"].get("listed_since")
            if listed_since and bt_date < listed_since:
                continue

            volumes = h["volume"][:i + 1]

            # ── Liquidity filter: skip tickers with low avg volume ──
            if RC.BACKTEST_MIN_AVG_VOL > 0 and len(volumes) >= 20:
                avg_vol_20d = float(np.mean(volumes[-20:]))
                if avg_vol_20d < RC.BACKTEST_MIN_AVG_VOL:
                    continue
            highs = h["high"][:i + 1]
            lows = h["low"][:i + 1]

            # Get pre-fetched fundamental data for this ticker (if available)
            # NOTE: overview (COMPANY_OVERVIEW) is DISABLED in backtest because
            # Alpha Vantage returns current-snapshot data, causing look-ahead bias.
            # The auto-normalize in compute_multi_factor_score() will redistribute
            # the fundamental weight to other available factors automatically.
            earnings_bt = bt_fundamentals.get(ticker, {}).get("earnings_data")
            cashflow_bt = bt_fundamentals.get(ticker, {}).get("cashflow_data")

            # Compute sector returns from historical ETF data (if available)
            bt_sector_returns = _compute_sector_returns_at(histories, i) if histories else None

            # Unified multi-factor score
            result = compute_multi_factor_score(
                closes=closes,
                volumes=volumes,
                highs=highs,
                lows=lows,
                spy_closes=spy_closes_for_rs,
                regime=regime,
                overview=None,              # DISABLED: look-ahead bias
                earnings_data=earnings_bt,
                cashflow_data=cashflow_bt,
                sentiment_value=None,        # no historical sentiment data
                sector_returns=bt_sector_returns,
                ticker_sector=h["item"].get("sector", ""),
                as_of_date=bt_date,
            )

            score = result["total_score"]

            # ── Relative strength filter ──
            is_defensive = ticker in defensive_set
            is_inverse = ticker in inverse_set
            is_etf = ticker in offensive_set
            is_largecap = ticker in largecap_set
            is_midcap = not is_defensive and not is_etf and not is_inverse and not is_largecap

            if RC.RELATIVE_STRENGTH_FILTER and not is_defensive and not is_inverse:
                rs = _compute_relative_strength(closes, spy_closes_for_rs, period=21)
                if rs < -0.02:  # underperforming SPY by >2% → skip
                    continue

            # Regime 硬过滤已移除 —— WF 5窗口验证（2020-2024）
            # 纯Alpha均值 Sharpe 3.84 vs 门控 1.70，评分系统已内置 Regime 感知
            # disable_regime_filter 参数保留供历史对比脚本使用（已无实际效果）

            scored.append((ticker, score))
            scores_map[ticker] = score
            scorer_results_map[ticker] = result

        # Holding inertia
        if holding_bonus > 0 and prev_selected:
            scored = [(t, sc + holding_bonus) if t in prev_selected else (t, sc)
                      for t, sc in scored]
            for t, sc in scored:
                scores_map[t] = sc

        scored.sort(key=lambda x: x[1], reverse=True)

        # ── Collect ML training snapshots (if requested) ──
        if _collect_snapshots is not None:
            snap_items = []
            for t, sc in scored[:ml_rerank_pool]:
                sr = scorer_results_map.get(t)
                if sr:
                    snap_items.append({"ticker": t, "scorer_result": sr})
            _collect_snapshots.append({
                "regime": regime,
                "date_idx": i,
                "scored_items": snap_items,
            })

        # ── ML re-ranking (方案B) —— 熊市跳过（池子<10只，特征失效）──
        if ml_enhance and ml_ranker is not None and regime not in ("bear",):
            from app.services.ml_scorer import ml_rerank_candidates
            selected = ml_rerank_candidates(
                scored_list=scored,
                scorer_results=scorer_results_map,
                regime=regime,
                ranker=ml_ranker,
                top_n=top_n,
                rerank_pool=ml_rerank_pool,
                histories=histories,
                date_idx=i,
            )
        elif RC.MAX_SECTOR_CONCENTRATION > 0:
            selected = _apply_sector_cap(scored, histories,
                                         max_per_sector=RC.MAX_SECTOR_CONCENTRATION,
                                         top_n=top_n)
        else:
            selected = [t for t, _ in scored[:top_n]]

        # ── 趋势保留豁免：高分持仓跌出 TOP_N 时，给一次保留周 ──
        # 条件：(1) 上周持有 (2) 本周分数 > pct门槛 (3) RS > 阈值 (4) 上周未使用过豁免
        if trend_hold_exempt and prev_selected:
            _pct_idx = max(0, int(len(scored) * exempt_score_pct) - 1)
            _pct_score = scored[_pct_idx][1] if scored else 0
            for t in prev_selected:
                if t not in selected and t not in _exempt_used:
                    t_score = scores_map.get(t, -999)
                    if t_score > _pct_score and t_score > 0:
                        # RS check
                        t_h = histories.get(t)
                        if t_h and i >= 22:
                            t_closes = t_h["close"][:i + 1]
                            t_rs = _compute_relative_strength(t_closes, spy_closes_for_rs, period=21)
                            if t_rs > exempt_rs_min:
                                # 当周亏损保护：若上周持有期间已亏超阈值则不豁免
                                if exempt_loss_cap is not None and i >= 1:
                                    _prev_close = t_closes[-2] if len(t_closes) >= 2 else t_closes[-1]
                                    _cur_close = t_closes[-1]
                                    _weekly_ret = (_cur_close / _prev_close) - 1 if _prev_close > 0 else 0
                                    if _weekly_ret < exempt_loss_cap:
                                        continue
                                selected.append(t)
                                _exempt_used.add(t)
                                logger.debug(f"[BT] Trend hold exempt: {t} score={t_score:.2f} RS={t_rs:.3f}")

        holdings.append(selected)

        # 记录换仓
        added = [t for t in selected if t not in prev_selected]
        removed = [t for t in prev_selected if t not in selected]
        week_date = str(spy_dates[i].date()) if hasattr(spy_dates[i], "date") else str(spy_dates[i])[:10]
        trade_log.append({
            "date": week_date,
            "regime": regime,
            "holdings": selected,
            "added": added,
            "removed": removed,
        })

        # ── ATR stop-loss simulation (with trailing stop) ──
        # Set stops for newly added tickers
        if RC.BACKTEST_STOP_LOSS:
            for t in added:
                h = histories.get(t)
                if h and i < len(h["close"]) and i < len(h["high"]) and i < len(h["low"]):
                    closes_t = h["close"][:i + 1]
                    highs_t = h["high"][:i + 1]
                    lows_t = h["low"][:i + 1]
                    atr = _compute_atr(highs_t, lows_t, closes_t)
                    entry_px = _bt_entry_price(h, i)
                    active_stops[t] = {
                        "stop": entry_px - RC.BACKTEST_STOP_MULT * atr,
                        "entry": entry_px,
                        "high": entry_px,
                        "atr": atr,
                    }
            # Remove stops for removed tickers
            for t in removed:
                active_stops.pop(t, None)

        # 清除已回到 selected 的豁免标记（允许未来再次豁免）
        if trend_hold_exempt:
            _exempt_used -= set(selected)
        prev_selected = selected[:]

        # ── Compute portfolio return for next week ──
        if RC.SCORE_WEIGHTED_ALLOC:
            port_ret = _score_weighted_returns(selected, scores_map, histories, i, step,
                                               prev_selected=prev_selected)
        else:
            slippage = RC.BACKTEST_SLIPPAGE
            port_ret = 0.0
            valid = 0
            for t in selected:
                h = histories.get(t)
                if h is None or i + step >= len(h["close"]):
                    continue
                entry_px = _bt_entry_price(h, i)
                exit_px = _bt_exit_price(h, i, step)
                week_ret = (exit_px / entry_px) - 1
                # Entry slippage for new positions
                if t in added and slippage > 0:
                    week_ret -= slippage
                port_ret += week_ret
                valid += 1
            if valid > 0:
                port_ret /= valid
            # Exit slippage for removed positions
            if slippage > 0 and removed and valid > 0:
                port_ret -= len(removed) * slippage / valid

        # ── ATR stop-loss + trailing stop check within the week ──
        if RC.BACKTEST_STOP_LOSS:
            for t in list(selected):
                h = histories.get(t)
                if h is None:
                    continue
                info = active_stops.get(t)
                if info is None:
                    continue
                triggered = False
                effective_stop = info["stop"]
                # Check daily bars within the week
                for d in range(i + 1, min(i + step + 1, len(h["low"]))):
                    # Update highest price with daily high
                    day_high = float(h["high"][d])
                    if day_high > info["high"]:
                        info["high"] = day_high
                    # Trailing stop: activate when profit >= ACTIVATE × ATR
                    if RC.BACKTEST_TRAILING_MULT > 0 and info["atr"] > 0:
                        profit = info["high"] - info["entry"]
                        if profit >= RC.BACKTEST_TRAILING_ACTIVATE * info["atr"]:
                            trailing_sl = info["high"] - RC.BACKTEST_TRAILING_MULT * info["atr"]
                            effective_stop = max(info["stop"], trailing_sl)
                    # Check if low breaches effective stop
                    if h["low"][d] < effective_stop:
                        bt_entry = _bt_entry_price(h, i)
                        actual_loss = (effective_stop / bt_entry) - 1
                        normal_ret = (_bt_exit_price(h, i, step) / bt_entry) - 1
                        is_trailing = effective_stop > info["stop"]

                        if normal_ret < actual_loss:
                            weight = scores_map.get(t, 1.0) if RC.SCORE_WEIGHTED_ALLOC else 1.0
                            total_w = sum(max(scores_map.get(s, 1.0), 0.01) for s in selected) if RC.SCORE_WEIGHTED_ALLOC else len(selected)
                            w_frac = max(weight, 0.01) / total_w if total_w > 0 else 1.0 / len(selected)
                            port_ret += (actual_loss - normal_ret) * w_frac
                            if is_trailing:
                                trailing_triggered_count += 1
                            else:
                                stop_triggered_count += 1

                        active_stops.pop(t, None)
                        triggered = True
                        break
                # Update effective stop in info if not triggered
                if not triggered and effective_stop > info["stop"]:
                    info["stop"] = effective_stop

        # ── Hedge Overlay: 独立对冲层，不占 Top-N 名额 ──
        hedge_ticker = None
        hedge_alloc = 0.0
        hedge_ret = 0.0
        if hedge_overlay:
            hedge_alloc = RC.HEDGE_ALLOC_BY_REGIME.get(regime, 0.0)
            if hedge_alloc > 0:
                # 选择原指数最弱的反向ETF
                best_inverse, best_weakness = None, -999
                for inv_tk, idx_tk in INVERSE_ETF_INDEX_MAP.items():
                    idx_h = histories.get(idx_tk)
                    if idx_h is None or i + step >= len(idx_h["close"]) or i < 22:
                        continue
                    idx_closes = idx_h["close"][:i + 1]
                    r1w = (float(idx_closes[-1]) / float(idx_closes[-5])) - 1 if len(idx_closes) >= 5 else 0
                    r1m = (float(idx_closes[-1]) / float(idx_closes[-22])) - 1 if len(idx_closes) >= 22 else 0
                    weakness = -(0.4 * r1w + 0.6 * r1m)
                    if weakness > best_weakness:
                        best_weakness = weakness
                        best_inverse = inv_tk
                if best_inverse:
                    hedge_ticker = best_inverse
                    inv_h = histories.get(best_inverse)
                    if inv_h and i + step < len(inv_h["close"]):
                        entry_px = float(inv_h["close"][i])
                        exit_px = float(inv_h["close"][i + step])
                        hedge_ret = (exit_px / entry_px) - 1
                        # 混合收益: alpha部分缩减 + 对冲部分
                        port_ret = (1 - hedge_alloc) * port_ret + hedge_alloc * hedge_ret

        spy_ret = (spy_hist["close"][i + step] / spy_hist["close"][i]) - 1
        qqq_ret = 0.0
        if qqq_hist and i + step < len(qqq_hist["close"]):
            qqq_ret = (qqq_hist["close"][i + step] / qqq_hist["close"][i]) - 1
        weekly_returns.append(port_ret)
        spy_weekly_returns.append(spy_ret)
        qqq_weekly_returns.append(qqq_ret)

        # 累计净值
        cum_port_val *= (1 + port_ret)
        cum_spy_val *= (1 + spy_ret)
        cum_qqq_val *= (1 + qqq_ret)
        equity_curve.append({
            "date": week_date,
            "portfolio": round(cum_port_val, 4),
            "spy": round(cum_spy_val, 4),
            "qqq": round(cum_qqq_val, 4),
        })
        weekly_details.append({
            "date": week_date,
            "regime": regime,
            "holdings": selected,
            "hedge_ticker": hedge_ticker,
            "hedge_alloc": hedge_alloc,
            "return_pct": round(port_ret * 100, 2),
            "spy_return_pct": round(spy_ret * 100, 2),
            "qqq_return_pct": round(qqq_ret * 100, 2),
            "cum_return": round((cum_port_val - 1) * 100, 2),
            "spy_cum_return": round((cum_spy_val - 1) * 100, 2),
            "qqq_cum_return": round((cum_qqq_val - 1) * 100, 2),
        })

    if not weekly_returns:
        return {"error": "Insufficient data for backtest"}

    # Compute cumulative returns
    cum_port = float(np.prod([1 + r for r in weekly_returns]) - 1)
    cum_spy = float(np.prod([1 + r for r in spy_weekly_returns]) - 1)
    cum_qqq = float(np.prod([1 + r for r in qqq_weekly_returns]) - 1)
    ann_ret = float((1 + cum_port) ** (52 / len(weekly_returns)) - 1) if weekly_returns else 0
    ann_vol = float(np.std(weekly_returns) * np.sqrt(52))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    max_dd = _max_drawdown(weekly_returns)

    win_weeks = sum(1 for r in weekly_returns if r > 0)
    win_rate = win_weeks / len(weekly_returns) if weekly_returns else 0

    # ── Per-year statistics (Sharpe, win_rate, max_dd per year) ──
    from collections import defaultdict
    _yearly_weeks = defaultdict(list)  # year_str -> [(port_ret, spy_ret, qqq_ret), ...]
    for wd in weekly_details:
        yr = wd["date"][:4]
        _yearly_weeks[yr].append((
            wd["return_pct"] / 100.0,
            wd["spy_return_pct"] / 100.0,
            wd.get("qqq_return_pct", 0.0) / 100.0,
        ))
    yearly_stats = []
    for yr in sorted(_yearly_weeks.keys()):
        wk_list = _yearly_weeks[yr]
        n = len(wk_list)
        port_rets = [w[0] for w in wk_list]
        spy_rets = [w[1] for w in wk_list]
        qqq_rets = [w[2] for w in wk_list]
        yr_cum_port = float(np.prod([1 + r for r in port_rets]) - 1)
        yr_cum_spy = float(np.prod([1 + r for r in spy_rets]) - 1)
        yr_cum_qqq = float(np.prod([1 + r for r in qqq_rets]) - 1)
        yr_ann_ret = float((1 + yr_cum_port) ** (52 / n) - 1) if n > 0 else 0
        yr_ann_vol = float(np.std(port_rets) * np.sqrt(52)) if n > 1 else 0
        yr_sharpe = round(yr_ann_ret / yr_ann_vol, 2) if yr_ann_vol > 0 else 0
        yr_win = sum(1 for r in port_rets if r > 0)
        yr_max_dd = _max_drawdown(port_rets)
        yearly_stats.append({
            "year": yr if yr != str(date.today().year) else f"{yr} YTD",
            "strategy_return": round(yr_cum_port, 4),
            "spy_return": round(yr_cum_spy, 4),
            "qqq_return": round(yr_cum_qqq, 4),
            "annualized_return": round(yr_ann_ret, 4),
            "sharpe": yr_sharpe,
            "max_drawdown": round(yr_max_dd, 4),
            "win_rate": round(yr_win / n, 4) if n > 0 else 0,
            "weeks": n,
        })

    # Alpha enhancement stats
    alpha_enhancements = {
        "relative_strength_filter": RC.RELATIVE_STRENGTH_FILTER,
        "score_weighted_alloc": RC.SCORE_WEIGHTED_ALLOC,
        "sector_concentration_cap": RC.MAX_SECTOR_CONCENTRATION,
        "graduated_trend_bonus": RC.GRADUATED_TREND_BONUS,
        "stop_loss_simulation": RC.BACKTEST_STOP_LOSS,
        "dynamic_momentum_weights": True,
        "stop_triggered_count": stop_triggered_count,
        "trailing_triggered_count": trailing_triggered_count,
        "slippage_per_trade": RC.BACKTEST_SLIPPAGE,
        "min_avg_volume": RC.BACKTEST_MIN_AVG_VOL,
        "next_open_entry": RC.BACKTEST_NEXT_OPEN,
    }

    return {
        "period": f"{start_date} to {end_date}",
        "weeks": len(weekly_returns),
        "top_n": top_n,
        "cumulative_return": round(cum_port, 4),
        "spy_cumulative_return": round(cum_spy, 4),
        "qqq_cumulative_return": round(cum_qqq, 4),
        "annualized_return": round(ann_ret, 4),
        "annualized_vol": round(ann_vol, 4),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
        "alpha_vs_spy": round(cum_port - cum_spy, 4),
        "alpha_vs_qqq": round(cum_port - cum_qqq, 4),
        "equity_curve": equity_curve,
        "trades": trade_log,
        "weekly_details": weekly_details,
        "alpha_enhancements": alpha_enhancements,
        "yearly_stats": yearly_stats,
        "regime_version": regime_version,
        "hedge_overlay": hedge_overlay,
    }


async def run_parameter_optimization(
    start_date: str = "2023-04-01",
    end_date: str = "2026-03-01",
) -> dict:
    """
    Grid search over top_n × holding_bonus to find optimal parameter combination.
    Returns sorted results matrix with best combo highlighted.
    """
    logger.info(f"Starting parameter optimization: {start_date} to {end_date}")

    # Fetch data ONCE, share across all 25 parameter combos
    prefetched = await _fetch_backtest_data(start_date, end_date)
    if "error" in prefetched:
        return prefetched

    top_n_values = [2, 3, 4, 5, 6]
    bonus_values = [0, 0.25, 0.5, 0.75, 1.0]

    results = []
    best_sharpe = -999
    best_combo = {}

    for tn in top_n_values:
        for hb in bonus_values:
            try:
                bt = await run_rotation_backtest(
                    start_date=start_date,
                    end_date=end_date,
                    top_n=tn,
                    holding_bonus=hb,
                    _prefetched=prefetched,
                )
                if "error" in bt:
                    continue

                entry = {
                    "top_n": tn,
                    "holding_bonus": hb,
                    "sharpe_ratio": bt["sharpe_ratio"],
                    "annualized_return": bt["annualized_return"],
                    "max_drawdown": bt["max_drawdown"],
                    "win_rate": bt["win_rate"],
                    "alpha_vs_spy": bt["alpha_vs_spy"],
                    "cumulative_return": bt["cumulative_return"],
                }
                results.append(entry)

                if bt["sharpe_ratio"] > best_sharpe:
                    best_sharpe = bt["sharpe_ratio"]
                    best_combo = entry

            except Exception as e:
                logger.warning(f"Optimization failed for top_n={tn}, bonus={hb}: {e}")

    # Sort by Sharpe ratio descending
    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)

    logger.info(f"Optimization complete: {len(results)} combos tested, "
                f"best Sharpe={best_sharpe:.2f} with top_n={best_combo.get('top_n')}, "
                f"bonus={best_combo.get('holding_bonus')}")

    return {
        "period": f"{start_date} to {end_date}",
        "total_combos": len(results),
        "best": best_combo,
        "results": results,
        "top_n_values": top_n_values,
        "bonus_values": bonus_values,
    }


async def run_adaptive_backtest(
    start_date: str = "2022-07-01",
    end_date: str = "2026-03-15",
    progress_callback=None,
) -> dict:
    """
    Walk-Forward Optimization: 月度自适应最优组合分析。
    1) 对25种参数组合各跑一次完整回测
    2) 按月切片，用前3个月训练窗口选最优参数
    3) 拼接自适应权益曲线，对比固定最优和SPY
    """
    from collections import defaultdict
    import math

    logger.info(f"Starting adaptive backtest: {start_date} to {end_date}")

    # Fetch data ONCE, share across all 25 parameter combos
    prefetched = await _fetch_backtest_data(start_date, end_date)
    if "error" in prefetched:
        return prefetched
    logger.info("Adaptive: data pre-fetched, running 25 parameter combos...")

    top_n_values = [2, 3, 4, 5, 6]
    bonus_values = [0, 0.25, 0.5, 0.75, 1.0]

    # ── Step 1: Run 25 full backtests (reusing pre-fetched data) ──
    all_results = {}  # (top_n, hb) -> backtest result dict
    total_combos = len(top_n_values) * len(bonus_values)
    combo_count = 0
    import time as _time
    step1_start = _time.time()
    for tn in top_n_values:
        for hb in bonus_values:
            combo_count += 1
            if progress_callback:
                progress_callback(f"回测组合 {combo_count}/{total_combos}（Top{tn}, 惯性{hb}）")
            try:
                bt = await run_rotation_backtest(
                    start_date=start_date,
                    end_date=end_date,
                    top_n=tn,
                    holding_bonus=hb,
                    _prefetched=prefetched,
                )
                if "error" not in bt:
                    all_results[(tn, hb)] = bt
                    logger.info(f"Adaptive [{combo_count}/{total_combos}]: "
                                f"combo ({tn},{hb}) done — "
                                f"sharpe={bt['sharpe_ratio']}, cum={bt['cumulative_return']:.2%}")
                else:
                    logger.warning(f"Adaptive [{combo_count}/{total_combos}]: "
                                   f"combo ({tn},{hb}) returned error: {bt.get('error')}")
            except Exception as e:
                logger.warning(f"Adaptive [{combo_count}/{total_combos}]: "
                               f"combo ({tn},{hb}) failed: {e}")
    step1_elapsed = _time.time() - step1_start
    logger.info(f"Adaptive Step 1 complete: {len(all_results)}/{total_combos} combos OK "
                f"in {step1_elapsed:.1f}s")

    if not all_results:
        return {"error": "所有参数组合回测均失败"}

    if progress_callback:
        progress_callback(f"24组回测完成，正在进行月度Walk-Forward优化...")

    # ── Step 2: Slice weekly_details by month ──
    # monthly_data[(tn,hb)][YYYY-MM] = list of weekly dicts
    monthly_data = defaultdict(lambda: defaultdict(list))
    for combo, bt in all_results.items():
        for wd in bt["weekly_details"]:
            month_key = wd["date"][:7]  # "YYYY-MM"
            monthly_data[combo][month_key].append(wd)

    # Get sorted list of all months
    all_months = sorted(set(
        m for combo_months in monthly_data.values() for m in combo_months
    ))

    if len(all_months) < 4:
        return {"error": "数据不足4个月，无法进行Walk-Forward分析"}

    # ── Helper: compute compound return from weekly returns ──
    def _compound_return(weekly_dicts: list) -> float:
        cum = 1.0
        for wd in weekly_dicts:
            cum *= (1 + wd["return_pct"] / 100.0)
        return cum - 1.0

    def _compound_spy_return(weekly_dicts: list) -> float:
        cum = 1.0
        for wd in weekly_dicts:
            cum *= (1 + wd["spy_return_pct"] / 100.0)
        return cum - 1.0

    def _compound_qqq_return(weekly_dicts: list) -> float:
        cum = 1.0
        for wd in weekly_dicts:
            cum *= (1 + wd.get("qqq_return_pct", 0.0) / 100.0)
        return cum - 1.0

    # ── Step 3: Monthly returns matrix ──
    # monthly_returns[(tn,hb)][YYYY-MM] = compound return
    monthly_returns = {}
    for combo in all_results:
        monthly_returns[combo] = {}
        for month in all_months:
            weeks = monthly_data[combo].get(month, [])
            monthly_returns[combo][month] = _compound_return(weeks) if weeks else 0.0

    # ── Step 4: Walk-Forward selection ──
    training_window = 3  # months
    monthly_report = []
    adaptive_weekly = []       # stitched weekly_details for adaptive
    adaptive_returns = []      # weekly return floats
    spy_returns_adaptive = []  # SPY weekly returns for the same weeks

    for i in range(training_window, len(all_months)):
        current_month = all_months[i]
        train_months = all_months[i - training_window: i]

        # Find best combo during training window (by Sharpe, not raw return)
        best_combo = None
        best_train_sharpe = -999
        for combo in all_results:
            # Collect all weekly returns in training window
            train_weekly_rets = []
            for tm in train_months:
                for wd in monthly_data[combo].get(tm, []):
                    train_weekly_rets.append(wd["return_pct"] / 100.0)
            if not train_weekly_rets:
                continue
            # Compute Sharpe-like metric for training window
            mean_ret = float(np.mean(train_weekly_rets))
            std_ret = float(np.std(train_weekly_rets))
            train_sharpe = (mean_ret / std_ret * math.sqrt(52)) if std_ret > 0 else 0
            if train_sharpe > best_train_sharpe:
                best_train_sharpe = train_sharpe
                best_combo = combo

        if best_combo is None:
            continue

        # Get this month's data from the selected combo
        month_weeks = monthly_data[best_combo].get(current_month, [])
        if not month_weeks:
            continue

        monthly_ret = _compound_return(month_weeks)
        spy_monthly_ret = _compound_spy_return(month_weeks)
        qqq_monthly_ret = _compound_qqq_return(month_weeks)

        # Get dominant regime for the month
        regime_counts = defaultdict(int)
        for wd in month_weeks:
            regime_counts[wd.get("regime", "unknown")] += 1
        dominant_regime = max(regime_counts, key=regime_counts.get) if regime_counts else "unknown"

        # Get top holdings (most frequently held during the month)
        holding_counts = defaultdict(int)
        for wd in month_weeks:
            for h in wd.get("holdings", []):
                holding_counts[h] += 1
        top_holdings = sorted(holding_counts, key=holding_counts.get, reverse=True)[:5]

        monthly_report.append({
            "month": current_month,
            "selected_top_n": best_combo[0],
            "selected_holding_bonus": best_combo[1],
            "training_window": f"{train_months[0]} ~ {train_months[-1]}",
            "training_sharpe": round(best_train_sharpe, 2),
            "regime": dominant_regime,
            "monthly_return": round(monthly_ret * 100, 2),
            "spy_monthly_return": round(spy_monthly_ret * 100, 2),
            "qqq_monthly_return": round(qqq_monthly_ret * 100, 2),
            "alpha": round((monthly_ret - spy_monthly_ret) * 100, 2),
            "top_holdings": top_holdings,
        })

        # Collect weekly data for equity curve
        for wd in month_weeks:
            adaptive_weekly.append(wd)
            adaptive_returns.append(wd["return_pct"] / 100.0)
            spy_returns_adaptive.append(wd["spy_return_pct"] / 100.0)

    # ── Step 5: Find fixed best combo (全周期最优) ──
    best_fixed_combo = max(all_results, key=lambda c: all_results[c]["sharpe_ratio"])
    fixed_best_bt = all_results[best_fixed_combo]

    # ── Step 6: Build equity curves ──
    equity_curve = []
    cum_adaptive = 1.0
    cum_spy = 1.0
    cum_qqq = 1.0

    # Also build fixed_best weekly returns aligned with adaptive weeks
    fixed_best_weekly = {wd["date"]: wd for wd in fixed_best_bt["weekly_details"]}
    cum_fixed = 1.0

    for wd in adaptive_weekly:
        date_str = wd["date"]
        cum_adaptive *= (1 + wd["return_pct"] / 100.0)
        cum_spy *= (1 + wd["spy_return_pct"] / 100.0)
        cum_qqq *= (1 + wd.get("qqq_return_pct", 0.0) / 100.0)

        fb_wd = fixed_best_weekly.get(date_str)
        if fb_wd:
            cum_fixed *= (1 + fb_wd["return_pct"] / 100.0)

        equity_curve.append({
            "date": date_str,
            "adaptive": round(cum_adaptive, 4),
            "fixed_best": round(cum_fixed, 4),
            "spy": round(cum_spy, 4),
            "qqq": round(cum_qqq, 4),
        })

    # ── Step 7: Compute statistics for all three ──
    def _compute_stats(weekly_rets, spy_rets):
        if not weekly_rets:
            return {}
        cum = float(np.prod([1 + r for r in weekly_rets]) - 1)
        cum_spy = float(np.prod([1 + r for r in spy_rets]) - 1)
        n = len(weekly_rets)
        ann_ret = float((1 + cum) ** (52 / n) - 1) if n > 0 else 0
        ann_vol = float(np.std(weekly_rets) * np.sqrt(52))
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        max_dd = _max_drawdown(weekly_rets)
        win = sum(1 for r in weekly_rets if r > 0) / n if n else 0
        return {
            "cumulative_return": round(cum, 4),
            "annualized_return": round(ann_ret, 4),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd, 4),
            "win_rate": round(win, 4),
            "alpha_vs_spy": round(cum - cum_spy, 4),
            "weeks": n,
        }

    # Fixed best returns for the same period
    adaptive_start = adaptive_weekly[0]["date"] if adaptive_weekly else start_date
    fixed_returns_aligned = []
    spy_returns_fixed = []
    for wd in fixed_best_bt["weekly_details"]:
        if wd["date"] >= adaptive_start:
            fixed_returns_aligned.append(wd["return_pct"] / 100.0)
            spy_returns_fixed.append(wd["spy_return_pct"] / 100.0)

    # QQQ returns for the adaptive period
    qqq_returns_adaptive = [wd.get("qqq_return_pct", 0.0) / 100.0 for wd in adaptive_weekly]

    stats = {
        "adaptive": _compute_stats(adaptive_returns, spy_returns_adaptive),
        "fixed_best": _compute_stats(fixed_returns_aligned, spy_returns_fixed),
        "spy": {
            "cumulative_return": round(float(np.prod([1 + r for r in spy_returns_adaptive]) - 1), 4)
            if spy_returns_adaptive else 0,
        },
        "qqq": {
            "cumulative_return": round(float(np.prod([1 + r for r in qqq_returns_adaptive]) - 1), 4)
            if qqq_returns_adaptive else 0,
        },
    }

    # ── Step 8: Parameter distribution ──
    param_distribution = defaultdict(int)
    prev_combo = None
    total_changes = 0
    for mr in monthly_report:
        combo_key = f"Top{mr['selected_top_n']} / 惯性{mr['selected_holding_bonus']}"
        param_distribution[combo_key] += 1
        curr_combo = (mr['selected_top_n'], mr['selected_holding_bonus'])
        if prev_combo and curr_combo != prev_combo:
            total_changes += 1
        prev_combo = curr_combo

    # Best/worst months
    sorted_months = sorted(monthly_report, key=lambda x: x["monthly_return"], reverse=True)
    best_months = sorted_months[:3]
    worst_months = sorted_months[-3:][::-1] if len(sorted_months) >= 3 else sorted_months[::-1]

    result = {
        "period": f"{start_date} to {end_date}",
        "training_months": training_window,
        "total_combos_tested": len(all_results),
        "monthly_report": monthly_report,
        "equity_curve": equity_curve,
        "statistics": stats,
        "fixed_best_params": {
            "top_n": best_fixed_combo[0],
            "holding_bonus": best_fixed_combo[1],
        },
        "param_changes": {
            "total_changes": total_changes,
            "param_distribution": dict(param_distribution),
        },
        "best_months": best_months,
        "worst_months": worst_months,
    }

    logger.info(f"Adaptive backtest complete: {len(monthly_report)} months analyzed, "
                f"adaptive cum={stats.get('adaptive', {}).get('cumulative_return', 0):.2%}")

    return result


def _max_drawdown(returns: list[float]) -> float:
    """Compute max drawdown from a list of period returns."""
    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        cum *= (1 + r)
        peak = max(peak, cum)
        dd = (peak - cum) / peak
        max_dd = max(max_dd, dd)
    return max_dd


# ============================================================
# 5. DAILY SCORING — full universe score refresh (no trading)
# ============================================================

async def run_daily_scoring() -> dict:
    """
    每日盘后全量评分：对动态池全部股票打分，写入 cache_store + sector_snapshots。
    不触发交易，不写 rotation_snapshots。供仪表盘 T+0 展示。

    调度：Tue-Sat 09:35 NZT（美股收盘后 35 分钟，市场数据已落地）
    """
    import time as _time
    t_start = _time.time()

    regime = await _detect_regime()
    logger.info(f"[DAILY-SCORING] regime={regime}, starting full universe scoring...")

    # Build universe: dynamic pool + ETFs
    stock_pool = LARGECAP_STOCKS + MIDCAP_STOCKS  # fallback
    if RC.USE_DYNAMIC_UNIVERSE:
        from app.services.universe_service import UniverseService
        _univ_items = UniverseService().get_universe_items()
        if _univ_items:
            stock_pool = _univ_items
            logger.info(f"[DAILY-SCORING] Dynamic universe: {len(stock_pool)} stocks")

    full_universe = list({
        item["ticker"]: item
        for pool in [DEFENSIVE_ETFS, OFFENSIVE_ETFS, INVERSE_ETFS] + [stock_pool]
        for item in pool
    }.values())

    # Fetch SPY for relative strength
    from app.services.knowledge_service import get_knowledge_service
    ks = get_knowledge_service()
    spy_data = await _fetch_history(RC.REGIME_TICKER, days=RC.LOOKBACK_DAYS)
    spy_closes = spy_data["close"] if spy_data else None

    # Concurrent scoring — same as weekly_rotation
    CONCURRENCY = 30
    _sem = asyncio.Semaphore(CONCURRENCY)

    async def _score_one(item):
        async with _sem:
            return await _score_ticker(item, regime, ks, spy_closes=spy_closes)

    results = await asyncio.gather(
        *[_score_one(item) for item in full_universe],
        return_exceptions=True,
    )

    scores: list[RotationScore] = []
    errors = 0
    for r in results:
        if isinstance(r, RotationScore):
            scores.append(r)
        elif isinstance(r, Exception):
            errors += 1

    scores.sort(key=lambda s: s.score, reverse=True)

    # Persist to cache_store + sector_snapshots (no rotation_snapshots, no trading)
    await _persist_all_scores_to_cache(scores, regime)
    trading_day = _last_trading_day()
    await _save_sector_snapshots(scores, regime, trading_day)

    elapsed = _time.time() - t_start
    logger.info(
        f"[DAILY-SCORING] Done: {len(scores)}/{len(full_universe)} scored, "
        f"{errors} errors, {elapsed:.0f}s"
    )

    return {
        "summary": f"scored={len(scores)}/{len(full_universe)}, errors={errors}, "
                   f"regime={regime}, elapsed={elapsed:.0f}s",
        "scored": len(scores),
        "total": len(full_universe),
        "errors": errors,
        "regime": regime,
        "elapsed_seconds": round(elapsed, 1),
    }


# ============================================================
# 6. SCORES — read pre-computed scores from DB
# ============================================================

def read_cached_scores(limit: int = 0) -> dict:
    """
    Read pre-computed rotation scores from DB (cache_store → rotation_snapshots fallback).
    Never triggers live scoring — all scores are produced by the weekly_rotation scheduler.

    Args:
        limit: Max scores to return (0 = all). Dashboard uses 50, API uses 0.

    Returns:
        {"regime": str, "count": int, "scores": list[dict]}
    """
    # L1: cache_store (written by _persist_all_scores_to_cache after weekly_rotation)
    try:
        db = get_db()
        result = db.table("cache_store").select("value").eq("key", "rotation_scores").limit(1).execute()
        if result.data:
            cached = result.data[0].get("value", {})
            scores = cached.get("scores", [])
            if scores:
                scores.sort(key=lambda x: x.get("score", 0), reverse=True)
                if limit > 0:
                    scores = scores[:limit]
                return {
                    "regime": cached.get("regime", "unknown"),
                    "count": len(scores),
                    "scores": scores,
                }
    except Exception as e:
        logger.warning(f"read_cached_scores: cache_store read failed: {e}")

    # L2: latest rotation_snapshot (always has top-20 scores from weekly_rotation)
    try:
        db = get_db()
        snap = db.table("rotation_snapshots").select(
            "regime, scores"
        ).order("created_at", desc=True).limit(1).execute()
        if snap.data and snap.data[0].get("scores"):
            row = snap.data[0]
            scores = row["scores"]
            if isinstance(scores, dict):
                scores = scores.get("scores", [])
            scores.sort(key=lambda x: x.get("score", 0), reverse=True)
            if limit > 0:
                scores = scores[:limit]
            return {
                "regime": row.get("regime", "unknown"),
                "count": len(scores),
                "scores": scores,
            }
    except Exception as e:
        logger.warning(f"read_cached_scores: rotation_snapshots fallback failed: {e}")

    return {"regime": "unknown", "count": 0, "scores": []}


# Legacy alias — kept for imports that haven't migrated yet.
# WARNING: This is now a synchronous DB read, NOT a live computation.
async def get_current_scores() -> dict:
    """Deprecated: use read_cached_scores() instead. Kept for backward compat."""
    return read_cached_scores()


# ============================================================
# DB HELPERS
# ============================================================

async def _save_snapshot(snapshot: RotationSnapshot, trigger_source: str = "scheduler") -> str:
    """Save rotation snapshot to DB with trigger source tracking."""
    try:
        db = get_db()
        data = {
            "snapshot_date": snapshot.snapshot_date,
            "regime": snapshot.regime,
            "spy_price": float(snapshot.spy_price),
            "spy_ma50": float(snapshot.spy_ma50),
            "scores": snapshot.scores,
            "selected_tickers": snapshot.selected_tickers,
            "previous_tickers": snapshot.previous_tickers,
            "changes": snapshot.changes,
            "trigger_source": trigger_source,
        }
        result = db.table("rotation_snapshots").insert(data).execute()
        if result.data:
            return result.data[0]["id"]
    except Exception as e:
        logger.error(f"Error saving rotation snapshot: {e}")
    return ""


async def _get_previous_selected() -> list[str]:
    """Get selected tickers from the most recent snapshot."""
    try:
        db = get_db()
        result = (
            db.table("rotation_snapshots")
            .select("selected_tickers")
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0].get("selected_tickers", [])
    except Exception as e:
        logger.error(f"Error getting previous selected: {e}")
    return []


async def _get_latest_selected() -> list[str]:
    """Get the latest selected tickers (same as previous for exit check)."""
    return await _get_previous_selected()


async def _get_positions_by_status(status: str) -> list[dict]:
    """Get rotation positions by status."""
    try:
        db = get_db()
        result = (
            db.table("rotation_positions")
            .select("*")
            .eq("status", status)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error getting positions: {e}")
        return []


async def _manage_positions_on_rotation(
    selected: list[str], removed: list[str], snapshot_id: str,
    hedge_ticker: str = None,
    hedge_alloc: float = 0.0,
):
    """
    After weekly rotation: manage position transitions.

    设计原则：先算清 full_target（alpha ∪ hedge），再执行任何 Tiger 订单。
    这样可以避免"先平仓 X → 再买回 X"的无效双边交易（如 RWM 从 alpha 转 hedge）。

    执行顺序：
      Step 0: 计算 _full_target = alpha ∪ hedge（无任何 IO，纯计算）
      Step 1: 加载当前持仓快照
      Step 2: 平仓 —— 只平 removed 中且不在 _full_target 的仓位
      Step 3: 为新 alpha 创建 pending_entry
      Step 4: 对冲层管理（rebalance existing / 新建 pending_entry）

    适用场景（每次 regime 切换或轮动均自动覆盖）：
      A. hedge_ticker 在 removed 中（旧 alpha → 新 hedge）→ Step 2 跳过平仓，Step 4 rebalance
      B. hedge_ticker 不在 removed 但已是 active（持仓大小不对）→ Step 4 rebalance
      C. hedge_ticker 从未持有 → Step 4 创建 pending_entry
      D. hedge_ticker == None（bull/strong_bull）→ Step 4 全部跳过
    """
    db = get_db()

    # ── Step 0: Pre-compute full new target（任何订单之前完成）─────────────────
    _alpha_set = set(selected)
    _full_target = set(selected)
    if hedge_ticker and hedge_alloc > 0:
        _full_target.add(hedge_ticker)

    # ── Step 1: 加载当前持仓快照 ──────────────────────────────────────────────
    existing = await _get_positions_by_status("pending_entry")
    existing.extend(await _get_positions_by_status("active"))
    existing_tickers = {p["ticker"] for p in existing}

    # ── Step 2: 平仓 —— 只处理不在 full_target 中的 removed 仓位 ─────────────
    for ticker in removed:
        if ticker in _full_target:
            # 此 ticker 在新的 full_target 中（alpha 或 hedge），禁止平仓
            # Step 4 统一处理 rebalance
            logger.info(
                f"[PM] {ticker}: 在 removed 中但属于新 full_target"
                f"({'alpha' if ticker in _alpha_set else 'hedge'})，跳过平仓 → Step 4 rebalance"
            )
            continue
        active_positions = [p for p in existing if p["ticker"] == ticker and p["status"] == "active"]
        for pos in active_positions:
            pos_qty = int(pos.get("quantity", 0) or 0)
            current_price = float(pos.get("current_price", 0) or 0)
            try:
                await _close_position(
                    pos["id"],
                    reason="rotation_removal",
                    exit_price=current_price if current_price > 0 else None,
                    ticker=ticker,
                    quantity=pos_qty,
                )
                logger.info(
                    f"Rotation removal: {ticker} qty={pos_qty} "
                    f"exit_price=${current_price:.2f} → Tiger MKT SELL queued"
                )
                try:
                    from app.services.notification_service import notify_rotation_exit
                    signal = DailyTimingSignal(
                        ticker=ticker,
                        signal_type="exit",
                        trigger_conditions=[f"rotation removal: dropped from top {RC.TOP_N}"],
                        current_price=current_price,
                        entry_price=float(pos.get("entry_price", 0) or 0),
                        exit_reason="rotation_removal",
                    )
                    await notify_rotation_exit(signal)
                except Exception:
                    pass  # notification failure is non-critical
            except Exception as e:
                logger.error(f"Error closing position for {ticker}: {e}")

    # ── Step 3: 为新 alpha 创建 pending_entry ────────────────────────────────
    for ticker in selected:
        if ticker not in existing_tickers:
            try:
                row = {"ticker": ticker, "status": "pending_entry"}
                if snapshot_id:
                    row["snapshot_id"] = snapshot_id
                db.table("rotation_positions").insert(row).execute()
                logger.info(f"Created pending_entry position for {ticker}")
            except Exception as e:
                err_msg = str(e).lower()
                if "duplicate" in err_msg or "unique" in err_msg or "23505" in err_msg:
                    logger.warning(f"Position already exists for {ticker} (unique constraint), skipping")
                else:
                    logger.error(f"Error creating position for {ticker}: {e}")

    # ── Step 4: 对冲层管理 ────────────────────────────────────────────────────
    # 统一处理所有 hedge 场景（A/B/C），无论 hedge_ticker 是否在 removed 中
    if hedge_ticker and hedge_alloc > 0:
        _h_active = [p for p in existing if p["ticker"] == hedge_ticker and p["status"] == "active"]
        _h_pending = [p for p in existing if p["ticker"] == hedge_ticker and p["status"] == "pending_entry"]

        if _h_active:
            # 场景 A / B：已有 active 仓位 → 多退少补至 hedge_alloc 目标
            _hpos = _h_active[0]
            _hpos_qty = int(_hpos.get("quantity", 0) or 0)
            _hprice = float(_hpos.get("current_price", 0) or _hpos.get("entry_price", 0) or 0)
            if _hprice > 0 and _hpos_qty > 0:
                try:
                    from app.services.order_service import get_tiger_trade_client
                    _tiger = get_tiger_trade_client()
                    _assets = await _tiger.get_account_assets()
                    _equity = _assets.get("net_liquidation", 100_000.0) if _assets else 100_000.0
                    _target_val = _equity * hedge_alloc
                    import math as _math
                    _target_qty = _math.floor(_target_val / _hprice)
                    _diff = _target_qty - _hpos_qty  # 正=补买，负=减仓
                    if abs(_diff) <= max(1, _hpos_qty * 0.05):
                        logger.info(f"[Hedge] {hedge_ticker}: qty 差异={_diff} ≤5%，无需调整")
                    elif not RC.AUTO_EXECUTE_ORDERS:
                        _action = f"补买 {_diff} 股" if _diff > 0 else f"减仓 {abs(_diff)} 股"
                        logger.info(f"[SIGNAL ONLY] Hedge {hedge_ticker}: {_action} → 目标 {_target_qty} 股 "
                                    f"(equity×{hedge_alloc:.0%}=${_target_val:,.0f}) — 等待人工确认")
                    elif _diff > 0:
                        _r = await _tiger.place_buy_order(hedge_ticker, _diff, order_type="MKT")
                        logger.info(f"[Hedge] {hedge_ticker}: 补买 {_diff} 股 → 目标 {_target_qty} 股 "
                                    f"(equity×{hedge_alloc:.0%}=${_target_val:,.0f}) order={_r}")
                    else:
                        _r = await _tiger.place_sell_order(hedge_ticker, abs(_diff), order_type="MKT")
                        logger.info(f"[Hedge] {hedge_ticker}: 减仓 {abs(_diff)} 股 → 目标 {_target_qty} 股 "
                                    f"(equity×{hedge_alloc:.0%}=${_target_val:,.0f}) order={_r}")
                except Exception as _e:
                    logger.error(f"[Hedge] {hedge_ticker} rebalance 失败: {_e}")
        elif not _h_pending and hedge_ticker not in _alpha_set:
            # 场景 C：无持仓且不在 alpha 队列 → 创建 pending_entry
            try:
                _hrow = {"ticker": hedge_ticker, "status": "pending_entry", "position_type": "hedge"}
                db.table("rotation_positions").insert(_hrow).execute()
                logger.info(f"[Hedge] {hedge_ticker}: 自动创建 pending_entry（对冲层新建）")
            except Exception as _e:
                _err = str(_e).lower()
                if "duplicate" in _err or "unique" in _err or "23505" in _err:
                    logger.warning(f"[Hedge] {hedge_ticker}: pending_entry 已存在，跳过")
                else:
                    logger.error(f"[Hedge] {hedge_ticker}: 创建 pending_entry 失败: {_e}")


async def _activate_position(
    position_id: str, entry_price: float, atr: float,
    stop_loss: float, take_profit: float, ticker: str = ""
):
    """Activate a pending_entry position and place Tiger buy order."""
    try:
        db = get_db()
        update_data = {
            "status": "active",
            "signal_price": round(entry_price, 4),  # preserve original signal price for slippage tracking
            "entry_price": entry_price,
            "entry_date": date.today().isoformat(),
            "atr14": round(atr, 4),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "current_price": entry_price,
            "unrealized_pnl_pct": 0.0,
        }

        # --- Tiger Order Execution (MKT, no bracket legs) ---
        if not RC.AUTO_EXECUTE_ORDERS:
            # 纯信号模式：记录意图，不向 Tiger 发单，等待人工确认后手动操作
            logger.info(
                f"[SIGNAL ONLY] BUY {ticker} @ ${entry_price:.2f} "
                f"SL=${stop_loss:.2f} TP=${take_profit:.2f} — AUTO_EXECUTE_ORDERS=False，等待人工确认"
            )
        else:
            try:
                from app.services.order_service import (
                    get_tiger_trade_client, calculate_position_size,
                )
                tiger = get_tiger_trade_client()
                _regime_for_sizing = await _detect_regime()
                from app.services.portfolio_manager import ALLOCATION_MATRIX
                _v4_fraction = ALLOCATION_MATRIX.get(_regime_for_sizing, ALLOCATION_MATRIX["bull"])["v4"]
                # 对冲层资金属于 V4 分配内部，alpha 每仓需先扣掉 hedge 部分再均分
                # 例：bear V4=50%, hedge=30% → alpha_fraction=20%, 每仓=6.7%
                _hedge_fraction = RC.HEDGE_ALLOC_BY_REGIME.get(_regime_for_sizing, 0.0)
                _alpha_fraction = max(0.0, _v4_fraction - _hedge_fraction)
                qty = await calculate_position_size(tiger, entry_price, max_positions=RC.TOP_N, equity_fraction=_alpha_fraction)
                if qty > 0:
                    result = await tiger.place_buy_order(
                        ticker, qty, order_type="MKT",
                    )
                    if result:
                        update_data["quantity"] = qty
                        order_id_str = str(result.get("id") or result.get("order_id", ""))
                        update_data["tiger_order_id"] = order_id_str
                        update_data["tiger_order_status"] = "submitted"
                        logger.info(f"[TIGER-TRADE] MKT BUY {qty}x {ticker} "
                                    f"SL=${stop_loss:.2f} TP=${take_profit:.2f} "
                                    f"order_id={result.get('order_id')}")

                        # Audit log: order submitted
                        from app.services.order_service import _log_order_audit
                        await _log_order_audit(
                            ticker, "BUY", "submitted",
                            position_id=position_id, order_type="MKT",
                            quantity=qty, signal_price=entry_price,
                            tiger_order_id=order_id_str,
                        )

                        # Immediately poll fill price — MKT orders typically fill within seconds
                        async def _poll_fill_price(pos_id: str, oid: str, atr_val: float):
                            await asyncio.sleep(5)
                            try:
                                fill_info = await tiger.get_order_status(int(oid))
                                if fill_info and "FILLED" in str(fill_info.get("status", "")).upper():
                                    fp = float(fill_info.get("avg_fill_price") or 0)
                                    if fp > 0:
                                        fill_update: dict = {
                                            "entry_price": round(fp, 4),
                                            "current_price": round(fp, 4),
                                            "tiger_order_status": "filled",
                                        }
                                        if atr_val > 0:
                                            fill_update["stop_loss"] = round(fp - RC.ATR_STOP_MULTIPLIER * atr_val, 2)
                                            fill_update["take_profit"] = round(fp + RC.ATR_TARGET_MULTIPLIER * atr_val, 2)
                                        get_db().table("rotation_positions").update(fill_update).eq("id", pos_id).execute()
                                        slippage_bps = round((fp - entry_price) / entry_price * 10000, 1) if entry_price > 0 else 0
                                        logger.info(f"[TIGER-TRADE] {ticker} immediate fill confirmed @ ${fp:.2f} "
                                                    f"(signal=${entry_price:.2f}, slippage={slippage_bps:+.1f}bps)")
                                        await _log_order_audit(
                                            ticker, "BUY", "filled",
                                            position_id=pos_id, order_type="MKT",
                                            quantity=qty, signal_price=entry_price,
                                            fill_price=fp, tiger_order_id=oid,
                                        )
                            except Exception as pe:
                                logger.debug(f"[TIGER-TRADE] Immediate fill poll skipped: {pe}")

                        asyncio.create_task(_poll_fill_price(position_id, order_id_str, atr))
                    else:
                        logger.warning(f"[TIGER-TRADE] BUY order failed for {ticker}, position still activated")
                        from app.services.order_service import _log_order_audit
                        await _log_order_audit(
                            ticker, "BUY", "rejected",
                            position_id=position_id, order_type="MKT",
                            quantity=qty, signal_price=entry_price,
                            error_message="place_buy_order returned None",
                        )
                else:
                    logger.warning(f"[TIGER-TRADE] Position size = 0 for {ticker} @ ${entry_price:.2f}")
            except Exception as te:
                logger.error(f"[TIGER-TRADE] Order error for {ticker}: {te}")
                try:
                    from app.services.order_service import _log_order_audit
                    await _log_order_audit(
                        ticker, "BUY", "error",
                        position_id=position_id, order_type="MKT",
                        signal_price=entry_price, error_message=str(te),
                    )
                except Exception:
                    pass
                # Don't block activation — signal is still valid

        db.table("rotation_positions").update(update_data).eq("id", position_id).execute()
    except Exception as e:
        logger.error(f"Error activating position: {e}")


async def _update_position_price(position_id: str, price: float, pnl_pct: float,
                                 highest_price: float = None):
    """Update current price, unrealized P&L, and highest price for trailing stop."""
    try:
        db = get_db()
        update_data = {
            "current_price": price,
            "unrealized_pnl_pct": round(pnl_pct, 4),
        }
        if highest_price is not None:
            update_data["highest_price"] = round(highest_price, 2)
        db.table("rotation_positions").update(update_data).eq("id", position_id).execute()
    except Exception as e:
        logger.error(f"Error updating position price: {e}")


async def _close_position(
    position_id: str, reason: str, exit_price: float = None,
    ticker: str = "", quantity: int = 0
):
    """Close a position and place Tiger sell order.
    If a Tiger sell order is placed, set status=pending_exit first;
    sync_tiger_orders will finalize to closed once the sell is filled.
    """
    try:
        db = get_db()
        update = {
            "status": "closed",
            "exit_reason": reason,
            "exit_date": date.today().isoformat(),
        }
        if exit_price:
            update["exit_price"] = exit_price

        # --- Tiger Sell Order ---
        if ticker and quantity > 0:
            if not RC.AUTO_EXECUTE_ORDERS:
                # 纯信号模式：标记为 pending_exit 等待人工确认，不向 Tiger 发单
                update["status"] = "pending_exit"
                logger.info(
                    f"[SIGNAL ONLY] SELL {quantity}x {ticker} reason={reason} "
                    f"@ ${exit_price:.2f if exit_price else 0:.2f} — AUTO_EXECUTE_ORDERS=False，等待人工确认"
                )
            else:
                try:
                    from app.services.order_service import get_tiger_trade_client
                    tiger = get_tiger_trade_client()
                    result = await tiger.place_sell_order(ticker, quantity)  # market order
                    if result:
                        update["tiger_exit_order_id"] = str(
                            result.get("id") or result.get("order_id", "")
                        )
                        update["status"] = "pending_exit"  # will be finalized by sync
                        logger.info(f"[TIGER-TRADE] SELL {quantity}x {ticker} "
                                    f"reason={reason} order_id={result.get('order_id')}")
                    else:
                        logger.warning(f"[TIGER-TRADE] SELL order failed for {ticker}")
                except Exception as te:
                    logger.error(f"[TIGER-TRADE] Sell order error for {ticker}: {te}")

        db.table("rotation_positions").update(update).eq("id", position_id).execute()
    except Exception as e:
        logger.error(f"Error closing position: {e}")


async def get_current_positions() -> list[dict]:
    """Get all non-closed positions."""
    try:
        def _fetch():
            db = get_db()
            return (
                db.table("rotation_positions")
                .select("*")
                .neq("status", "closed")
                .order("created_at", desc=True)
                .execute()
            )

        # Supabase Python client is synchronous; run in thread to avoid blocking event loop.
        result = await asyncio.to_thread(_fetch)
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error getting current positions: {e}")
        return []


async def get_rotation_history(limit: int = 10) -> list[dict]:
    """Get recent rotation snapshots."""
    try:
        db = get_db()
        result = (
            db.table("rotation_snapshots")
            .select("*")
            .order("snapshot_date", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error getting rotation history: {e}")
        return []


def _days_since(timestamp_str: str) -> int:
    """Calculate days since a timestamp string."""
    try:
        if not timestamp_str:
            return 0
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        return (datetime.now(dt.tzinfo) - dt).days
    except Exception:
        return 0


# ============================================================
# PENDING EXIT CHECKER（待确认卖单巡检）
# ============================================================

_PENDING_EXIT_WARN_DAYS: int = 2  # 超过 N 天未人工确认则升级告警


async def run_pending_exit_check() -> list[dict]:
    """
    巡检所有 pending_exit 仓位，统计等待天数并告警。

    pending_exit = AUTO_EXECUTE_ORDERS=False 时，系统已判断"该卖"但等待人工确认的仓位。
    若长期未处理，价格可能已从触发时大幅偏移，形成隐性风险。

    超过 _PENDING_EXIT_WARN_DAYS 天未处理的仓位会在日志中输出 WARNING，
    供 Render 日志监控捕获并提醒操作者。
    """
    positions = await _get_positions_by_status("pending_exit")
    if not positions:
        logger.info("[PENDING_EXIT] ✅ 无待确认卖单")
        return []

    results = []
    overdue_count = 0

    for pos in positions:
        ticker = pos.get("ticker", "?")
        exit_reason = pos.get("exit_reason", "unknown")
        exit_price = pos.get("exit_price")
        days = _days_since(pos.get("created_at", ""))

        entry = {
            "ticker": ticker,
            "days_waiting": days,
            "exit_reason": exit_reason,
            "exit_price": exit_price,
        }
        results.append(entry)

        if days >= _PENDING_EXIT_WARN_DAYS:
            overdue_count += 1
            logger.warning(
                f"[PENDING_EXIT] ⚠️ {ticker} 待确认卖单已 {days} 天 "
                f"reason={exit_reason} exit_price={f'${exit_price:.2f}' if exit_price else 'N/A'} "
                f"— 请尽快人工确认执行"
            )
        else:
            logger.info(
                f"[PENDING_EXIT] {ticker} 待确认 {days} 天 reason={exit_reason}"
            )

    logger.warning(
        f"[PENDING_EXIT] 共 {len(results)} 笔待确认卖单，"
        f"其中 {overdue_count} 笔超过 {_PENDING_EXIT_WARN_DAYS} 天未处理"
    )
    return results


