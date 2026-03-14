"""
StockQueen V3.0 - Multi-Factor Scoring Engine
统一评分引擎：采集、回测、信号三位一体。
所有评分逻辑写在这里，被三个系统共同调用。
"""

import logging
import numpy as np
from typing import Optional
from datetime import date

logger = logging.getLogger(__name__)


# ============================================================
# Factor Weight Configuration
# ============================================================

FACTOR_WEIGHTS = {
    "momentum":           0.25,   # 动量因子（1W/1M/3M加权）
    "technical":          0.15,   # 技术指标（RSI/MACD/BB/OBV/ADX）
    "trend":              0.10,   # 趋势因子（渐进MA评分）
    "relative_strength":  0.10,   # 相对强度 vs SPY
    "fundamental":        0.15,   # 基本面质量（PEG/ROE/增长率）
    "earnings":           0.10,   # 盈利因子（EPS surprise/beat率）
    "cashflow":           0.05,   # 现金流健康度
    "sentiment":          0.05,   # AI新闻情绪
    "sector_wind":        0.05,   # 板块顺风/逆风
}

# 大盘股独立评分权重 — 基本面+相对强度权重更高，动量+技术权重降低
LARGECAP_FACTOR_WEIGHTS = {
    "momentum":           0.20,   # 降低：大盘动量幅度小
    "technical":          0.10,   # 降低：机构驱动，技术面有效性低
    "trend":              0.10,   # 不变
    "relative_strength":  0.15,   # 提高：大盘龙头相对强度是选股核心
    "fundamental":        0.20,   # 提高：基本面数据完整可靠
    "earnings":           0.10,   # 不变
    "cashflow":           0.05,   # 不变
    "sentiment":          0.05,   # 不变
    "sector_wind":        0.05,   # 不变
}

# Regime-specific momentum weights (1W, 1M, 3M)
MOMENTUM_WEIGHTS_BY_REGIME = {
    "strong_bull": (0.15, 0.35, 0.50),
    "bull":        (0.20, 0.40, 0.40),
    "choppy":      (0.35, 0.40, 0.25),
    "bear":        (0.40, 0.40, 0.20),
}


# ============================================================
# Individual Factor Scoring Functions
# ============================================================

def score_momentum(closes: np.ndarray, regime: str = "bull",
                   vol_penalty: float = 0.50) -> dict:
    """
    Momentum factor: weighted returns - volatility penalty.
    Returns dict with raw score and components.
    Score range: roughly [-10, +10], normalized to [-1, +1].
    """
    if len(closes) < 63:
        return {"score": 0.0, "ret_1w": 0, "ret_1m": 0, "ret_3m": 0, "vol": 0}

    ret_1w = float((closes[-1] / closes[-6]) - 1) if len(closes) > 6 else 0
    ret_1m = float((closes[-1] / closes[-22]) - 1) if len(closes) > 22 else 0
    ret_3m = float((closes[-1] / closes[-63]) - 1) if len(closes) > 63 else 0

    w1w, w1m, w3m = MOMENTUM_WEIGHTS_BY_REGIME.get(regime, (0.20, 0.40, 0.40))
    raw_m = w1w * ret_1w + w1m * ret_1m + w3m * ret_3m

    # Volatility
    vol_arr = np.diff(closes[-22:]) / closes[-22:-1] if len(closes) > 22 else np.array([0])
    vol = float(np.std(vol_arr) * np.sqrt(252))

    score = raw_m - vol_penalty * vol
    # Normalize: typical range is about [-0.3, +0.3] → map to [-1, +1]
    normalized = max(-1.0, min(1.0, score * 3.0))

    return {
        "score": normalized,
        "ret_1w": ret_1w, "ret_1m": ret_1m, "ret_3m": ret_3m,
        "vol": vol, "raw": raw_m,
    }


