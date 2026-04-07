"""
StockQueen - Intraday Multi-Factor Scoring Engine
盘中 30 分钟评分引擎：6 因子纯量价+微观结构体系。

因子列表:
  1. intraday_momentum (0.25) — 短期加权动量
  2. vwap_deviation    (0.20) — VWAP 偏离度
  3. volume_profile    (0.20) — 成交量异常
  4. micro_rsi         (0.15) — RSI(6) 超买超卖
  5. spread_quality    (0.10) — 价格效率
  6. relative_flow     (0.10) — 相对 SPY 超额收益
"""

import logging
import numpy as np
from typing import Optional

from app.config.intraday_config import IntradayConfig

logger = logging.getLogger(__name__)


# ============================================================
# Individual Intraday Factor Functions
# ============================================================

def score_intraday_momentum(
    closes: np.ndarray, opens: np.ndarray,
    highs: np.ndarray, lows: np.ndarray,
) -> dict:
    """
    盘中短期动量：最近 1/2/4 根 bar 的加权收益率，减去波动率惩罚。
    Score range: [-1, +1]
    """
    n = len(closes)
    if n < 5:
        return {"score": 0.0, "available": False}

    # 1-bar, 2-bar, 4-bar returns (protect against zero/nan prices)
    ret_1 = 0
    if n >= 2 and closes[-2] != 0 and not np.isnan(closes[-2]):
        ret_1 = (closes[-1] / closes[-2]) - 1

    ret_2 = 0
    if n >= 3 and closes[-3] != 0 and not np.isnan(closes[-3]):
        ret_2 = (closes[-1] / closes[-3]) - 1

    ret_4 = 0
    if n >= 5 and closes[-5] != 0 and not np.isnan(closes[-5]):
        ret_4 = (closes[-1] / closes[-5]) - 1

    # Weighted momentum (recent bars heavier)
    raw = 0.50 * ret_1 + 0.30 * ret_2 + 0.20 * ret_4

    # Volatility penalty: std of bar returns over last 6 bars
    lookback = min(n, 7)
    bar_rets = np.diff(closes[-lookback:]) / closes[-lookback:-1]
    vol = float(np.std(bar_rets)) if len(bar_rets) > 1 else 0

    score = raw - 0.3 * vol
    normalized = max(-1.0, min(1.0, score * 30.0))

    return {
        "score": normalized,
        "available": True,
        "ret_1bar": ret_1,
        "ret_2bar": ret_2,
        "ret_4bar": ret_4,
        "vol": vol,
    }


def score_vwap_deviation(
    closes: np.ndarray, highs: np.ndarray,
    lows: np.ndarray, volumes: np.ndarray,
) -> dict:
    """
    价格相对 VWAP 偏离度。
    高于 VWAP = 多头强势, 低于 = 空头压力。
    Score range: [-1, +1]
    """
    n = len(closes)
    if n < 3 or np.sum(volumes) == 0:
        return {"score": 0.0, "vwap": 0.0, "deviation_pct": 0.0, "available": False}

    typical_price = (highs + lows + closes) / 3.0
    cum_tp_vol = np.cumsum(typical_price * volumes)
    cum_vol = np.cumsum(volumes)

    # Avoid division by zero
    mask = cum_vol > 0
    if not np.any(mask):
        return {"score": 0.0, "vwap": 0.0, "deviation_pct": 0.0, "available": False}

    vwap = float(cum_tp_vol[-1] / cum_vol[-1])
    current = float(closes[-1])

    if vwap == 0:
        return {"score": 0.0, "vwap": 0.0, "deviation_pct": 0.0, "available": False}

    deviation_pct = (current - vwap) / vwap

    # Normalize: +-2% deviation -> +-1.0
    normalized = max(-1.0, min(1.0, deviation_pct * 50.0))

    return {
        "score": normalized,
        "available": True,
        "vwap": round(vwap, 4),
        "deviation_pct": round(deviation_pct * 100, 3),
    }


def score_volume_profile(volumes: np.ndarray) -> dict:
    """
    成交量异常检测：当前 bar 相对日内均量的倍数。
    量能放大 = 方向性信号放大器。
    Score range: [-1, +1] (always >= 0 since volume is direction-agnostic)
    """
    n = len(volumes)
    if n < 3:
        return {"score": 0.0, "vol_ratio": 0.0, "available": False}

    avg_vol = float(np.mean(volumes[:-1]))  # 排除当前 bar
    current_vol = float(volumes[-1])

    if avg_vol == 0:
        return {"score": 0.0, "vol_ratio": 0.0, "available": False}

    vol_ratio = current_vol / avg_vol

    # Score: ratio 1.0=neutral, 2.0+=strong, 0.5-=weak
    # Map [0.5, 3.0] -> [-0.5, +1.0]
    raw = (vol_ratio - 1.0) / 2.0
    normalized = max(-1.0, min(1.0, raw))

    return {
        "score": normalized,
        "available": True,
        "vol_ratio": round(vol_ratio, 2),
        "current_vol": current_vol,
        "avg_vol": round(avg_vol, 0),
    }


def score_micro_rsi(closes: np.ndarray, period: int = 6) -> dict:
    """
    盘中短周期 RSI(6)。
    <20 超卖(做多), >80 超买(做空), 40-60 中性。
    Score range: [-1, +1]
    """
    n = len(closes)
    if n < period + 1:
        return {"score": 0.0, "rsi": 50.0, "available": False}

    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = float(np.mean(gains))
    avg_loss = float(np.mean(losses))

    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

    # Map RSI to score:
    # RSI 50 = 0, RSI 80 = -0.8 (overbought), RSI 20 = +0.8 (oversold)
    # This is a mean-reversion signal
    score = -(rsi - 50.0) / 37.5
    normalized = max(-1.0, min(1.0, score))

    return {
        "score": normalized,
        "available": True,
        "rsi": round(rsi, 1),
    }


