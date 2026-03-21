"""
全量数据预拉取脚本（Massive 数据源 - Stocks Developer 套餐）
======================================
把动态股票池所有 ticker 的历史数据全部缓存到本地磁盘，
后续 Walk-Forward / IC 分析 / 回测全部读本地，不再打 API。

套餐限制: 10年历史数据 / 15分钟延迟 / Unlimited API Calls

缓存路径：
  OHLCV    → .cache/av/daily_TICKER_full.json        (180天有效期)
  基本面   → .cache/av/overview_TICKER.json           (3天有效期)
            .cache/av/earnings_TICKER.json
            .cache/av/income_TICKER.json
            .cache/av/cashflow_TICKER.json

用法：
  python scripts/prefetch_all_data.py              # 全部 (OHLCV + 基本面)
  python scripts/prefetch_all_data.py --mode ohlcv       # 只拉行情
  python scripts/prefetch_all_data.py --mode fundamentals # 只拉基本面
  python scripts/prefetch_all_data.py --universe watchlist # 只拉 watchlist (快速)
  python scripts/prefetch_all_data.py --concurrency 50    # 自定义并发数
"""

import asyncio
import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("prefetch")

CACHE_DIR = PROJECT_ROOT / ".cache" / "av"
RESULTS_DIR = PROJECT_ROOT / "scripts" / "stress_test_results"


def parse_args():
    p = argparse.ArgumentParser(description="全量数据预拉取")
    p.add_argument("--mode", default="all",
                   choices=["all", "ohlcv", "fundamentals"],
                   help="拉取模式")
    p.add_argument("--universe", default="all",
                   choices=["all", "watchlist", "supabase"],
                   help="股票池来源")
    p.add_argument("--concurrency", type=int, default=30,
                   help="并发请求数 (默认30，Massive 无严格限速)")
    p.add_argument("--skip-existing", action="store_true", default=True,
                   help="跳过已有磁盘缓存的 ticker (默认 True)")
    return p.parse_args()


def load_watchlist_tickers() -> list:
    """从 rotation_watchlist.py 加载硬编码 watchlist。"""
    from app.config.rotation_watchlist import MIDCAP_STOCKS, LARGECAP_STOCKS
    tickers = list({s["ticker"] for s in (MIDCAP_STOCKS + LARGECAP_STOCKS)})
    print(f"Watchlist: {len(tickers)} tickers")
    return sorted(tickers)


async def load_supabase_tickers() -> list:
    """从 Supabase universe_snapshots 加载动态选股池。"""
    try:
        from app.config import settings
        from supabase import create_client
        sb = create_client(settings.supabase_url, settings.supabase_service_key)
        result = sb.table("universe_snapshots") \
            .select("tickers") \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        if result.data:
            raw = result.data[0].get("tickers", [])
            # 兼容 list[str] 和 list[dict]
            if raw and isinstance(raw[0], dict):
                tickers = [t["ticker"] for t in raw if t.get("ticker")]
            else:
                tickers = [str(t) for t in raw if t]
            print(f"Supabase universe: {len(tickers)} tickers")
            return sorted(tickers)
    except Exception as e:
        print(f"Supabase 加载失败: {e}")
    return []


def ohlcv_cache_exists(ticker: str) -> bool:
    """检查 OHLCV 磁盘缓存是否存在且未过期。"""
    fpath = CACHE_DIR / f"daily_{ticker}_full.json"
    if not fpath.exists():
        return False
    try:
        with open(fpath) as f:
            data = json.load(f)
        ts = data.get("ts", 0)
        # 180天有效期
        return (time.time() - ts) < 86400 * 180
    except Exception:
        return False


def fundamentals_cache_exists(ticker: str) -> bool:
    """检查基本面缓存是否存在（earnings + cashflow）。"""
    e = CACHE_DIR / f"earnings_{ticker}.json"
    c = CACHE_DIR / f"cashflow_{ticker}.json"
    return e.exists() and c.exists()


# ──────────────────────────────────────────────
# OHLCV 预拉取
# ──────────────────────────────────────────────

async def prefetch_ohlcv(tickers: list, concurrency: int, skip_existing: bool):
    """并发拉取所有 ticker 的 10 年日线数据并写入磁盘缓存。"""
    from app.services.massive_client import get_massive_client
    client = get_massive_client()

    if skip_existing:
        pending = [t for t in tickers if not ohlcv_cache_exists(t)]
        skipped = len(tickers) - len(pending)
        print(f"\n[OHLCV] {len(tickers)} tickers → 跳过已缓存 {skipped} → 待拉取 {len(pending)}")
    else:
        pending = tickers
        print(f"\n[OHLCV] 待拉取 {len(pending)} tickers (concurrency={concurrency})")

    if not pending:
        print("[OHLCV] 全部已缓存，跳过")
        return

    sem = asyncio.Semaphore(concurrency)
    counter = {"ok": 0, "fail": 0, "done": 0}
    total = len(pending)
    t0 = time.time()

    async def fetch_one(ticker: str):
        async with sem:
            try:
                # Developer套餐: 10年历史 = 3650天
                df = await client.get_daily_history(ticker, days=3650, outputsize="full")
                if df is not None and not df.empty:
                    counter["ok"] += 1
                else:
                    counter["fail"] += 1
            except Exception:
                counter["fail"] += 1
            finally:
                counter["done"] += 1
                done = counter["done"]
                if done % 50 == 0 or done == total:
                    elapsed = time.time() - t0
                    rate = done / elapsed if elapsed > 0 else 0
                    eta = (total - done) / rate if rate > 0 else 0
                    print(f"  [OHLCV] {done:4d}/{total}  ok={counter['ok']}  "
                          f"fail={counter['fail']}  "
                          f"{rate:.1f}/s  ETA={eta/60:.1f}min")

    await asyncio.gather(*[fetch_one(t) for t in pending])
    print(f"\n[OHLCV] 完成: ok={counter['ok']}  fail={counter['fail']}  "
          f"耗时={((time.time()-t0)/60):.1f}min")


