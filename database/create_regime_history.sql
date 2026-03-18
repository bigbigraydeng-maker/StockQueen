-- Regime History table: tracks daily regime detection results
-- Used by regime_monitor.py to detect regime transitions and send alerts

CREATE TABLE IF NOT EXISTS regime_history (
    id          BIGSERIAL PRIMARY KEY,
    date        DATE NOT NULL UNIQUE,
    regime      TEXT NOT NULL,               -- strong_bull | bull | choppy | bear
    score       INTEGER NOT NULL,            -- raw score [-5, +5]
    spy_price   NUMERIC(10, 2) DEFAULT 0,
    signals     JSONB,                       -- compact signal breakdown
    changed_from TEXT,                        -- previous regime if changed, NULL if stable
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookups by date (descending for "latest" queries)
CREATE INDEX IF NOT EXISTS idx_regime_history_date ON regime_history (date DESC);

-- Index for finding regime changes quickly
CREATE INDEX IF NOT EXISTS idx_regime_history_changed ON regime_history (changed_from) WHERE changed_from IS NOT NULL;