def score_technical(closes: np.ndarray, volumes: np.ndarray,
                    highs: np.ndarray, lows: np.ndarray) -> dict:
    """
    Technical indicator factor: RSI, MACD, Bollinger, OBV, ADX.
    Returns score in [-1, +1].
    """
    long_score = 0
    short_score = 0

    # RSI
    rsi = _compute_rsi(closes)
    if rsi < 30:
        long_score += 1
    elif rsi > 70:
        short_score += 1

    # MACD
    macd = _compute_macd(closes)
    if macd["histogram"] > 0:
        long_score += 1
    elif macd["histogram"] < 0:
        short_score += 1

    # Bollinger Bands
    bb = _compute_bbands(closes)
    if bb["position"] < 0.2:
        long_score += 1
    elif bb["position"] > 0.8:
        short_score += 1

    # OBV
    obv = _compute_obv_trend(closes, volumes)
    if obv == "rising":
        long_score += 1
    elif obv == "falling":
        short_score += 1

    # ADX amplifier
    adx = _compute_adx(highs, lows, closes)
    if adx > 25:
        if long_score > short_score:
            long_score += 1
        elif short_score > long_score:
            short_score += 1

    net = long_score - short_score
    normalized = max(-1.0, min(1.0, net / 3.0))
    return {"score": normalized, "rsi": rsi, "macd_hist": macd["histogram"],
            "bb_pos": bb["position"], "obv": obv, "adx": adx}


def score_trend(closes: np.ndarray) -> dict:
    """
    Graduated trend bonus based on MA alignment.
    Returns score in [0, 1.0].
    """
    if len(closes) < 50:
        return {"score": 0.0}

    bonus = 0.0
    current = float(closes[-1])
    ma10 = float(np.mean(closes[-10:]))
    ma20 = float(np.mean(closes[-20:]))
    ma50 = float(np.mean(closes[-50:]))

    if current > ma10:
        bonus += 0.17
    if current > ma20:
        bonus += 0.33
    if current > ma50:
        bonus += 0.33
    if len(closes) >= 25:
        ma20_prev = float(np.mean(closes[-25:-5]))
        if ma20 > ma20_prev:
            bonus += 0.17

    return {"score": min(1.0, bonus), "above_ma10": current > ma10,
            "above_ma20": current > ma20, "above_ma50": current > ma50}


def score_relative_strength(closes: np.ndarray, spy_closes: np.ndarray,
                            period: int = 21) -> dict:
    """
    Relative strength vs SPY.
    Returns score in [-1, +1].
    """
    if len(closes) < period + 1 or len(spy_closes) < period + 1:
        return {"score": 0.0, "rs": 0.0}

    ticker_ret = (closes[-1] / closes[-period - 1]) - 1
    spy_ret = (spy_closes[-1] / spy_closes[-period - 1]) - 1
    rs = float(ticker_ret - spy_ret)

    # Normalize: ±10% relative performance → ±1.0
    normalized = max(-1.0, min(1.0, rs * 10.0))
    return {"score": normalized, "rs": rs}


def score_fundamental(overview: Optional[dict] = None) -> dict:
    """
    Fundamental quality score from company overview data.
    Returns score in [-1, +1].
    """
    if not overview:
        return {"score": 0.0, "available": False}

    score = 0.0
    components = {}

    # PEG ratio: < 1.5 is good, > 3 is expensive
    peg = overview.get("peg_ratio")
    if peg is not None:
        if peg < 1.0:
            score += 0.3
            components["peg"] = "excellent"
        elif peg < 1.5:
            score += 0.15
            components["peg"] = "good"
        elif peg > 3.0:
            score -= 0.2
            components["peg"] = "expensive"

    # ROE > 15% is strong
    roe = overview.get("roe")
    if roe is not None:
        if roe > 0.20:
            score += 0.25
            components["roe"] = "excellent"
        elif roe > 0.15:
            score += 0.15
            components["roe"] = "good"
        elif roe < 0:
            score -= 0.15
            components["roe"] = "negative"

    # Revenue growth YoY > 20% is strong growth
    rev_growth = overview.get("revenue_growth_yoy")
    if rev_growth is not None:
        if rev_growth > 0.30:
            score += 0.25
            components["rev_growth"] = "high"
        elif rev_growth > 0.15:
            score += 0.10
            components["rev_growth"] = "moderate"
        elif rev_growth < 0:
            score -= 0.20
            components["rev_growth"] = "declining"

    # Analyst target price upside
    target = overview.get("analyst_target_price")
    current_price = overview.get("current_price")
    if target and current_price and current_price > 0:
        upside = (target / current_price) - 1
        if upside > 0.20:
            score += 0.20
            components["target_upside"] = f"+{upside:.0%}"
        elif upside < -0.10:
            score -= 0.15
            components["target_upside"] = f"{upside:.0%}"

    # Profit margin
    margin = overview.get("profit_margin")
    if margin is not None:
        if margin > 0.20:
            score += 0.10
        elif margin < 0:
            score -= 0.10

    normalized = max(-1.0, min(1.0, score))
    return {"score": normalized, "available": True, "components": components}