def score_spread_quality(
    opens: np.ndarray, closes: np.ndarray,
    highs: np.ndarray, lows: np.ndarray,
) -> dict:
    """
    价格效率（Spread Quality）：衡量 bar 的方向性强度。
    spread = (close - open) / (high - low)
    接近 +1.0 = 强势上涨趋势 bar
    接近 -1.0 = 强势下跌趋势 bar
    接近 0 = 十字星/犹豫 bar
    用最近 3 根 bar 的加权平均。
    Score range: [-1, +1]
    """
    n = len(closes)
    if n < 3:
        return {"score": 0.0, "efficiency": 0.0, "available": False}

    # Compute efficiency for last 3 bars
    lookback = min(n, 3)
    weights = [0.5, 0.3, 0.2][:lookback]  # Most recent bar has highest weight
    total_weight = sum(weights)

    weighted_eff = 0.0
    for i, w in enumerate(weights):
        idx = -(i + 1)
        bar_range = highs[idx] - lows[idx]
        if bar_range > 0:
            eff = (closes[idx] - opens[idx]) / bar_range
        else:
            eff = 0.0
        weighted_eff += eff * w

    efficiency = weighted_eff / total_weight
    normalized = max(-1.0, min(1.0, efficiency))

    return {
        "score": normalized,
        "available": True,
        "efficiency": round(efficiency, 3),
    }


def score_relative_flow(
    closes: np.ndarray, spy_closes: np.ndarray,
    period: int = 4,
) -> dict:
    """
    相对 SPY 的盘中超额收益。
    period: 对比的 bar 数（默认 4 根 = 2 小时）。
    Score range: [-1, +1]
    """
    if len(closes) < period + 1 or len(spy_closes) < period + 1:
        return {"score": 0.0, "alpha": 0.0, "available": False}

    # Protect against zero/nan prices
    if closes[-period - 1] == 0 or np.isnan(closes[-period - 1]) or \
       spy_closes[-period - 1] == 0 or np.isnan(spy_closes[-period - 1]):
        return {"score": 0.0, "alpha": 0.0, "available": False}

    ticker_ret = (closes[-1] / closes[-period - 1]) - 1
    spy_ret = (spy_closes[-1] / spy_closes[-period - 1]) - 1
    alpha = float(ticker_ret - spy_ret)

    # Normalize: +-1% alpha -> +-1.0
    normalized = max(-1.0, min(1.0, alpha * 100.0))

    return {
        "score": normalized,
        "available": True,
        "alpha": round(alpha * 100, 3),
        "ticker_ret": round(float(ticker_ret) * 100, 3),
        "spy_ret": round(float(spy_ret) * 100, 3),
    }


# ============================================================
# Unified Intraday Scoring Entry Point
# ============================================================

def compute_intraday_score(
    bars: dict,
    spy_bars: Optional[dict] = None,
    factor_overrides: Optional[dict] = None,
) -> dict:
    """
    盘中多因子评分统一入口。

    Args:
        bars: {"open": np.array, "close": np.array, "high": np.array,
               "low": np.array, "volume": np.array}
        spy_bars: SPY 同时段 bars（相同格式）
        factor_overrides: 覆盖默认因子权重

    Returns:
        {
            "total_score": float,   # 加权总分 [-10, +10]
            "factors": dict,        # 各因子详情
            "weights_used": dict,
        }
    """
    weights = dict(IntradayConfig.FACTOR_WEIGHTS)
    if factor_overrides:
        weights.update(factor_overrides)

    closes = bars.get("close", np.array([]))
    opens = bars.get("open", np.array([]))
    highs = bars.get("high", np.array([]))
    lows = bars.get("low", np.array([]))
    volumes = bars.get("volume", np.array([]))

    factors = {}

    # 1. Intraday Momentum
    factors["intraday_momentum"] = score_intraday_momentum(closes, opens, highs, lows)

    # 2. VWAP Deviation
    factors["vwap_deviation"] = score_vwap_deviation(closes, highs, lows, volumes)

    # 3. Volume Profile
    factors["volume_profile"] = score_volume_profile(volumes)

    # 4. Micro RSI
    factors["micro_rsi"] = score_micro_rsi(closes)

    # 5. Spread Quality
    factors["spread_quality"] = score_spread_quality(opens, closes, highs, lows)

    # 6. Relative Flow (needs SPY data)
    if spy_bars is not None:
        spy_closes = spy_bars.get("close", np.array([]))
        factors["relative_flow"] = score_relative_flow(closes, spy_closes)
    else:
        factors["relative_flow"] = {"score": 0.0, "available": False}

    # Weight normalization: redistribute unavailable factor weights
    available_weights = {}
    unavailable = []
    for name, w in weights.items():
        f = factors.get(name, {})
        if f.get("available", False):
            available_weights[name] = w
        else:
            unavailable.append(name)

    available_sum = sum(available_weights.values())
    if available_sum > 0 and available_sum < 1.0:
        scale = 1.0 / available_sum
        normalized_weights = {k: v * scale for k, v in available_weights.items()}
    else:
        normalized_weights = dict(available_weights)

    # Weighted total: factor scores [-1, +1], scaled to [-10, +10]
    total = 0.0
    for name, w in normalized_weights.items():
        factor_score = factors.get(name, {}).get("score", 0.0)
        total += factor_score * w * 10.0

    return {
        "total_score": round(total, 3),
        "factors": factors,
        "weights_used": normalized_weights,
        "unavailable_factors": unavailable,
    }
