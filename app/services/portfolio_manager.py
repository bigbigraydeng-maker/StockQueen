"""
StockQueen 破浪 - Portfolio Manager
策略矩阵调度层：统一管理 宝典V4趋势 / 均值回归 / 事件驱动 三个策略的资金分配。

核心职责：
  1. 根据市场体制动态分配三个策略的资金比例
  2. VIX 信号作为全局调节器（不是独立策略）
  3. 处理策略间持仓冲突（同一只股票不重复计算）
  4. 确保总仓位不超过设定上限

资金分配矩阵（体制 → 各策略权重）：
  strong_bull:  V4=70%  均值回归=0%   事件驱动=30%
  bull:         V4=60%  均值回归=10%  事件驱动=30%
  choppy:       V4=30%  均值回归=50%  事件驱动=20%
  bear:         V4=20%  均值回归=0%   事件驱动=30%  剩余=现金

VIX 调节规则（叠加在体制分配之上）：
  VIX > 35:  全体策略仓位 × 0.7（保留30%现金缓冲）
  VIX > 25:  全体策略仓位 × 0.85
  VIX < 15:  正常执行

生产隔离原则：
  - 本模块不直接修改任何策略服务
  - 通过统一接口与各策略通信
  - 回测通过 scripts/test_strategy_matrix.py 执行
"""

import logging
import numpy as np
from typing import Optional
from datetime import datetime
from app.database import get_db

logger = logging.getLogger(__name__)

# ============================================================
# 每日信号缓存（内存缓存，服务器重启后清空，每日盘后调度器刷新）
# ============================================================
_signals_cache: dict = {}  # {"data": {...}, "cached_at": "2026-03-19T09:50:00"}
_DAILY_SIGNALS_CACHE_KEY = "daily_signals_cache"


def get_cached_daily_signals() -> Optional[dict]:
    """获取最近一次每日信号扫描结果（内存优先，DB 兜底）。"""
    data = _signals_cache.get("data")
    if data:
        return data

    try:
        r = (
            get_db()
            .table("cache_store")
            .select("value")
            .eq("key", _DAILY_SIGNALS_CACHE_KEY)
            .limit(1)
            .execute()
        )
        if r.data and r.data[0].get("value"):
            v = r.data[0]["value"]
            if isinstance(v, dict):
                _signals_cache["data"] = v
                _signals_cache["cached_at"] = datetime.now().isoformat()
                return v
    except Exception as e:
        logger.warning(f"[PM] get_cached_daily_signals DB fallback failed: {e}")
    return None


async def run_and_cache_daily_signals(vix: Optional[float] = None) -> dict:
    """运行每日信号扫描并缓存结果。由调度器每日盘后调用。"""
    result = await get_daily_signals(vix=vix)
    _signals_cache["data"] = result
    _signals_cache["cached_at"] = datetime.now().isoformat()
    try:
        get_db().table("cache_store").upsert(
            {"key": _DAILY_SIGNALS_CACHE_KEY, "value": result}
        ).execute()
    except Exception as e:
        logger.warning(f"[PM] daily signals cache persist failed: {e}")
    logger.info(f"[PM] 每日信号已缓存: regime={result.get('regime')} "
                f"MR={len(result.get('mr_candidates', []))} ED={len(result.get('ed_candidates', []))}")
    return result


def _ec_val(x) -> float:
    """从 equity_curve 元素中提取净值：兼容 float 和 V4 的 dict 格式"""
    return x["portfolio"] if isinstance(x, dict) else float(x)


# ============================================================
# 资金分配配置
# ============================================================

# 体制 → 策略资金分配矩阵 (按回测参数 commit a781e10)
# Hedge 从 V4 预算内扣除（例：bear V4=50% 中 Hedge=30% → Alpha=20%）
ALLOCATION_MATRIX = {
    "strong_bull": {"v4": 0.70, "mean_reversion": 0.00, "event_driven": 0.30},
    "bull":        {"v4": 0.60, "mean_reversion": 0.10, "event_driven": 0.30},
    "choppy":      {"v4": 0.30, "mean_reversion": 0.50, "event_driven": 0.20},
    "bear":        {"v4": 0.50, "mean_reversion": 0.00, "event_driven": 0.00},  # V4=50%, 内部 Hedge=30% → Alpha=20%
}