def score_earnings(earnings_data: Optional[dict] = None,
                   as_of_date: Optional[str] = None) -> dict:
    """
    Earnings quality score from EPS history.
    Returns score in [-1, +1].
    as_of_date: for backtesting, only consider data reported before this date.
    """
    if not earnings_data or not earnings_data.get("quarterly"):
        return {"score": 0.0, "available": False}

    quarters = earnings_data["quarterly"]

    # Filter by as_of_date for backtest correctness
    if as_of_date:
        quarters = [q for q in quarters if q.get("date", "") <= as_of_date]

    if not quarters:
        return {"score": 0.0, "available": False}

    score = 0.0
    beats = 0
    total = 0
    latest_surprise = None

    for q in quarters[:4]:  # last 4 quarters
        rep = q.get("reported_eps")
        est = q.get("estimated_eps")
        surprise = q.get("surprise_pct")

        if rep is not None and est is not None:
            total += 1
            if rep > est:
                beats += 1

        if surprise is not None and latest_surprise is None:
            latest_surprise = surprise

    # Beat rate
    if total >= 2:
        beat_rate = beats / total
        if beat_rate >= 0.75:
            score += 0.40
        elif beat_rate >= 0.50:
            score += 0.15
        elif beat_rate < 0.25:
            score -= 0.30

    # Latest surprise magnitude
    if latest_surprise is not None:
        if latest_surprise > 10:
            score += 0.30
        elif latest_surprise > 5:
            score += 0.15
        elif latest_surprise < -10:
            score -= 0.30
        elif latest_surprise < -5:
            score -= 0.15

    # EPS growth trend (compare latest vs 4 quarters ago)
    if len(quarters) >= 5:
        latest_eps = quarters[0].get("reported_eps")
        old_eps = quarters[4].get("reported_eps")
        if latest_eps is not None and old_eps is not None and old_eps > 0:
            eps_growth = (latest_eps / old_eps) - 1
            if eps_growth > 0.20:
                score += 0.20
            elif eps_growth < -0.10:
                score -= 0.15

    normalized = max(-1.0, min(1.0, score))
    return {"score": normalized, "available": True,
            "beat_rate": beats / total if total > 0 else 0,
            "latest_surprise": latest_surprise}


def score_cashflow(cashflow_data: Optional[dict] = None,
                   as_of_date: Optional[str] = None) -> dict:
    """
    Cash flow health score.
    Returns score in [-1, +1].
    """
    if not cashflow_data or not cashflow_data.get("quarterly"):
        return {"score": 0.0, "available": False}

    quarters = cashflow_data["quarterly"]
    if as_of_date:
        quarters = [q for q in quarters if q.get("date", "") <= as_of_date]

    if not quarters:
        return {"score": 0.0, "available": False}

    score = 0.0

    # Latest quarter FCF
    latest = quarters[0]
    fcf = latest.get("free_cashflow")
    op_cf = latest.get("operating_cashflow")

    if fcf is not None:
        if fcf > 0:
            score += 0.30
        else:
            score -= 0.30

    if op_cf is not None:
        if op_cf > 0:
            score += 0.15
        else:
            score -= 0.30  # negative operating CF is a red flag

    # FCF growth (compare latest vs 4 quarters ago)
    if len(quarters) >= 5:
        old_fcf = quarters[4].get("free_cashflow")
        if fcf is not None and old_fcf is not None and old_fcf > 0:
            fcf_growth = (fcf / old_fcf) - 1
            if fcf_growth > 0.20:
                score += 0.25
            elif fcf_growth < -0.20:
                score -= 0.15

    # Consecutive positive FCF
    consecutive_positive = 0
    for q in quarters[:4]:
        if q.get("free_cashflow") and q["free_cashflow"] > 0:
            consecutive_positive += 1
        else:
            break
    if consecutive_positive >= 4:
        score += 0.20

    normalized = max(-1.0, min(1.0, score))
    return {"score": normalized, "available": True, "fcf": fcf, "op_cf": op_cf}


def score_sentiment(sentiment_value: Optional[float] = None) -> dict:
    """
    AI news sentiment score. Direct pass-through from knowledge_service.
    Input: [-1, +1] from AISentimentCollector.
    Returns score in [-1, +1].
    """
    if sentiment_value is None:
        return {"score": 0.0, "available": False}
    return {"score": max(-1.0, min(1.0, sentiment_value)), "available": True}


