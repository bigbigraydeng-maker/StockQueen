"""
scripts/populate_ohlcv_cache.py
================================
一次性 OHLCV 磁盘缓存预填充脚本。

功能：
  - 从 Alpha Vantage 拉取所有 V4 Watchlist（500支）的完整历史价格（outputsize=full，约20年）
  - 保存到 .cache/av/daily_TICKER_full.json
  - 服务器启动时 AV Client 的 _load_disk_cache() 会自动加载这些文件
  - 加载后，/backtest 页面可回测到 2018-01-01 起

使用方式（本地运行，建议下班后跑，约需 30-60 分钟）：
  cd StockQueen
  python scripts/populate_ohlcv_cache.py

  可选参数：
    --resume        跳过已有磁盘缓存的 ticker（断点续传）
    --limit N       只处理前 N 支（测试用）
    --tickers A,B   只处理指定 ticker

注意：
  - 需要有效的 AV_KEY（Premium，75 req/min）
  - 每支股票约 0.8s（限速），500 支约需 7 分钟
  - 完成后将 .cache/av/ 目录保留，服务器重启时会从磁盘恢复（无需重跑）
"""

import asyncio
import argparse
import os
import sys
import time
import logging

# 确保可以 import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("populate_ohlcv")


async def main(resume: bool, limit: int, only_tickers: list):
    from app.config.rotation_watchlist import get_all_tickers
    from app.services.alphavantage_client import get_av_client

    av = get_av_client()
    cache_dir = av._DISK_CACHE_DIR

    all_tickers = only_tickers if only_tickers else get_all_tickers()
    # 加入 SPY / QQQ 确保基准数据存在
    for must in ["SPY", "QQQ", "IWM"]:
        if must not in all_tickers:
            all_tickers.insert(0, must)

    if limit:
        all_tickers = all_tickers[:limit]

    total = len(all_tickers)
    logger.info(f"目标：{total} 支股票，保存至 {cache_dir}")
    logger.info(f"resume={resume}，预计耗时约 {total * 0.9 / 60:.1f} 分钟")

    done = 0
    skipped = 0
    failed = []
    t0 = time.time()

    for i, ticker in enumerate(all_tickers, 1):
        # 断点续传：已有文件则跳过
        fpath = os.path.join(cache_dir, f"daily_{ticker}_full.json")
        if resume and os.path.isfile(fpath):
            skipped += 1
            if i % 50 == 0:
                logger.info(f"[{i}/{total}] 跳过已缓存：{ticker}（累计跳过 {skipped}）")
            continue

        try:
            df = await av.get_daily_history(ticker, days=9000, outputsize="full")
            if df is not None and not df.empty:
                done += 1
                elapsed = time.time() - t0
                eta = elapsed / i * (total - i) / 60
                if i % 10 == 0 or i <= 5:
                    logger.info(
                        f"[{i}/{total}] OK {ticker}: {len(df)} 行 | "
                        f"进度 {i/total*100:.0f}% | 剩余约 {eta:.1f} 分钟"
                    )
            else:
                failed.append(ticker)
                logger.warning(f"[{i}/{total}] 无数据：{ticker}")
        except Exception as e:
            failed.append(ticker)
            logger.error(f"[{i}/{total}] 失败 {ticker}: {e}")

    elapsed_total = time.time() - t0
    logger.info("=" * 60)
    logger.info(f"完成！耗时 {elapsed_total/60:.1f} 分钟")
    logger.info(f"成功：{done}，跳过：{skipped}，失败：{len(failed)}")
    if failed:
        logger.warning(f"失败列表（可重跑）：{failed}")
    logger.info(f"缓存目录：{cache_dir}")
    logger.info("现在可以重启服务器，/backtest 将支持 2018-01-01 起的回测。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="预填充 OHLCV 磁盘缓存")
    parser.add_argument("--resume", action="store_true",
                        help="跳过已存在的缓存文件（断点续传）")
    parser.add_argument("--limit", type=int, default=0,
                        help="只处理前 N 支（0=全部）")
    parser.add_argument("--tickers", type=str, default="",
                        help="只处理指定 ticker，逗号分隔（如 AAPL,MSFT,SPY）")
    args = parser.parse_args()

    only = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] if args.tickers else []
    asyncio.run(main(resume=args.resume, limit=args.limit, only_tickers=only))
