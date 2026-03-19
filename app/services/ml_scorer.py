"""
StockQueen ML Enhancement Layer (Step 2) — Offensive Ranker
XGBoost ranking model optimized for finding high-growth winners.

Architecture:
  Layer 1 (frozen): Rule-based multi-factor scoring → candidate pool (defense)
  Layer 2 (this):   ML re-ranking → find breakout candidates (offense)

Design Philosophy:
  - Multi-strategy matrix already handles defense (regime, VIX, cash, stops)
  - ML's job is OFFENSE: identify stocks most likely to outperform the pool
  - Label = cross-sectional rank (relative outperformance, not absolute return)
  - Objective = rank:pairwise (optimize ranking quality, not prediction accuracy)
  - Features include "attack" signals: momentum acceleration, volume surge, new highs

Principles:
  - ML does NOT modify strategy parameters, risk controls, or execution logic
  - ML ONLY re-ranks candidates that already passed Layer 1 filtering
  - Walk-forward training prevents overfitting
  - Baseline comparison always available for A/B evaluation
"""

import logging
import pickle
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Model persistence directory
MODEL_DIR = Path(__file__).parent.parent.parent / "models" / "ml_ranker"

# ============================================================
# Feature Extraction — offensive + base features
# ============================================================

FEATURE_NAMES = [
    # ── Base features (from multi_factor_scorer) ──
    "ret_1w", "ret_1m", "ret_3m", "volatility", "momentum_score",
    "rsi", "macd_hist", "bb_pos", "adx", "technical_score",
    "trend_score", "rs_score",
    # ── Regime context (one-hot) ──
    "regime_strong_bull", "regime_bull", "regime_choppy", "regime_bear",
    # ── Composite ──
    "rule_score",
    # ── Offensive features (NEW) ──
    "momentum_accel",     # ret_1w / ret_1m — acceleration signal
    "volume_surge",       # recent vol / avg vol — breakout signal
    "new_high_pct",       # close / 52w high — proximity to breakout
    "upside_vol",         # std of positive returns — good volatility
    "drawdown_from_peak", # shallow drawdown = strong base
]

NUM_FEATURES = len(FEATURE_NAMES)


def extract_features(
    scorer_result: dict,
    regime: str,
    closes: np.ndarray = None,
    volumes: np.ndarray = None,
    highs: np.ndarray = None,
) -> np.ndarray:
    """
    Extract ML feature vector with offensive features.

    Args:
        scorer_result: output of compute_multi_factor_score()
        regime: current market regime string
        closes: OHLCV close array (for computing offensive features)
        volumes: OHLCV volume array
        highs: OHLCV high array

    Returns:
        1D numpy array of shape (NUM_FEATURES,)
    """
    factors = scorer_result.get("factors", {})
    mom = factors.get("momentum", {})
    tech = factors.get("technical", {})
    trend = factors.get("trend", {})
    rs = factors.get("relative_strength", {})

    # Regime one-hot
    regime_oh = [
        1.0 if regime == "strong_bull" else 0.0,
        1.0 if regime == "bull" else 0.0,
        1.0 if regime == "choppy" else 0.0,
        1.0 if regime == "bear" else 0.0,
    ]

    # ── Offensive features ──
    ret_1w = mom.get("ret_1w", 0.0)
    ret_1m = mom.get("ret_1m", 0.0)

    # Momentum acceleration: 1w return relative to 1m return
    # High = accelerating upward; Low = decelerating
    if abs(ret_1m) > 0.001:
        momentum_accel = ret_1w / abs(ret_1m)
    else:
        momentum_accel = 0.0
    momentum_accel = max(-5.0, min(5.0, momentum_accel))

    # Volume surge: recent 5d avg volume / 20d avg volume
    volume_surge = 0.0
    if volumes is not None and len(volumes) >= 20:
        avg_5d = float(np.mean(volumes[-5:]))
        avg_20d = float(np.mean(volumes[-20:]))
        if avg_20d > 0:
            volume_surge = avg_5d / avg_20d
        volume_surge = max(0.0, min(5.0, volume_surge))

    # New high proximity: close / 52-week high
    new_high_pct = 0.0
    if closes is not None and len(closes) >= 5:
        lookback = min(252, len(closes))
        if highs is not None and len(highs) >= lookback:
            high_52w = float(np.max(highs[-lookback:]))
        else:
            high_52w = float(np.max(closes[-lookback:]))
        if high_52w > 0:
            new_high_pct = float(closes[-1]) / high_52w

    # Upside volatility: std of positive daily returns only
    upside_vol = 0.0
    if closes is not None and len(closes) >= 22:
        daily_rets = np.diff(closes[-22:]) / closes[-22:-1]
        positive_rets = daily_rets[daily_rets > 0]
        if len(positive_rets) >= 3:
            upside_vol = float(np.std(positive_rets) * np.sqrt(252))

    # Drawdown from peak: how far from recent high
    drawdown_from_peak = 0.0
    if closes is not None and len(closes) >= 20:
        recent_high = float(np.max(closes[-63:])) if len(closes) >= 63 else float(np.max(closes[-20:]))
        if recent_high > 0:
            drawdown_from_peak = (float(closes[-1]) - recent_high) / recent_high

    features = np.array([
        # Base features
        ret_1w,
        ret_1m,
        mom.get("ret_3m", 0.0),
        mom.get("vol", 0.0),
        mom.get("score", 0.0),
        tech.get("rsi", 50.0),
        tech.get("macd_hist", 0.0),
        tech.get("bb_pos", 0.5),
        tech.get("adx", 0.0),
        tech.get("score", 0.0),
        trend.get("score", 0.0),
        rs.get("score", 0.0),
        # Regime
        *regime_oh,
        # Composite
        scorer_result.get("total_score", 0.0),
        # Offensive features
        momentum_accel,
        volume_surge,
        new_high_pct,
        upside_vol,
        drawdown_from_peak,
    ], dtype=np.float64)

    return features


