"""
scripts/backtest_precompute.py
==============================
回测预计算独立脚本 —— 在 GitHub Actions / 本地运行，不依赖 Render Web 服务器。

功能：
  - 从 AV 拉取 2017-01-01 至今的 OHLCV 数据（或从磁盘缓存加载）
  - 计算 50 种参数组合（5 top_n × 5 holding_bonus × 2 regime_version）
  - 结果直接写入 Supabase cache_store 表
  - 写入后 Render 服务器重启时直接命中缓存，回测页秒加载

用法：
  python scripts/backtest_precompute.py
  python scripts/backtest_precompute.py --dry-run        # 只跑第一个 combo 验证
  python scripts/backtest_precompute.py --regime v1      # 只跑 v1（25 combos）
  python scripts/backtest_precompute.py --regime v2      # 只跑 v2（25 combos）

环境变量（必须）：
  SUPABASE_URL / SUPABASE_SERVICE_KEY
  ALPHA_VANTAGE_KEY（Premium，75 req/min）

可选：
  APP_ENV=production  （默认 development，不影响脚本运行）
"""

import asyncio
import os
import sys
import json
import time
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path

# 把项目根目录加入 Python 路径
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("precompute")


START_DATE    = "2018-01-01"
PREFETCH_START = "2017-01-01"   # 6 个月 lookback

def _last_friday() -> str:
    """最近一个周五，与服务器和前端的默认 end_date 保持一致"""
    from datetime import timedelta
    today = datetime.now(timezone.utc).date()
    day_of_week = today.weekday()  # 0=Mon, 4=Fri
    days_since_friday = (day_of_week - 4) % 7
    return (today - timedelta(days=days_since_friday)).strftime("%Y-%m-%d")

END_DATE = _last_friday()
TOP_N_VALUES  = [2, 3, 4, 5, 6]
BONUS_VALUES  = [0, 0.25, 0.5, 0.75, 1.0]
REGIME_VERS   = ["v1", "v2"]
BACKTEST_TTL  = 86400 * 8       # 8 天（与 web.py 保持一致）


def _make_json_safe(obj):
    """递归转换 numpy / pandas 类型为 JSON 可序列化类型"""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def _cache_set_supabase(key: str, value, ttl: int, db):
    """直接写 Supabase cache_store（同步）"""
    try:
        safe_value = _make_json_safe(value)
        db.table("cache_store").upsert({
            "key": key,
            "value": safe_value,
        }).execute()
        logger.info(f"  ✓ Supabase 写入: {key}")
    except Exception as e:
        logger.warning(f"  ✗ Supabase 写入失败 {key}: {e}")


