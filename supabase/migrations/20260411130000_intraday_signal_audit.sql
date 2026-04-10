-- 盘中信号审计：用于监控大屏「信号反馈 / 因子有效性」
-- 仅新增表与索引，不删改既有对象。
-- 写入时机：铃铛评分落库时由应用插入；ret_5m/ret_30m 由定时任务回填。

CREATE TABLE IF NOT EXISTS public.intraday_signal_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_date date NOT NULL,
    round_number integer NOT NULL,
    ticker text NOT NULL,
    triggered_at timestamptz NOT NULL,
    source text NOT NULL DEFAULT 'intraday_scoring',
    total_score double precision,
    factors jsonb,
    price_at_signal double precision,
    ret_5m double precision,
    ret_30m double precision,
    exit_pnl_pct double precision,
    outcome_label text,
    failure_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT intraday_signal_audit_unique_event UNIQUE (session_date, round_number, ticker, source)
);

CREATE INDEX IF NOT EXISTS idx_intraday_signal_audit_session_triggered
    ON public.intraday_signal_audit (session_date, triggered_at DESC);

CREATE INDEX IF NOT EXISTS idx_intraday_signal_audit_ticker_date
    ON public.intraday_signal_audit (ticker, session_date DESC);

CREATE INDEX IF NOT EXISTS idx_intraday_signal_audit_pending_ret
    ON public.intraday_signal_audit (triggered_at)
    WHERE ret_5m IS NULL;

COMMENT ON TABLE public.intraday_signal_audit IS '盘中信号审计：评分触发快照与事后收益/标签，供监控大屏与因子有效性分析';
COMMENT ON COLUMN public.intraday_signal_audit.session_date IS '美东交易日';
COMMENT ON COLUMN public.intraday_signal_audit.source IS '信号来源，如 intraday_scoring';
COMMENT ON COLUMN public.intraday_signal_audit.factors IS '触发时六因子快照 JSON';
COMMENT ON COLUMN public.intraday_signal_audit.ret_5m IS '触发后约 5 分钟收益（小数，如 0.003=0.3%），定时回填';
COMMENT ON COLUMN public.intraday_signal_audit.ret_30m IS '触发后约 30 分钟收益，定时回填';
COMMENT ON COLUMN public.intraday_signal_audit.outcome_label IS '如 pending, ok, false_breakout, stop_loss';