# VIX 全局调节阈值
VIX_DELEVERAGE_LEVELS = [
    (35.0, 0.70),   # VIX > 35：整体仓位 × 0.70
    (25.0, 0.85),   # VIX > 25：整体仓位 × 0.85
    (0.0,  1.00),   # 正常：不调节
]

# 策略名称映射
STRATEGY_NAMES = {
    "v4":             "宝典V4",
    "mean_reversion": "均值回归",
    "event_driven":   "事件驱动",
}


# ============================================================
# 核心调度接口
# ============================================================

def get_strategy_allocations(regime: str, vix: Optional[float] = None) -> dict:
    """
    根据体制和VIX计算各策略的资金分配比例。

    Args:
        regime: 市场体制 "strong_bull" | "bull" | "choppy" | "bear"
        vix: 当前VIX数值（可选，用于全局调节）

    Returns:
        {
            "v4": 0.60,
            "mean_reversion": 0.10,
            "event_driven": 0.30,
            "cash": 0.00,
            "vix_multiplier": 1.0,
            "regime": "bull",
            "note": "..."
        }
    """
    base = ALLOCATION_MATRIX.get(regime, ALLOCATION_MATRIX["bull"]).copy()

    # VIX 全局调节
    vix_mult = 1.0
    vix_note = ""
    if vix is not None:
        for threshold, mult in VIX_DELEVERAGE_LEVELS:
            if vix > threshold:
                vix_mult = mult
                vix_note = f"VIX={vix:.1f} > {threshold} → 全体仓位×{mult}"
                break

    # 应用VIX调节
    adjusted = {k: round(v * vix_mult, 4) for k, v in base.items()}
    cash = round(1.0 - sum(adjusted.values()), 4)

    result = {
        **adjusted,
        "cash": max(0.0, cash),
        "vix_multiplier": vix_mult,
        "regime": regime,
        "note": vix_note or f"体制={regime}，正常分配",
    }

    logger.info(
        f"[PM] 资金分配 | 体制={regime} VIX={vix} | "
        f"V4={result['v4']:.0%} MR={result['mean_reversion']:.0%} "
        f"ED={result['event_driven']:.0%} 现金={result['cash']:.0%}"
    )
    return result


def resolve_position_conflicts(
    v4_positions: list[str],
    mr_positions: list[str],
    ed_positions: list[str],
) -> dict:
    """
    处理策略间持仓冲突：同一只股票不重复计算。
    优先级：V4 > 事件驱动 > 均值回归（V4已持有则其他策略不重复开仓）

    Returns:
        {
            "v4": [不冲突的V4持仓],
            "mean_reversion": [不冲突的均值回归持仓],
            "event_driven": [不冲突的事件驱动持仓],
            "conflicts": [冲突的ticker列表],
        }
    """
    conflicts = []
    v4_set = set(v4_positions)
    ed_final = []
    mr_final = []

    # 事件驱动 vs V4
    for t in ed_positions:
        if t in v4_set:
            conflicts.append({"ticker": t, "kept_by": "v4", "removed_from": "event_driven"})
            logger.debug(f"[PM] 持仓冲突: {t} 已在V4，事件驱动不重复开仓")
        else:
            ed_final.append(t)

    # 均值回归 vs V4 + 事件驱动
    ed_set = set(ed_final)
    for t in mr_positions:
        if t in v4_set or t in ed_set:
            conflicts.append({"ticker": t, "kept_by": "v4_or_ed", "removed_from": "mean_reversion"})
            logger.debug(f"[PM] 持仓冲突: {t} 已在其他策略，均值回归不重复开仓")
        else:
            mr_final.append(t)

    if conflicts:
        logger.info(f"[PM] 发现 {len(conflicts)} 个持仓冲突，已自动处理")

    return {
        "v4": v4_positions,
        "mean_reversion": mr_final,
        "event_driven": ed_final,
        "conflicts": conflicts,
    }


# ============================================================
# 组合回测引擎
# ============================================================

