-- C5: Retail Sentiment Regime Gate
-- 每日盘后记录散户情绪 Regime，供 ED 策略入场门控使用

CREATE TABLE IF NOT EXISTS retail_sentiment_regime (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL UNIQUE,           -- 美东交易日

    -- CBOE Put/Call 比率
    pc_ratio        NUMERIC(6, 4),                  -- EQUITY_PC_RATIO，NULL = 获取失败
    pc_signal       TEXT,                           -- greed/neutral/neutral_high/fear/unavailable

    -- Reddit WSB 提及
    wsb_top_mentions JSONB DEFAULT '[]'::JSONB,     -- [{ticker, count, zscore}, ...] top20
    wsb_meme_tickers JSONB DEFAULT '[]'::JSONB,     -- zscore > 2.0 的 ticker 列表

    -- 综合判断（核心输出）
    meme_mode       BOOLEAN NOT NULL DEFAULT FALSE,
    meme_intensity  TEXT    NOT NULL DEFAULT 'normal',  -- extreme/elevated/normal/fear/unavailable
    rationale       TEXT,                               -- 简短解释（DeepSeek 或规则生成）

    -- 元数据
    data_sources    JSONB DEFAULT '{}'::JSONB,      -- {cboe: bool, wsb: bool}
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_retail_sentiment_date
    ON retail_sentiment_regime (date DESC);

CREATE INDEX IF NOT EXISTS idx_retail_sentiment_meme
    ON retail_sentiment_regime (meme_mode, date DESC)
    WHERE meme_mode = TRUE;

ALTER TABLE retail_sentiment_regime ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON retail_sentiment_regime
    FOR ALL USING (true);
