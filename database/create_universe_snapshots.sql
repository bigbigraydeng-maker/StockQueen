-- StockQueen V5: Dynamic Universe Snapshots
-- Stores universe refresh results in Supabase so data survives Render redeploys.
--
-- Run once in Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS universe_snapshots (
    id            BIGSERIAL    PRIMARY KEY,
    snapshot_date DATE         NOT NULL,
    is_latest     BOOLEAN      NOT NULL DEFAULT FALSE,
    total_screened  INTEGER,
    step1_candidates INTEGER,
    step2_passed    INTEGER,
    final_count   INTEGER      NOT NULL,
    tickers       JSONB        NOT NULL,  -- array of {ticker,name,exchange,sector,...}
    filters       JSONB,                  -- {min_market_cap, min_avg_volume, ...}
    elapsed_seconds FLOAT,
    refreshed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Only one row can be "latest" at a time
CREATE UNIQUE INDEX IF NOT EXISTS universe_snapshots_latest_idx
    ON universe_snapshots (is_latest) WHERE is_latest = TRUE;

CREATE INDEX IF NOT EXISTS universe_snapshots_date_idx
    ON universe_snapshots (snapshot_date DESC);

-- Grant access for service role (Supabase default)
COMMENT ON TABLE universe_snapshots IS
    'Dynamic stock universe snapshots built by UniverseService.refresh_universe().';