def extract_features_batch(
    scored_items: list[dict],
    regime: str,
) -> tuple[np.ndarray, list[str]]:
    """
    Extract features for a batch of scored tickers.

    Args:
        scored_items: list of {ticker, scorer_result, closes?, volumes?, highs?}
        regime: current market regime

    Returns:
        (feature_matrix [N, NUM_FEATURES], ticker_list [N])
    """
    features_list = []
    tickers = []
    for item in scored_items:
        feat = extract_features(
            item["scorer_result"], regime,
            closes=item.get("closes"),
            volumes=item.get("volumes"),
            highs=item.get("highs"),
        )
        features_list.append(feat)
        tickers.append(item["ticker"])

    X = np.array(features_list) if features_list else np.empty((0, NUM_FEATURES))
    return X, tickers


# ============================================================
# Training Data Builder — cross-sectional ranking labels
# ============================================================

def build_training_data(
    weekly_snapshots: list[dict],
    histories: dict,
    lookahead_days: int = 5,
    asymmetric: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Build (X, y, groups) training data with cross-sectional ranking labels.

    Label design (offensive):
      y = cross-sectional z-score of forward return within each week's pool
      This teaches the model "who outperforms the pool" not "what's the absolute return"

    asymmetric=True (ML-V3A):
      y = z_raw * 1.5 if z_raw > 0 else z_raw * 0.5
      Amplifies upside signals so model prioritizes explosive winners over safe stocks.

    Groups: number of items per weekly snapshot (for rank:pairwise)

    Returns:
        (X [N_samples, NUM_FEATURES], y [N_samples], groups [N_weeks])
    """
    X_all = []
    y_all = []
    groups = []

    for snap in weekly_snapshots:
        regime = snap["regime"]
        date_idx = snap["date_idx"]

        # Collect all forward returns for this week's pool
        week_items = []
        for item in snap["scored_items"]:
            ticker = item["ticker"]
            h = histories.get(ticker)
            if h is None:
                continue

            closes = h["close"]
            if date_idx + lookahead_days >= len(closes):
                continue

            entry_price = closes[date_idx]
            exit_price = closes[date_idx + lookahead_days]
            if entry_price <= 0:
                continue

            fwd_return = (exit_price / entry_price) - 1.0

            feat = extract_features(
                item["scorer_result"], regime,
                closes=closes[:date_idx + 1],
                volumes=h.get("volume", np.array([]))[:date_idx + 1] if "volume" in h else None,
                highs=h.get("high", np.array([]))[:date_idx + 1] if "high" in h else None,
            )
            week_items.append((feat, fwd_return))

        if len(week_items) < 3:
            continue

        # Cross-sectional z-score: normalize returns within this week
        returns = np.array([r for _, r in week_items])
        mean_ret = np.mean(returns)
        std_ret = np.std(returns)
        if std_ret < 1e-8:
            std_ret = 1.0  # avoid division by zero

        for feat, fwd_ret in week_items:
            z_raw = (fwd_ret - mean_ret) / std_ret
            if asymmetric:
                z_score = z_raw * 1.5 if z_raw > 0 else z_raw * 0.5
            else:
                z_score = z_raw
            X_all.append(feat)
            y_all.append(z_score)

        groups.append(len(week_items))

    X = np.array(X_all) if X_all else np.empty((0, NUM_FEATURES))
    y = np.array(y_all) if y_all else np.empty(0)
    g = np.array(groups) if groups else np.empty(0, dtype=int)
    return X, y, g


# ============================================================
# XGBoost Ranking Model
# ============================================================

class MLRanker:
    """
    XGBoost pairwise ranking model — optimized for finding winners.
    Uses rank:pairwise objective to directly optimize ranking quality.
    """

    def __init__(self):
        self.model = None
        self.trained_at: Optional[str] = None
        self.train_samples: int = 0
        self.feature_names = FEATURE_NAMES

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        groups: np.ndarray = None,
        params: Optional[dict] = None,
    ) -> dict:
        """
        Train XGBoost ranker on (X, y, groups) data.

        For rank:pairwise, groups defines how many items belong to each query
        (each weekly snapshot = one query group).

        Returns training metrics dict.
        """
        try:
            import xgboost as xgb
        except ImportError:
            raise ImportError(
                "xgboost is required for ML ranking. "
                "Install with: pip install xgboost"
            )

        if len(X) < 50:
            logger.warning(f"Too few samples ({len(X)}) for ML training, skipping")
            return {"error": "insufficient_samples", "n_samples": len(X)}

        default_params = {
            "objective": "rank:pairwise",
            "max_depth": 4,
            "learning_rate": 0.05,
            "n_estimators": 200,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 10,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "random_state": 42,
            "verbosity": 0,
        }
        if params:
            default_params.update(params)

        n_estimators = default_params.pop("n_estimators", 200)
        random_state = default_params.pop("random_state", 42)
        verbosity = default_params.pop("verbosity", 0)

        self.model = xgb.XGBRanker(
            n_estimators=n_estimators,
            random_state=random_state,
            verbosity=verbosity,
            **default_params,
        )

        # groups is required for XGBRanker
        if groups is None or len(groups) == 0:
            # Fallback: treat all as one group
            groups = np.array([len(X)])

        self.model.fit(X, y, group=groups)
        self.trained_at = datetime.now().isoformat()
        self.train_samples = len(X)

        # Training metrics
        train_pred = self.model.predict(X)
        corr = float(np.corrcoef(y, train_pred)[0, 1]) if len(y) > 1 else 0.0

        # Ranking quality: top-quartile vs bottom-quartile actual z-scores
        n = len(y)
        q_size = max(1, n // 4)
        pred_ranks = np.argsort(-train_pred)
        top_q_actual = float(np.mean(y[pred_ranks[:q_size]]))
        bottom_q_actual = float(np.mean(y[pred_ranks[-q_size:]]))
        rank_spread = top_q_actual - bottom_q_actual

        # Feature importance
        importance = dict(zip(
            self.feature_names,
            [float(v) for v in self.model.feature_importances_],
        ))

        metrics = {
            "n_samples": len(X),
            "n_groups": len(groups),
            "correlation": corr,
            "rank_spread_train": rank_spread,
            "top_q_zscore": top_q_actual,
            "bottom_q_zscore": bottom_q_actual,
            "feature_importance": importance,
            "trained_at": self.trained_at,
        }
        logger.info(
            f"ML Ranker trained: {len(X)} samples, {len(groups)} groups, "
            f"corr={corr:.3f}, rank_spread={rank_spread:+.3f}"
        )
        return metrics

    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Predict ranking scores. Higher = more likely to outperform.
        """
        if self.model is None:
            raise RuntimeError("MLRanker not trained. Call train() first.")
        return self.model.predict(X)

    def rank(
        self,
        scored_items: list[dict],
        regime: str,
        top_n: int = 6,
    ) -> list[dict]:
        """
        Re-rank scored candidates using ML predictions.
        Main entry point for Plan B integration.
        """
        if self.model is None or len(scored_items) == 0:
            return scored_items[:top_n]

        X, tickers = extract_features_batch(scored_items, regime)
        ml_scores = self.predict(X)

        for item, ml_score in zip(scored_items, ml_scores):
            item["ml_score"] = float(ml_score)

        # Sort by ML ranking score (higher = better)
        reranked = sorted(scored_items, key=lambda x: x.get("ml_score", 0), reverse=True)

        logger.info(
            f"ML re-ranked {len(scored_items)} → top {top_n}: "
            f"{[item['ticker'] for item in reranked[:top_n]]}"
        )
        return reranked[:top_n]

    def save(self, path: Optional[str] = None):
        """Save trained model to disk."""
        if self.model is None:
            logger.warning("No model to save")
            return

        save_dir = Path(path) if path else MODEL_DIR
        save_dir.mkdir(parents=True, exist_ok=True)

        model_path = save_dir / "ml_ranker.pkl"
        meta = {
            "trained_at": self.trained_at,
            "train_samples": self.train_samples,
            "feature_names": self.feature_names,
            "model_type": "offensive_ranker_ml-v2",
        }

        with open(model_path, "wb") as f:
            pickle.dump({"model": self.model, "meta": meta}, f)

        logger.info(f"ML Ranker saved to {model_path}")

    def load(self, path: Optional[str] = None) -> bool:
        """Load trained model from disk."""
        load_dir = Path(path) if path else MODEL_DIR
        model_path = load_dir / "ml_ranker.pkl"

        if not model_path.exists():
            logger.info(f"No saved ML model at {model_path}")
            return False

        try:
            with open(model_path, "rb") as f:
                data = pickle.load(f)

            self.model = data["model"]
            meta = data.get("meta", {})
            self.trained_at = meta.get("trained_at")
            self.train_samples = meta.get("train_samples", 0)

            logger.info(
                f"ML Ranker loaded from {model_path} "
                f"(trained {self.trained_at}, {self.train_samples} samples)"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to load ML model: {e}")
            return False


# ============================================================
# ML-Enhanced Backtest Integration
# ============================================================

def ml_rerank_candidates(
    scored_list: list[tuple[str, float]],
    scorer_results: dict[str, dict],
    regime: str,
    ranker: 'MLRanker',
    top_n: int = 6,
    rerank_pool: int = 10,
    histories: dict = None,
    date_idx: int = 0,
) -> list[str]:
    """
    Plan B: Rule-based top pool → ML re-ranking → final selection.

    Args:
        scored_list: sorted [(ticker, rule_score), ...] from backtest
        scorer_results: {ticker: compute_multi_factor_score() output}
        regime: current market regime
        ranker: trained MLRanker instance
        top_n: final number to select
        rerank_pool: how many candidates to feed into ML
        histories: backtest histories for offensive feature computation
        date_idx: current backtest date index

    Returns:
        list of selected tickers (length = top_n)
    """
    if ranker is None or ranker.model is None:
        return [t for t, _ in scored_list[:top_n]]

    candidates = scored_list[:rerank_pool]

    scored_items = []
    for ticker, rule_score in candidates:
        sr = scorer_results.get(ticker)
        if sr is None:
            continue

        item = {
            "ticker": ticker,
            "score": rule_score,
            "scorer_result": sr,
        }

        # Attach OHLCV for offensive feature computation
        if histories and ticker in histories:
            h = histories[ticker]
            idx = min(date_idx + 1, len(h["close"]))
            item["closes"] = h["close"][:idx]
            item["volumes"] = h.get("volume", np.array([]))[:idx]
            item["highs"] = h.get("high", np.array([]))[:idx]

        scored_items.append(item)

    if len(scored_items) <= top_n:
        return [item["ticker"] for item in scored_items]

    reranked = ranker.rank(scored_items, regime, top_n=top_n)
    return [item["ticker"] for item in reranked]
