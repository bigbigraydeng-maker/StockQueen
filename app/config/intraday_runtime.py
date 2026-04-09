"""
铃铛策略运行时阀门（与代码常量分离，便于后台/Lab 调整）

- 默认与上限见 intraday_runtime.json
- 执行层请使用 get_max_total_exposure()，勿直接读 IntradayConfig.MAX_TOTAL_EXPOSURE 做硬上限
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

_RUNTIME_PATH = Path(__file__).resolve().parent / "intraday_runtime.json"

# 产品硬边界：名义敞口相对权益的倍数（与 Tiger 账户杠杆能力无关，是策略层阀门）
_MIN_EXPOSURE = 1.0
_MAX_EXPOSURE = 2.0


def _defaults() -> Dict[str, Any]:
    return {"max_total_exposure": 2.0}


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
    for k, v in cur.items():
        if str(k).startswith("_"):
            write_out[k] = v
    _RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_RUNTIME_PATH, "w", encoding="utf-8") as f:
        json.dump(write_out, f, indent=2, ensure_ascii=False)
    logger.info(f"[intraday_runtime] saved max_total_exposure={write_out.get('max_total_exposure')}")
    return write_out