async def run_portfolio_backtest(
    start_date: str,
    end_date: str,
    allocation_override: Optional[dict] = None,
) -> dict:
    """
    三策略组合回测：V4 + 均值回归 + 事件驱动。
    按照体制动态分配资金，计算组合整体表现。

    Args:
        start_date: 回测开始日期
        end_date: 回测结束日期
        allocation_override: 可选，手动覆盖资金分配（用于测试不同分配方案）

    Returns:
        完整的组合回测结果，包含各子策略表现和相关性分析
    """
    from app.services.rotation_service import (
        run_rotation_backtest, _slice_prefetched, _fetch_backtest_data
    )
    from app.services.mean_reversion_service import run_mean_reversion_backtest
    from app.services.event_driven_service import (
        run_event_driven_backtest, fetch_ed_fundamentals_only
    )

    logger.info(f"[PM] 开始组合回测 {start_date} → {end_date}")

    # --- 确定动态资金分配（使用平均分配作为回测基础）---
    # 完整组合回测中，我们用各体制的加权平均作为整体分配
    if allocation_override:
        alloc = allocation_override
        logger.info(f"[PM] 使用手动分配: {alloc}")
    else:
        # 默认：bull 体制下的标准分配
        alloc = ALLOCATION_MATRIX["bull"]
        logger.info(f"[PM] 使用默认bull分配: {alloc}")

    # --- 预取 OHLCV 数据（三策略共享，确保宇宙一致）---
    # 关键修复：以前 V4/MR/ED 各自独立取数，导致：
    #   1. V4 三次运行用不同 av._daily_cache 快照（MR/ED 跑完后缓存变大）→ 结果不一致
    #   2. equity_curve 长度不齐（min_len 被最短者截断）→ portfolio trading_days 异常偏短
    # 现在：统一预取一次，所有策略共享同一份 histories，保证确定性与日期对齐。
    import asyncio

    logger.info("[PM] 预取 OHLCV 历史数据（三策略共享）...")
    prefetched = _slice_prefetched(start_date, end_date)
    if prefetched is None:
        logger.info("[PM] 内存/磁盘缓存未命中，从 AV 实时拉取数据...")
        prefetched = await _fetch_backtest_data(start_date, end_date)
        if "error" in prefetched:
            return {"error": f"数据获取失败: {prefetched['error']}"}
    shared_histories = prefetched["histories"]
    logger.info(f"[PM] OHLCV 预取完成：{len(shared_histories)} 只股票，"
                f"period={start_date}→{end_date}")

    # ED 需要财报数据（独立于 OHLCV），单独预取一次
    logger.info("[PM] 预取 ED 财报数据（FMP/AV）...")
    ed_fundamentals = await fetch_ed_fundamentals_only()
    logger.info(f"[PM] 财报预取完成：{len(ed_fundamentals)} 只")

    # --- 策略回测：V4 / MR / ED 均使用同一份 shared_histories ---
    logger.info("[PM] 第1步：运行V4回测（使用共享数据）...")
    v4_result = await run_rotation_backtest(
        start_date=start_date, end_date=end_date,
        _prefetched=prefetched,
    )

    logger.info("[PM] 第2步：并行运行均值回归+事件驱动回测（共享数据）...")
    mr_task = run_mean_reversion_backtest(
        start_date=start_date, end_date=end_date,
        capital_ratio=alloc.get("mean_reversion", 0.1),
        _prefetched=shared_histories,
    )
    # NOTE: regime_series 未传入（event_driven_service 有该参数但此处不使用）
    # ED 的 regime 控制通过 ALLOCATION_MATRIX 在组合层面实现，无需策略层再做调整
    ed_task = run_event_driven_backtest(
        start_date=start_date, end_date=end_date,
        capital_ratio=alloc.get("event_driven", 0.3),
        _prefetched=shared_histories,
        _prefetched_fundamentals=ed_fundamentals,
    )
    mr_result, ed_result = await asyncio.gather(mr_task, ed_task)

    # --- 合并权益曲线 ---
    combined = _combine_equity_curves(
        v4_result,  alloc.get("v4", 0.60),
        mr_result,  alloc.get("mean_reversion", 0.10),
        ed_result,  alloc.get("event_driven", 0.30),
    )

    # --- 计算相关性矩阵 ---
    correlations = _compute_strategy_correlations(v4_result, mr_result, ed_result)

    # --- 组合统计 ---
    portfolio_stats = _compute_portfolio_stats(combined["equity_curve"], start_date, end_date)

    result = {
        "strategy": "portfolio_matrix",
        "period": f"{start_date} → {end_date}",
        "allocation": alloc,

        # 组合整体
        "portfolio": {
            **portfolio_stats,
            "equity_curve": combined["equity_curve"],
        },

        # 各子策略独立结果
        "sub_strategies": {
            "v4": {
                "cumulative_return": v4_result.get("cumulative_return"),
                "annualized_return": v4_result.get("annualized_return"),
                "sharpe_ratio": v4_result.get("sharpe_ratio"),
                "max_drawdown": v4_result.get("max_drawdown"),
                "win_rate": v4_result.get("win_rate"),
            },
            "mean_reversion": {
                "cumulative_return": mr_result.get("cumulative_return"),
                "annualized_return": mr_result.get("annualized_return"),
                "sharpe_ratio": mr_result.get("sharpe_ratio"),
                "max_drawdown": mr_result.get("max_drawdown"),
                "win_rate": mr_result.get("win_rate"),
            },
            "event_driven": {
                "cumulative_return": ed_result.get("cumulative_return"),
                "annualized_return": ed_result.get("annualized_return"),
                "sharpe_ratio": ed_result.get("sharpe_ratio"),
                "max_drawdown": ed_result.get("max_drawdown"),
                "win_rate": ed_result.get("win_rate"),
            },
        },

        # 相关性分析
        "correlations": correlations,
    }

    logger.info(
        f"[PM] 组合回测完成 | "
        f"累计={portfolio_stats['cumulative_return']:+.2%} "
        f"夏普={portfolio_stats['sharpe_ratio']:.2f} "
        f"回撤={portfolio_stats['max_drawdown']:.2%}"
    )
    return result


