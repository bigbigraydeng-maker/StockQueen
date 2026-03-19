-- ML Exit Scorer Signals Table
-- Signal collection mode: log ML predictions without executing trades
-- Run in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS exit_scorer_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date            DATE NOT NULL,
    ticker          TEXT NOT NULL,
    exit_prob       FLOAT NOT NULL,          -- model output: P(exit now)
    signal          BOOLEAN NOT NULL,        -- exit_prob >= threshold
    threshold       FLOAT NOT NULL DEFAULT 0.65,
    -- Position snapshot at time of signal
    days_held       INTEGER,
    unrealized_pnl_pct  FLOAT,
    pnl_peak_pct        FLOAT,
    pnl_drawdown_from_peak FLOAT,
    -- Context
    regime          TEXT,
    etf_category    TEXT,
    -- Full feature vector (for retraining)
    features_json   JSONB,
    -- Outcome (filled in retrospectively for retraining)
    outcome_forward_3d_return FLOAT,         -- actual return 3 days later
    outcome_stop_triggered    BOOLEAN,       -- did stop trigger within 5 days?
    outcome_filled_at         DATE,          -- when outcome was filled
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Unique per ticker per day (one signal per position per day)
CREATE UNIQUE INDEX IF NOT EXISTS idx_exit_scorer_date_ticker
    ON exit_scorer_signals (date, ticker);

CREATE INDEX IF NOT EXISTS idx_exit_scorer_date
    ON exit_scorer_signals (date DESC);

CREATE INDEX IF NOT EXISTS idx_exit_scorer_signal
    ON exit_scorer_signals (signal) WHERE signal = true;

-- Row-level security
ALTER TABLE exit_scorer_signals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow all for service role" ON exit_scorer_signals
    FOR ALL USING (true);
