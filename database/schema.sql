-- StockQueen V1 - Database Schema
-- Supabase PostgreSQL Schema
-- Created: 2025-02-25

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- 1. EVENTS TABLE - Raw news from RSS feeds
-- ============================================
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticker VARCHAR(10),
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT NOT NULL UNIQUE,
    source VARCHAR(50) NOT NULL, -- 'pr_newswire', 'fda'
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'filtered', 'processed', 'error'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for events
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_published_at ON events(published_at);
CREATE INDEX IF NOT EXISTS idx_events_ticker ON events(ticker);

-- ============================================
-- 2. AI_EVENTS TABLE - DeepSeek classification results
-- ============================================
CREATE TABLE IF NOT EXISTS ai_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    ticker VARCHAR(10),
    is_valid_event BOOLEAN NOT NULL,
    event_type VARCHAR(50) NOT NULL, -- 'Phase3_Positive', 'FDA_Approval', etc.
    direction_bias VARCHAR(10) NOT NULL, -- 'long', 'short', 'none'
    raw_response TEXT, -- Original AI response for audit
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for ai_events
CREATE INDEX IF NOT EXISTS idx_ai_events_event_id ON ai_events(event_id);
CREATE INDEX IF NOT EXISTS idx_ai_events_is_valid ON ai_events(is_valid_event);
CREATE INDEX IF NOT EXISTS idx_ai_events_event_type ON ai_events(event_type);
CREATE INDEX IF NOT EXISTS idx_ai_events_direction ON ai_events(direction_bias);