# ============================================================
# 实时信号汇总（每日盘后调用）
# ============================================================

async def get_daily_signals(vix: Optional[float] = None) -> dict:
    """
    每日盘后汇总所有策略信号。
    供通知系统/前端调用。

    Returns:
        {
            "regime": str,
            "allocation": dict,
            "v4_holdings": [...],
            "mr_candidates": [...],
            "ed_candidates": [...],
            "summary": str,
        }
    """
    from app.services.rotation_service import _detect_regime
    from app.services.mean_reversion_service import scan_live_signals
    from app.services.event_driven_service import scan_live_events

    import asyncio

    logger.info("[PM] 开始汇总每日信号...")

    # 获取当前体制
    regime = await _detect_regime()
    alloc = get_strategy_allocations(regime, vix=vix)

    current_date = datetime.now().strftime("%Y-%m-%d")

    # 并行扫描各策略信号
    mr_task = scan_live_signals(regime)
    ed_task = scan_live_events(current_date)

    mr_candidates, ed_candidates = await asyncio.gather(mr_task, ed_task)

    # 生成摘要
    summary_parts = [
        f"体制={regime}",
        f"V4={alloc['v4']:.0%} MR={alloc['mean_reversion']:.0%} ED={alloc['event_driven']:.0%}",
        f"均值回归候选: {len(mr_candidates)}个",
        f"事件驱动候选: {len(ed_candidates)}个",
    ]
    if alloc.get("note"):
        summary_parts.append(alloc["note"])

    logger.info(f"[PM] 每日信号汇总完成: {' | '.join(summary_parts)}")

    return {
        "date": current_date,
        "regime": regime,
        "allocation": alloc,
        "mr_candidates": mr_candidates[:5],    # 只返回前5个
        "ed_candidates": ed_candidates[:5],
        "vix": vix,
        "summary": " | ".join(summary_parts),
    }


# ============================================================
# 内部工具函数
# ============================================================

def _upsample_weekly_to_daily(weekly_rets: list) -> list:
    """
    将周级别收益序列上采样为日级别。
    V4是周轮动策略，权益曲线每条代表一周；MR/ED是日级别。
    对齐前须先把V4周收益均匀分配到5个交易日：
      每日等效收益 = (1 + weekly_ret)^(1/5) - 1
    """
    daily = []
    for wr in weekly_rets:
        daily_r = (1.0 + wr) ** (1.0 / 5.0) - 1.0
        daily.extend([daily_r] * 5)
    return daily