def score_sector_wind(ticker_sector: str, sector_returns: Optional[dict] = None) -> dict:
    """
    Sector tailwind/headwind score.
    sector_returns: {sector_name: 1m_return, ...}
    Returns score in [-1, +1].
    """
    if not sector_returns or not ticker_sector:
        return {"score": 0.0, "available": False}

    sector_ret = sector_returns.get(ticker_sector)
    if sector_ret is None:
        return {"score": 0.0, "available": False}

    # Normalize: ±5% monthly sector return → ±1.0
    normalized = max(-1.0, min(1.0, sector_ret * 20.0))
    return {"score": normalized, "available": True, "sector_return": sector_ret}


# ============================================================
# Unified Scoring Entry Point
# ============================================================

def compute_multi_factor_score(
    closes: np.ndarray,
    volumes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    spy_closes: Optional[np.ndarray] = None,
    regime: str = "bull",
    overview: Optional[dict] = None,
    earnings_data: Optional[dict] = None,
    cashflow_data: Optional[dict] = None,
    sentiment_value: Optional[float] = None,
    sector_returns: Optional[dict] = None,
    ticker_sector: str = "",
    as_of_date: Optional[str] = None,
    factor_overrides: Optional[dict] = None,
) -> dict:
    """
    统一多因子评分入口。
    被 rotation_service（实时+回测）和 signal_service 共同调用。

    Returns:
        {
            "total_score": float,  # 加权总分 [-10, +10]
            "factors": {factor_name: {score, ...}, ...},
            "weights_used": dict,
        }
    """
    weights = dict(FACTOR_WEIGHTS)
    if factor_overrides:
        weights.update(factor_overrides)

    factors = {}

    # 1. Momentum
    factors["momentum"] = score_momentum(closes, regime)

    # 2. Technical
    factors["technical"] = score_technical(closes, volumes, highs, lows)

    # 3. Trend
    factors["trend"] = score_trend(closes)

    # 4. Relative Strength
    if spy_closes is not None and len(spy_closes) > 22:
        factors["relative_strength"] = score_relative_strength(closes, spy_closes)
    else:
        factors["relative_strength"] = {"score": 0.0}

    # 5. Fundamental
    factors["fundamental"] = score_fundamental(overview)

    # 6. Earnings
    factors["earnings"] = score_earnings(earnings_data, as_of_date)

    # 7. Cash Flow
    factors["cashflow"] = score_cashflow(cashflow_data, as_of_date)

    # 8. Sentiment
    factors["sentiment"] = score_sentiment(sentiment_value)

    # 9. Sector Wind
    factors["sector_wind"] = score_sector_wind(ticker_sector, sector_returns)

    # Weighted total: each factor score is [-1, +1], weight sum = 1.0
    # Scale to a more readable range by multiplying by 10
    total = 0.0
    for name, w in weights.items():
        factor_score = factors.get(name, {}).get("score", 0.0)
        total += factor_score * w * 10.0  # range: [-10, +10]

    return {
        "total_score": round(total, 3),
        "factors": factors,
        "weights_used": weights,
    }


# ============================================================
# Technical Indicator Helpers (shared — same as rotation_service)
# ============================================================

def _compute_rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
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
    if len(closes) < 35:
        return {"macd": 0, "signal": 0, "histogram": 0}
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
    return {"macd": float(macd_line[-1]), "signal": float(signal_line[-1]),
            "histogram": float(histogram[-1])}


def _compute_bbands(closes: np.ndarray, period: int = 20) -> dict:
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
    if len(closes) < 6 or len(volumes) < 6:
        return "flat"
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
    n = len(closes)
    if n < period + 1:
        return 0.0
    tr_list, plus_dm, minus_dm = [], [], []
    for i in range(1, n):
        h_l = highs[i] - lows[i]
        h_pc = abs(highs[i] - closes[i - 1])
        l_pc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(h_l, h_pc, l_pc))
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)
    if len(tr_list) < period:
        return 0.0
    atr = float(np.mean(tr_list[-period:]))
    avg_plus = float(np.mean(plus_dm[-period:]))
    avg_minus = float(np.mean(minus_dm[-period:]))
    if atr == 0:
        return 0.0
    plus_di = 100 * avg_plus / atr
    minus_di = 100 * avg_minus / atr
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0.0
    return float(100 * abs(plus_di - minus_di) / di_sum)