-- ============================================
-- 3. MARKET_SNAPSHOT TABLE - Tiger API market data
-- ============================================
CREATE TABLE IF NOT EXISTS market_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticker VARCHAR(10) NOT NULL,
    event_id UUID NOT NULL REFERENCES ai_events(id) ON DELETE CASCADE,
    prev_close DECIMAL(12, 4) NOT NULL,
    day_open DECIMAL(12, 4) NOT NULL,
    day_high DECIMAL(12, 4) NOT NULL,
    day_low DECIMAL(12, 4) NOT NULL,
    current_price DECIMAL(12, 4) NOT NULL,
    day_change_pct DECIMAL(8, 4) NOT NULL,
    volume BIGINT NOT NULL,
    avg_volume_30d BIGINT NOT NULL,
    market_cap DECIMAL(15, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for market_snapshots
CREATE INDEX IF NOT EXISTS idx_market_snapshots_event_id ON market_snapshots(event_id);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_ticker ON market_snapshots(ticker);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_change_pct ON market_snapshots(day_change_pct);

-- ============================================
-- 4. SIGNALS TABLE - Trading signals
-- ============================================
CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticker VARCHAR(10) NOT NULL,
    event_id UUID NOT NULL REFERENCES ai_events(id) ON DELETE CASCADE,
    market_snapshot_id UUID NOT NULL REFERENCES market_snapshots(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'observe', -- 'observe', 'confirmed', 'trade', 'executed', 'closed', 'cancelled'
    direction VARCHAR(10) NOT NULL, -- 'long', 'short'
    entry_price DECIMAL(12, 4),
    stop_loss DECIMAL(12, 4),
    target_price DECIMAL(12, 4),
    confidence_score DECIMAL(5, 2), -- 0-100
    human_confirmed BOOLEAN DEFAULT FALSE,
    confirmed_at TIMESTAMP WITH TIME ZONE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for signals
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
CREATE INDEX IF NOT EXISTS idx_signals_direction ON signals(direction);
CREATE INDEX IF NOT EXISTS idx_signals_event_id ON signals(event_id);
CREATE INDEX IF NOT EXISTS idx_signals_human_confirmed ON signals(human_confirmed);

-- ============================================
-- 5. ORDERS TABLE - Trading orders via Tiger API
-- ============================================
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    signal_id UUID NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    ticker VARCHAR(10) NOT NULL,
    direction VARCHAR(10) NOT NULL, -- 'long', 'short'
    order_type VARCHAR(20) DEFAULT 'limit', -- 'limit', 'market', 'stop'
    side VARCHAR(10) NOT NULL, -- 'buy', 'sell'
    quantity INTEGER NOT NULL,
    price DECIMAL(12, 4),
    stop_price DECIMAL(12, 4),
    tiger_order_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'submitted', 'filled', 'partial', 'cancelled', 'error'
    filled_quantity INTEGER DEFAULT 0,
    filled_price DECIMAL(12, 4),
    filled_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for orders
CREATE INDEX IF NOT EXISTS idx_orders_signal_id ON orders(signal_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_tiger_id ON orders(tiger_order_id);

-- ============================================
-- 6. TRADES TABLE - Completed trades with P&L
-- ============================================
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    signal_id UUID NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    ticker VARCHAR(10) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    entry_price DECIMAL(12, 4) NOT NULL,
    exit_price DECIMAL(12, 4),
    quantity INTEGER NOT NULL,
    pnl DECIMAL(12, 4),
    pnl_pct DECIMAL(8, 4),
    entry_at TIMESTAMP WITH TIME ZONE NOT NULL,
    exit_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) DEFAULT 'open', -- 'open', 'closed'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for trades
CREATE INDEX IF NOT EXISTS idx_trades_signal_id ON trades(signal_id);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);

-- ============================================
-- 7. RISK_STATE TABLE - Current risk state
-- ============================================
CREATE TABLE IF NOT EXISTS risk_state (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    current_positions INTEGER DEFAULT 0,
    open_position_value DECIMAL(15, 2) DEFAULT 0.00,
    account_equity DECIMAL(15, 2) DEFAULT 0.00,
    max_drawdown_pct DECIMAL(8, 4) DEFAULT 0.00,
    consecutive_losses INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'normal', -- 'normal', 'warning', 'paused'
    last_trade_pnl DECIMAL(12, 4),
    paused_at TIMESTAMP WITH TIME ZONE,
    resume_at TIMESTAMP WITH TIME ZONE,
    alert_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for risk_state
CREATE INDEX IF NOT EXISTS idx_risk_state_status ON risk_state(status);

-- Insert initial risk state
INSERT INTO risk_state (id, current_positions, status)
VALUES (uuid_generate_v4(), 0, 'normal')
ON CONFLICT DO NOTHING;

-- ============================================
-- 8. SYSTEM_LOGS TABLE - Application logs
-- ============================================
CREATE TABLE IF NOT EXISTS system_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    level VARCHAR(20) NOT NULL,
    logger VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    module VARCHAR(100),
    function VARCHAR(100),
    line INTEGER,
    extra JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for system_logs
CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level);
CREATE INDEX IF NOT EXISTS idx_system_logs_created_at ON system_logs(created_at);

-- ============================================
-- 9. API_CALL_LOGS TABLE - External API call logs
-- ============================================
CREATE TABLE IF NOT EXISTS api_call_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service VARCHAR(50) NOT NULL, -- 'tiger', 'deepseek', 'twilio'
    endpoint VARCHAR(255),
    method VARCHAR(10),
    request_body JSONB,
    response_body JSONB,
    status_code INTEGER,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for api_call_logs
CREATE INDEX IF NOT EXISTS idx_api_call_logs_service ON api_call_logs(service);
CREATE INDEX IF NOT EXISTS idx_api_call_logs_created_at ON api_call_logs(created_at);

-- ============================================
-- TRIGGERS - Auto-update updated_at timestamp
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for all tables
CREATE TRIGGER update_events_updated_at BEFORE UPDATE ON events
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_ai_events_updated_at BEFORE UPDATE ON ai_events
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_market_snapshots_updated_at BEFORE UPDATE ON market_snapshots
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_signals_updated_at BEFORE UPDATE ON signals
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_orders_updated_at BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_trades_updated_at BEFORE UPDATE ON trades
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_risk_state_updated_at BEFORE UPDATE ON risk_state
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- ROW LEVEL SECURITY (RLS) - Enable for security
-- ============================================
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_state ENABLE ROW LEVEL SECURITY;

-- Create policy to allow all operations for service role
CREATE POLICY "Enable all for service role" ON events
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Enable all for service role" ON ai_events
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Enable all for service role" ON market_snapshots
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Enable all for service role" ON signals
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Enable all for service role" ON orders
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Enable all for service role" ON trades
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Enable all for service role" ON risk_state
    FOR ALL USING (true) WITH CHECK (true);

-- ============================================
-- 10. KNOWLEDGE_BASE TABLE - RAG 知识库
-- ============================================
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_base (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- 内容
    content TEXT NOT NULL,
    summary TEXT,
    embedding vector(1536),

    -- 分类
    source_type TEXT NOT NULL,            -- 'auto_signal_result' / 'auto_news_outcome' /
                                          -- 'auto_pattern_stat' / 'auto_sector_rotation' /
                                          -- 'user_feed_text' / 'user_feed_url'
    category TEXT,                         -- 'trade_result' / 'news_analysis' / 'technical' /
                                          -- 'sector' / 'macro' / 'research' / 'opinion'

    -- 关联
    tickers TEXT[],
    tags TEXT[],

    -- 时效性
    relevance_date DATE,
    expires_at TIMESTAMP WITH TIME ZONE,

    -- 元数据
    metadata JSONB,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 向量相似度搜索索引
CREATE INDEX IF NOT EXISTS idx_knowledge_embedding ON knowledge_base
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge_base(source_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_tickers ON knowledge_base USING GIN(tickers);
CREATE INDEX IF NOT EXISTS idx_knowledge_tags ON knowledge_base USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_knowledge_date ON knowledge_base(relevance_date DESC);

-- RLS
ALTER TABLE knowledge_base ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Enable all for service role" ON knowledge_base
    FOR ALL USING (true) WITH CHECK (true);

-- Trigger
CREATE TRIGGER update_knowledge_base_updated_at BEFORE UPDATE ON knowledge_base
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- 11. SIGNAL_OUTCOMES TABLE - 信号结果追踪
-- ============================================
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    signal_id UUID REFERENCES signals(id) ON DELETE SET NULL,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price DECIMAL(12, 4),
    entry_date TIMESTAMP WITH TIME ZONE,

    -- 多时间窗口结果
    price_1d DECIMAL(12, 4),
    price_5d DECIMAL(12, 4),
    price_20d DECIMAL(12, 4),
    return_1d DECIMAL(8, 4),
    return_5d DECIMAL(8, 4),
    return_20d DECIMAL(8, 4),

    -- 止损止盈
    hit_stop_loss BOOLEAN DEFAULT FALSE,
    hit_take_profit BOOLEAN DEFAULT FALSE,
    exit_price DECIMAL(12, 4),
    exit_date TIMESTAMP WITH TIME ZONE,
    exit_reason TEXT,

    -- 上下文
    market_regime TEXT,
    spy_change_on_entry DECIMAL(8, 4),

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signal_outcomes_signal ON signal_outcomes(signal_id);
CREATE INDEX IF NOT EXISTS idx_signal_outcomes_ticker ON signal_outcomes(ticker);
CREATE INDEX IF NOT EXISTS idx_signal_outcomes_entry_date ON signal_outcomes(entry_date DESC);

ALTER TABLE signal_outcomes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Enable all for service role" ON signal_outcomes
    FOR ALL USING (true) WITH CHECK (true);

CREATE TRIGGER update_signal_outcomes_updated_at BEFORE UPDATE ON signal_outcomes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- 12. VECTOR SEARCH RPC FUNCTION
-- ============================================
CREATE OR REPLACE FUNCTION match_knowledge(
    query_embedding vector(1536),
    match_count int DEFAULT 5,
    filter_source_type text DEFAULT NULL,
    filter_category text DEFAULT NULL
)
RETURNS TABLE (
    id uuid,
    content text,
    summary text,
    source_type text,
    category text,
    tickers text[],
    tags text[],
    relevance_date date,
    created_at timestamptz,
    metadata jsonb,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        kb.id,
        kb.content,
        kb.summary,
        kb.source_type,
        kb.category,
        kb.tickers,
        kb.tags,
        kb.relevance_date,
        kb.created_at,
        kb.metadata,
        1 - (kb.embedding <=> query_embedding) AS similarity
    FROM knowledge_base kb
    WHERE
        kb.embedding IS NOT NULL
        AND (filter_source_type IS NULL OR kb.source_type = filter_source_type)
        AND (filter_category IS NULL OR kb.category = filter_category)
        AND (kb.expires_at IS NULL OR kb.expires_at > NOW())
    ORDER BY kb.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ============================================
-- 13. ROTATION_SNAPSHOTS TABLE - Weekly rotation snapshots
-- ============================================
CREATE TABLE IF NOT EXISTS rotation_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    snapshot_date DATE NOT NULL,
    regime VARCHAR(10) NOT NULL,          -- 'bull' / 'bear'
    spy_price DECIMAL(12, 4),
    spy_ma50 DECIMAL(12, 4),
    scores JSONB,                         -- full scoring array
    selected_tickers TEXT[] NOT NULL,      -- top N tickers
    previous_tickers TEXT[],              -- last week's top N
    changes JSONB,                        -- {"added": [...], "removed": [...]}
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rotation_snapshots_date ON rotation_snapshots(snapshot_date DESC);

ALTER TABLE rotation_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Enable all for service role" ON rotation_snapshots
    FOR ALL USING (true) WITH CHECK (true);

CREATE TRIGGER update_rotation_snapshots_updated_at BEFORE UPDATE ON rotation_snapshots
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- 14. ROTATION_POSITIONS TABLE - Active position tracking
-- ============================================
CREATE TABLE IF NOT EXISTS rotation_positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticker VARCHAR(10) NOT NULL,
    direction VARCHAR(10) DEFAULT 'long',
    entry_price DECIMAL(12, 4),
    entry_date DATE,
    stop_loss DECIMAL(12, 4),
    take_profit DECIMAL(12, 4),
    atr14 DECIMAL(12, 4),
    current_price DECIMAL(12, 4),
    unrealized_pnl_pct DECIMAL(8, 4),
    status VARCHAR(20) DEFAULT 'pending_entry', -- 'pending_entry', 'active', 'pending_exit', 'closed'
    exit_price DECIMAL(12, 4),
    exit_date DATE,
    exit_reason VARCHAR(50),              -- 'stop_loss', 'take_profit', 'rotation_exit'
    snapshot_id UUID REFERENCES rotation_snapshots(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rotation_positions_status ON rotation_positions(status);
CREATE INDEX IF NOT EXISTS idx_rotation_positions_ticker ON rotation_positions(ticker);

ALTER TABLE rotation_positions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Enable all for service role" ON rotation_positions
    FOR ALL USING (true) WITH CHECK (true);

CREATE TRIGGER update_rotation_positions_updated_at BEFORE UPDATE ON rotation_positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