def _combine_equity_curves(
    v4_result: dict,  v4_weight: float,
    mr_result: dict,  mr_weight: float,
    ed_result: dict,  ed_weight: float,
) -> dict:
    """
    按权重合并三个策略的权益曲线。
    V4是周级别权益曲线，MR/ED是日级别；先把V4上采样为日级别再合并。
    """
    def get_rets(result: dict) -> list:
        ec = result.get("equity_curve", [1.0])
        if len(ec) < 2:
            return []
        return [(_ec_val(ec[i]) / _ec_val(ec[i-1])) - 1 for i in range(1, len(ec))]

    v4_rets_raw = get_rets(v4_result)
    mr_rets = get_rets(mr_result)
    ed_rets = get_rets(ed_result)

    # V4 是周级别，判断标准：条目数 < 日级别的一半则认为是周频
    # 正常回测：日级别 ≈ trading_days，周级别 ≈ trading_days/5
    mr_days = mr_result.get("trading_days", len(mr_rets))
    v4_is_weekly = len(v4_rets_raw) > 0 and len(v4_rets_raw) < mr_days * 0.4

    if v4_is_weekly:
        v4_rets = _upsample_weekly_to_daily(v4_rets_raw)
        logger.debug(f"[PM] V4 周→日上采样: {len(v4_rets_raw)}周 → {len(v4_rets)}日")
    else:
        v4_rets = v4_rets_raw

    # 对齐长度（取最短），允许2%误差容忍（约5天）
    min_len = min(len(v4_rets), len(mr_rets), len(ed_rets))
    if min_len == 0:
        logger.warning("[PM] 权益曲线合并失败：某策略返回空数据")
        return {"equity_curve": [1.0]}

    # 加权合并
    cash_weight = max(0.0, 1.0 - v4_weight - mr_weight - ed_weight)
    combined_rets = []
    for i in range(min_len):
        daily_ret = (
            v4_rets[i]  * v4_weight +
            mr_rets[i]  * mr_weight +
            ed_rets[i]  * ed_weight +
            0.0         * cash_weight   # 现金收益率为0
        )
        combined_rets.append(daily_ret)

    # 重建权益曲线
    equity_curve = [1.0]
    for r in combined_rets:
        equity_curve.append(equity_curve[-1] * (1 + r))

    logger.debug(f"[PM] 权益曲线合并完成: {len(equity_curve)}日, "
                 f"V4({len(v4_rets)}) MR({len(mr_rets)}) ED({len(ed_rets)})")

    return {
        "equity_curve": equity_curve,
        "daily_returns": combined_rets,
    }


