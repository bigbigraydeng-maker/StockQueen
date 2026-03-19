-- C2: After-Hours AI Event Signals Table
-- Run this migration in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS event_signals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date        DATE NOT NULL,
    ticker      TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    direction   TEXT NOT NULL CHECK (direction IN ('bullish', 'bearish', 'neutral')),
    headline    TEXT NOT NULL,
    summary     TEXT,
    signal_strength   FLOAT NOT NULL,
    relevance_score   FLOAT NOT NULL,
    sentiment_score   FLOAT NOT NULL,
    source      TEXT,
    url         TEXT UNIQUE,       -- dedup key
    published   TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_event_signals_date   ON event_signals (date DESC);
CREATE INDEX IF NOT EXISTS idx_event_signals_ticker ON event_signals (ticker);
CREATE INDEX IF NOT EXISTS idx_event_signals_type   ON event_signals (event_type);

-- Row-level security (match other tables pattern)
ALTER TABLE event_signals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow all for service role" ON event_signals
    FOR ALL USING (true);
