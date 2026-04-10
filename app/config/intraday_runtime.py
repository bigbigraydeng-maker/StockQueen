"""
铃铛策略运行时阀门（与代码常量分离，便于后台/Lab 调整）

- 默认与上限见 intraday_runtime.json
- 执行层请使用 get_max_total_exposure()，勿直接读 IntradayConfig.MAX_TOTAL_EXPOSURE 做硬上限
- 方案 B 动态杠杆：adjust_leverage_by_daily_pnl(current_equity) 每轮评分自动调用
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz

logger = logging.getLogger(__name__)

_RUNTIME_PATH = Path(__file__).resolve().parent / "intraday_runtime.json"

# 产品硬边界：名义敞口相对权益的倍数（与 Tiger 账户杠杆能力无关，是策略层阀门）
_MIN_EXPOSURE = 1.0
_MAX_EXPOSURE = 4.0  # 上调至 4x，允许运行时配置到 3x

# 方案 B 阈值（日内已实现 P&L 相对开盘权益）
_PLAN_B_TIERS = [
    (-0.010, 1.0),   # 亏损 ≥ 1.0% → 1x，停止新建仓
    (-0.005, 1.5),   # 亏损 ≥ 0.5% → 1.5x
    ( 0.000, 3.0),   # 正常 / 盈利  → 3x（默认上限）
]


def _defaults() -> Dict[str, Any]:
    return {"max_total_exposure": 3.0}


def load_intraday_runtime() -> Dict[str, Any]:
    """读取 JSON；缺失或损坏时返回默认值（不写盘）。保留以下划线开头的元数据键。"""
    if not _RUNTIME_PATH.exists():
        return _defaults()
    try:
        with open(_RUNTIME_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _defaults()
        out = _defaults()
        out.update({k: v for k, v in data.items() if not str(k).startswith("_")})
        meta = {k: v for k, v in data.items() if str(k).startswith("_")}
        out.update(meta)
        return out
    except Exception as e:
        logger.warning(f"[intraday_runtime] load failed: {e}")
        return _defaults()


def get_max_total_exposure() -> float:
    """
    策略层允许的最大总敞口：sum(持仓市值)/权益 的上限（倍）。
    例如 2.0 表示合计名义敞口不超过权益的 200%。
    """
    raw = load_intraday_runtime().get("max_total_exposure", _defaults()["max_total_exposure"])
    try:
        v = float(raw)
    except (TypeError, ValueError):
        v = float(_defaults()["max_total_exposure"])
    return max(_MIN_EXPOSURE, min(_MAX_EXPOSURE, v))


def save_intraday_runtime(updates: Dict[str, Any]) -> Dict[str, Any]:
    """合并写入 JSON；max_total_exposure 会钳制在 [MIN, MAX]。保留原有 _ 前缀注释键。"""
    cur = load_intraday_runtime()
    for k, v in updates.items():
        if str(k).startswith("_"):
            continue
        cur[k] = v
    if "max_total_exposure" in cur:
        try:
            cur["max_total_exposure"] = max(
                _MIN_EXPOSURE, min(_MAX_EXPOSURE, float(cur["max_total_exposure"]))
            )
        except (TypeError, ValueError):
            cur["max_total_exposure"] = _defaults()["max_total_exposure"]
    write_out: Dict[str, Any] = {
        "max_total_exposure": cur.get("max_total_exposure", _defaults()["max_total_exposure"]),
    }
    # 持久化日内基准权益和日期
    for key in ("day_start_equity", "day_start_date"):
        if key in cur:
            write_out[key] = cur[key]
    for k, v in cur.items():
        if str(k).startswith("_"):
            write_out[k] = v
    _RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_RUNTIME_PATH, "w", encoding="utf-8") as f:
        json.dump(write_out, f, indent=2, ensure_ascii=False)
    logger.info(f"[intraday_runtime] saved max_total_exposure={write_out.get('max_total_exposure')}")
    return write_out


def adjust_leverage_by_daily_pnl(current_equity: float) -> Optional[float]:
    """
    方案 B：根据当日已实现盈亏率自动调节杠杆上限。

    逻辑：
        日盈亏率 = (current_equity - day_start_equity) / day_start_equity
        ≥  0.0%  → 3x（正常 / 盈利）
        < -0.5%  → 1.5x（开始亏损，降档）
        < -1.0%  → 1.0x（深度亏损，停止新建仓）

    每个交易日首次调用时，将 current_equity 记录为 day_start_equity。

    Returns:
        新的 max_total_exposure（已写入 runtime），或 None（权益数据无效时跳过）
    """
    if not current_equity or current_equity <= 0:
        return None

    et = pytz.timezone("US/Eastern")
    today_str = datetime.now(et).strftime("%Y-%m-%d")

    state = load_intraday_runtime()
    stored_date = state.get("day_start_date", "")
    stored_equity = float(state.get("day_start_equity", 0) or 0)

    # 新的交易日：重置基准权益
    if stored_date != today_str or stored_equity <= 0:
        save_intraday_runtime({
            "day_start_equity": current_equity,
            "day_start_date": today_str,
        })
        logger.info(
            f"[LEVERAGE-AUTO] New trading day {today_str}, "
            f"day_start_equity=${current_equity:,.2f}, leverage stays at "
            f"{get_max_total_exposure()}x"
        )
        return get_max_total_exposure()

    # 计算日内盈亏率
    daily_pnl_pct = (current_equity - stored_equity) / stored_equity

    # 按阈值确定目标杠杆（从低到高遍历，取第一个满足条件的）
    target_leverage = _PLAN_B_TIERS[-1][1]  # 默认最高档
    for threshold, lev in _PLAN_B_TIERS:
        if daily_pnl_pct < threshold:
            target_leverage = lev
            break

    current_leverage = get_max_total_exposure()
    if abs(target_leverage - current_leverage) >= 0.01:
        save_intraday_runtime({"max_total_exposure": target_leverage})
        logger.warning(
            f"[LEVERAGE-AUTO] Adjust {current_leverage}x -> {target_leverage}x | "
            f"daily_pnl={daily_pnl_pct*100:+.3f}% "
            f"(equity ${current_equity:,.0f} vs start ${stored_equity:,.0f})"
        )
    else:
        logger.debug(
            f"[LEVERAGE-AUTO] No change {current_leverage}x | "
            f"daily_pnl={daily_pnl_pct*100:+.3f}%"
        )

    return target_leverage