def _compute_strategy_correlations(
    v4_result: dict,
    mr_result: dict,
    ed_result: dict,
) -> dict:
    """
    计算三个策略之间的收益相关性。
    相关性越低，组合效果越好。
    """
    def get_vals(result: dict) -> list:
        """提取权益曲线数值列表"""
        ec = result.get("equity_curve", [1.0])
        return [_ec_val(x) for x in ec] if ec else [1.0]

    def to_weekly_rets(vals: list) -> np.ndarray:
        """
        将任意频率的权益曲线转为周收益序列。
        V4已是周级别（直接计算相邻收益）；
        MR/ED是日级别（每5个交易日取一个采样点）。
        """
        if len(vals) < 2:
            return np.array([])
        # 判断是否为日级别（通常 >200 个点代表多于一年日数据）
        step = 5 if len(vals) > 200 else 1
        sampled = [vals[i] for i in range(0, len(vals), step)]
        if len(sampled) < 2:
            return np.array([])
        rets = np.array([(sampled[i] / sampled[i-1]) - 1 for i in range(1, len(sampled))])
        return rets

    v4_rets = to_weekly_rets(get_vals(v4_result))
    mr_rets = to_weekly_rets(get_vals(mr_result))
    ed_rets = to_weekly_rets(get_vals(ed_result))

    min_len = min(len(v4_rets), len(mr_rets), len(ed_rets))
    if min_len < 10:
        return {"error": "数据不足，无法计算相关性"}

    v4_rets = v4_rets[:min_len]
    mr_rets = mr_rets[:min_len]
    ed_rets = ed_rets[:min_len]

    # 如果任一序列方差为零（全无交易），跳过该对的相关性
    def safe_corr(a: np.ndarray, b: np.ndarray) -> float:
        if np.std(a) < 1e-10 or np.std(b) < 1e-10:
            return float("nan")
        return float(np.corrcoef(a, b)[0, 1])

    corr_v4_mr = safe_corr(v4_rets, mr_rets)
    corr_v4_ed = safe_corr(v4_rets, ed_rets)
    corr_mr_ed = safe_corr(mr_rets, ed_rets)

    # 评估相关性水平
    def _assess(corr: float) -> str:
        if abs(corr) < 0.2:
            return "极低 ✅"
        elif abs(corr) < 0.4:
            return "低 ✅"
        elif abs(corr) < 0.6:
            return "中 ⚠️"
        else:
            return "高 ❌"

    result = {
        "v4_vs_mean_reversion": round(corr_v4_mr, 3),
        "v4_vs_event_driven":   round(corr_v4_ed, 3),
        "mean_reversion_vs_event_driven": round(corr_mr_ed, 3),
        "assessment": {
            "v4_vs_mean_reversion": _assess(corr_v4_mr),
            "v4_vs_event_driven":   _assess(corr_v4_ed),
            "mean_reversion_vs_event_driven": _assess(corr_mr_ed),
        },
        "diversification_verdict": (
            "组合多元化效果良好 ✅"
            if max(abs(corr_v4_mr), abs(corr_v4_ed), abs(corr_mr_ed)) < 0.5
            else "⚠️ 某些策略相关性偏高，建议检查参数"
        ),
    }

    logger.info(
        f"[PM] 相关性分析 | "
        f"V4↔MR={corr_v4_mr:.2f} "
        f"V4↔ED={corr_v4_ed:.2f} "
        f"MR↔ED={corr_mr_ed:.2f}"
    )
    return result


def _compute_portfolio_stats(
    equity_curve: list,
    start_date: str = None,
    end_date: str = None,
    frequency: str = "daily",
) -> dict:
    """
    计算组合整体统计指标。
    年化收益率优先用实际日历年数（最准确），避免周/日频率混淆导致虚高。

    Args:
        frequency: "daily"（默认）或 "weekly"。
                   组合权益曲线由 _combine_equity_curves 合并而来，V4 已上采样到日频，
                   故始终应传入 "daily"（252 periods/year）。
    """
    if len(equity_curve) < 2:
        return {}

    periods = len(equity_curve) - 1          # 数据点间隔数
    period_rets = [(equity_curve[i] / equity_curve[i-1]) - 1
                   for i in range(1, len(equity_curve))]

    # 明确使用调用方指定的频率（不再用 <500 阈值猜测，避免短周期误判）
    periods_per_year = 52 if frequency == "weekly" else 252

    cumulative_return = equity_curve[-1] - 1.0

    # 年化收益：优先用日历年数（start/end date），避免频率假设错误
    if start_date and end_date:
        try:
            from datetime import date as _date
            d0 = _date.fromisoformat(start_date[:10])
            d1 = _date.fromisoformat(end_date[:10])
            years = max((d1 - d0).days / 365.25, 0.1)
        except Exception:
            years = periods / max(periods_per_year, 1)
    else:
        years = periods / max(periods_per_year, 1)

    annualized_return = (equity_curve[-1] ** (1.0 / years)) - 1
    vol = float(np.std(period_rets) * np.sqrt(periods_per_year))
    sharpe = annualized_return / vol if vol > 0 else 0.0

    # 最大回撤
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # 胜率（以每期收益计，无论周/日均适用）
    win_rate = sum(1 for r in period_rets if r > 0) / len(period_rets) if period_rets else 0.0

    return {
        "cumulative_return": round(cumulative_return, 4),
        "annualized_return": round(annualized_return, 4),
        "annualized_vol": round(vol, 4),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
        "trading_days": periods,
        "years": round(years, 2),
    }