# ──────────────────────────────────────────────
# 基本面预拉取
# ──────────────────────────────────────────────

async def prefetch_fundamentals(tickers: list, concurrency: int, skip_existing: bool):
    """并发拉取所有 ticker 的基本面数据并写入磁盘缓存。"""
    from app.services.massive_client import get_massive_client
    client = get_massive_client()

    if skip_existing:
        pending = [t for t in tickers if not fundamentals_cache_exists(t)]
        skipped = len(tickers) - len(pending)
        print(f"\n[Fundamentals] {len(tickers)} tickers → 跳过已缓存 {skipped} → 待拉取 {len(pending)}")
    else:
        pending = tickers
        print(f"\n[Fundamentals] 待拉取 {len(pending)} tickers (concurrency={concurrency})")

    if not pending:
        print("[Fundamentals] 全部已缓存，跳过")
        return

    sem = asyncio.Semaphore(concurrency)
    counter = {"ok": 0, "fail": 0, "done": 0}
    total = len(pending)
    t0 = time.time()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def fetch_one(ticker: str):
        async with sem:
            try:
                earnings  = await client.get_earnings(ticker)
                cashflow  = await client.get_cash_flow(ticker)
                income    = await client.get_income_statement(ticker)
                overview  = await client.get_company_overview(ticker)

                has_data = any([
                    earnings and earnings.get("quarterly"),
                    cashflow and cashflow.get("quarterly"),
                ])
                if has_data:
                    counter["ok"] += 1
                else:
                    counter["fail"] += 1
            except Exception:
                counter["fail"] += 1
            finally:
                counter["done"] += 1
                done = counter["done"]
                if done % 50 == 0 or done == total:
                    elapsed = time.time() - t0
                    rate = done / elapsed if elapsed > 0 else 0
                    eta = (total - done) / rate if rate > 0 else 0
                    print(f"  [Fund] {done:4d}/{total}  ok={counter['ok']}  "
                          f"fail={counter['fail']}  "
                          f"{rate:.1f}/s  ETA={eta/60:.1f}min")

    await asyncio.gather(*[fetch_one(t) for t in pending])
    print(f"\n[Fundamentals] 完成: ok={counter['ok']}  fail={counter['fail']}  "
          f"耗时={((time.time()-t0)/60):.1f}min")


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

async def main():
    args = parse_args()

    print("=" * 60)
    print("StockQueen 全量数据预拉取（Massive Stocks Developer）")
    print(f"模式: {args.mode}  股票池: {args.universe}  并发: {args.concurrency}")
    print(f"历史深度: 10年 (Developer套餐限制)")
    print(f"缓存目录: {CACHE_DIR}")
    print("=" * 60)

    # 加载 ticker 列表
    tickers = []
    if args.universe in ("all", "watchlist"):
        tickers.extend(load_watchlist_tickers())
    if args.universe in ("all", "supabase"):
        sb_tickers = await load_supabase_tickers()
        if sb_tickers:
            tickers = list(set(tickers) | set(sb_tickers))
        elif args.universe == "supabase":
            print("Supabase 无数据，回退到 watchlist")
            tickers.extend(load_watchlist_tickers())

    tickers = sorted(set(tickers))
    print(f"\n合计待处理: {len(tickers)} tickers")

    t_total = time.time()

    if args.mode in ("all", "ohlcv"):
        await prefetch_ohlcv(tickers, args.concurrency, args.skip_existing)

    if args.mode in ("all", "fundamentals"):
        await prefetch_fundamentals(tickers, args.concurrency, args.skip_existing)

    elapsed = time.time() - t_total
    print(f"\n{'='*60}")
    print(f"全部完成！总耗时 {elapsed/60:.1f} 分钟")
    print(f"缓存目录: {CACHE_DIR}")

    # 统计缓存文件数
    ohlcv_count = len(list(CACHE_DIR.glob("daily_*_full.json")))
    fund_count  = len(list(CACHE_DIR.glob("earnings_*.json")))
    print(f"  OHLCV 缓存文件: {ohlcv_count}")
    print(f"  Earnings 缓存:  {fund_count}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
