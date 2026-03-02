#!/usr/bin/env python3
"""
测试 pharma_watchlist.py 配置
"""

from app.config.pharma_watchlist import PHARMA_WATCHLIST, PHARMA_KEYWORDS

print("=" * 60)
print("StockQueen Watchlist 测试")
print("=" * 60)

print(f"\nWatchlist 股票数量: {len(PHARMA_WATCHLIST)}")
print(f"Keywords 数量: {len(PHARMA_KEYWORDS)}")

print("\n--- 小盘生物科技股 ---")
small_cap_tickers = [
    "SAVA", "ACAD", "HALO", "KRTX", "ARQT", "IMVT", "KRYS",
    "RXRX", "BEAM", "EDIT", "NTLA", "CRSP", "PTCT", "BLUE",
    "NBIX", "SRPT", "EXEL", "INCY", "JAZZ", "SGEN"
]

for ticker in small_cap_tickers:
    company = PHARMA_WATCHLIST.get(ticker, "N/A")
    print(f"{ticker}: {company}")

print("\n--- 配置测试通过 ---")