async def run_precompute(dry_run: bool = False, regime: str = "all"):
    t_total = time.time()

    # ── 初始化 Supabase ──
    from supabase import create_client
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not supabase_url or not supabase_key:
        logger.error("❌ 缺少环境变量！请在 GitHub Secrets 中配置：")
        logger.error("   SUPABASE_URL        = https://xxx.supabase.co")
        logger.error("   SUPABASE_SERVICE_KEY = eyJ... (service_role key)")
        sys.exit(1)
    db = create_client(supabase_url, supabase_key)
    logger.info(f"Supabase 已连接: {supabase_url[:40]}...")

    # ── 拉取 OHLCV + 基本面数据 ──
    logger.info(f"开始拉取数据: {PREFETCH_START} → {END_DATE}")
    from app.services.rotation_service import _fetch_backtest_data, set_prefetched_full
    prefetched = await _fetch_backtest_data(PREFETCH_START, END_DATE)
    if "error" in prefetched:
        logger.error(f"数据拉取失败: {prefetched['error']}")
        sys.exit(1)

    logger.info(f"数据拉取完成（原始）: {len(prefetched['histories'])} 支票")

    # ── 过滤至 watchlist tickers，剔除历史缓存多余的股票 ──
    # 磁盘缓存可能包含非 watchlist 的历史 ticker，会大幅拖慢计算
    from app.config.rotation_watchlist import (
        OFFENSIVE_ETFS, DEFENSIVE_ETFS, INVERSE_ETFS, LARGECAP_STOCKS, MIDCAP_STOCKS,
    )
    watchlist_tickers = (
        {e["ticker"] for e in OFFENSIVE_ETFS}
        | {e["ticker"] for e in DEFENSIVE_ETFS}
        | {e["ticker"] for e in INVERSE_ETFS}
        | {e["ticker"] for e in LARGECAP_STOCKS}
        | {e["ticker"] for e in MIDCAP_STOCKS}
        | {"SPY", "QQQ"}
    )
    original_count = len(prefetched["histories"])
    prefetched["histories"] = {
        t: h for t, h in prefetched["histories"].items()
        if t in watchlist_tickers
    }
    logger.info(f"Ticker 过滤: {original_count} → {len(prefetched['histories'])} 支（watchlist only）")

    set_prefetched_full(prefetched, PREFETCH_START, END_DATE)

    # 持久化 bt_fundamentals
    if prefetched.get("bt_fundamentals"):
        _cache_set_supabase(
            "bt_fund:latest",
            _make_json_safe(prefetched["bt_fundamentals"]),
            86400 * 30,
            db,
        )
        logger.info(f"bt_fundamentals 已写入 ({len(prefetched['bt_fundamentals'])} 支)")

    # ── 计算 50 个 combo ──
    from app.services.rotation_service import run_rotation_backtest

    regime_list = [regime] if regime in ("v1", "v2") else REGIME_VERS
    combos = [
        (rv, tn, hb)
        for rv in regime_list
        for tn in TOP_N_VALUES
        for hb in BONUS_VALUES
    ]
    if dry_run:
        combos = combos[:1]
        logger.info("dry-run 模式：只跑第 1 个 combo")
    logger.info(f"计划运行 {len(combos)} 个 combo（regime={regime}）")

    total = len(combos)
    ok = 0
    for idx, (rv, tn, hb) in enumerate(combos, 1):
        t0 = time.time()
        try:
            result = await run_rotation_backtest(
                start_date=START_DATE,
                end_date=END_DATE,
                top_n=tn,
                holding_bonus=hb,
                _prefetched=prefetched,
                regime_version=rv,
            )
            elapsed = time.time() - t0
            if "error" in result:
                logger.warning(f"[{idx}/{total}] {rv}/Top{tn}/HB{hb} → 计算错误: {result['error']}")
                continue

            sharpe = result.get("sharpe_ratio", 0)
            cache_key = (
                f"bt_v2:{START_DATE}:{END_DATE}:{tn}:{hb}"
                if rv == "v1"
                else f"bt_v2:{START_DATE}:{END_DATE}:{tn}:{hb}:{rv}"
            )
            _cache_set_supabase(cache_key, _make_json_safe(result), BACKTEST_TTL, db)
            logger.info(
                f"[{idx}/{total}] {rv}/Top{tn}/HB{hb} → Sharpe={sharpe:.2f} ({elapsed:.1f}s)"
            )
            ok += 1
        except Exception as e:
            logger.warning(f"[{idx}/{total}] {rv}/Top{tn}/HB{hb} → 异常: {e}")

    total_time = time.time() - t_total
    logger.info("=" * 60)
    logger.info(f"预计算完成：{ok}/{total} 个 combo 成功，共耗时 {total_time/60:.1f} 分钟")
    logger.info(f"END_DATE 使用：{END_DATE}")
    logger.info("=" * 60)

    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回测预计算脚本")
    parser.add_argument("--dry-run", action="store_true", help="只跑第1个combo（验证用）")
    parser.add_argument("--regime", default="all", choices=["all", "v1", "v2"],
                        help="只跑指定 regime version（all/v1/v2），用于并行化")
    args = parser.parse_args()
    asyncio.run(run_precompute(dry_run=args.dry_run, regime=args.regime))
