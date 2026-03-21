-- SEC EDGAR Form 4 Insider Trading Tables
-- 存储内幕人士交易申报数据（已清洗），用于生成 insider 信号

-- ============================================================
-- 1. Raw 清洗后的 Form 4 交易记录
-- ============================================================

CREATE TABLE IF NOT EXISTS insider_transactions (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- EDGAR 申报标识（唯一去重键）
    accession_number     TEXT NOT NULL,          -- e.g. "0001234567-26-123456"
    filing_date          DATE NOT NULL,          -- EDGAR 申报日期
    transaction_date     DATE NOT NULL,          -- 实际交易日期

    -- 证券信息
    ticker               TEXT NOT NULL,          -- 股票代码（大写）
    company_name         TEXT,                   -- 公司名称

    -- 申报人信息
    cik                  TEXT NOT NULL,          -- 公司 CIK
    insider_cik          TEXT,                   -- 内幕人士 CIK
    insider_name         TEXT NOT NULL,          -- 姓名（原始大写，已规范化）
    insider_title        TEXT,                   -- 职位原文（如 "Chief Executive Officer"）
    title_normalized     TEXT,                   -- 规范化职位（如 "ceo"）
    is_director          BOOLEAN NOT NULL DEFAULT FALSE,
    is_officer           BOOLEAN NOT NULL DEFAULT FALSE,
    is_ten_pct_owner     BOOLEAN NOT NULL DEFAULT FALSE,

    -- 交易明细（仅保留 P/S，已过滤期权行权等）
    transaction_code     TEXT NOT NULL CHECK (transaction_code IN ('P', 'S')),
    -- P = 公开市场买入, S = 公开市场卖出

    shares               FLOAT NOT NULL CHECK (shares > 0),
    price_per_share      FLOAT,                  -- NULL 表示无价格（赠与等已在上游过滤）
    notional_value       FLOAT,                  -- shares × price_per_share
    acquired_or_disposed TEXT CHECK (acquired_or_disposed IN ('A', 'D')),
    -- A = 取得, D = 处置

    shares_owned_after   FLOAT,                  -- 交易后持仓量（用于判断比例）
    -- 持仓比例变化 = shares / NULLIF(shares_owned_after, 0) * 100
    pct_of_holdings      FLOAT,                  -- 本次交易占总持仓的百分比

    -- 元数据
    source_url           TEXT,                   -- XML 原始 URL（调试用）
    created_at           TIMESTAMPTZ DEFAULT NOW(),

    -- 复合去重键：同一申报+同一内幕人+同一交易类型+同一日期
    UNIQUE (accession_number, insider_name, transaction_code, transaction_date)
);

-- 查询索引
CREATE INDEX IF NOT EXISTS idx_insider_txn_ticker      ON insider_transactions (ticker);
CREATE INDEX IF NOT EXISTS idx_insider_txn_date        ON insider_transactions (transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_insider_txn_filing_date ON insider_transactions (filing_date DESC);
CREATE INDEX IF NOT EXISTS idx_insider_txn_code        ON insider_transactions (transaction_code);
CREATE INDEX IF NOT EXISTS idx_insider_txn_notional    ON insider_transactions (notional_value DESC);

-- RLS（与其他表保持一致）
ALTER TABLE insider_transactions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow all for service role" ON insider_transactions
    FOR ALL USING (true);

-- ============================================================
-- 说明（写入 event_signals 的字段映射）
-- ============================================================
-- 聚合信号写入已有的 event_signals 表，字段映射：
--   event_type  → 'insider_cluster_buy' / 'insider_ceo_buy' /
--                  'insider_large_buy' / 'insider_director_buy' /
--                  'insider_cluster_sell' / 'insider_large_sell'
--   direction   → 'bullish' (P) / 'bearish' (S)
--   signal_strength → 0.45–0.90（按规则分级）
--   relevance_score → 1.0（结构化数据，无噪音）
--   sentiment_score → +signal_strength (买) / -signal_strength (卖)
--   source      → 'SEC EDGAR Form 4'
--   url         → accession URL（去重键）
--   headline    → 人类可读描述
--   summary     → 详细交易明细
