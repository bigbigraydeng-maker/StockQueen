-- 盘中动能持续追踪：一轮一表头 + 按票聚合
-- 在 Supabase SQL Editor 执行，或与 CLI 迁移一并应用；仅新增，不删改既有表

-- 1) 每 30min 评分轮次的元数据（便于按日查询「跑了多少轮」、Top5 快照）
CREATE TABLE IF NOT EXISTS public.intraday_rounds (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_date date NOT NULL,
    round_number integer NOT NULL,
    scored_at timestamptz NOT NULL,
    total_scored integer NOT NULL DEFAULT 0,
    rows_persisted integer NOT NULL DEFAULT 0,
    top5 jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT intraday_rounds_session_round UNIQUE (session_date, round_number)
);

CREATE INDEX IF NOT EXISTS idx_intraday_rounds_session_scored
    ON public.intraday_rounds (session_date, scored_at DESC);

COMMENT ON TABLE public.intraday_rounds IS '盘中多因子评分：每一轮（约30min）一条元数据，含 Top5 摘要';

-- 2) 按「交易日 + 标的」聚合：持续追踪当日排名/分数变化（动能是否在榜、名次升降）
CREATE TABLE IF NOT EXISTS public.intraday_momentum_daily (
    session_date date NOT NULL,
    ticker text NOT NULL,
    latest_rank integer,
    latest_total_score double precision,
    latest_round_number integer,
    latest_scored_at timestamptz,
    best_rank integer,
    worst_rank integer,
    rounds_in_top20 integer NOT NULL DEFAULT 0,
    rank_history jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_date, ticker)
);

CREATE INDEX IF NOT EXISTS idx_momentum_daily_session_rank
    ON public.intraday_momentum_daily (session_date, latest_rank);

COMMENT ON TABLE public.intraday_momentum_daily IS '盘中动能：同一交易日每只标的一条聚合，记录最佳/最差名次与最近若干轮名次序列';

-- 可选：已有 intraday_scores 与 (session_date, round_number, ticker) 的关联仅通过字段隐含；
-- 若日后需要强关联，可再加 round_id uuid REFERENCES intraday_rounds(id)。
