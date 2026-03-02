#!/usr/bin/env python3
"""
查看今天的信号和扫描记录
"""

import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import get_db

async def check_today_signals():
    """查看今天的信号"""
    print("=" * 80)
    print("今天信号检查")
    print("=" * 80)
    print()
    
    today = datetime.utcnow().strftime("%Y-%m-%d")
    print(f"查询日期: {today} (UTC)")
    print()
    
    db = get_db()
    
    # 1. 查看今天的signals
    print("📊 今天生成的信号:")
    print("-" * 80)
    result = db.table("signals").select("*").gte("created_at", today).execute()
    signals = result.data if result.data else []
    print(f"信号数量: {len(signals)}")
    
    for s in signals:
        print(f"  - {s['ticker']} | {s['direction']} | {s['rating']} | {s['created_at']}")
    print()
    
    # 2. 查看今天的market_snapshots
    print("📈 今天的市场扫描记录:")
    print("-" * 80)
    result = db.table("market_snapshots").select("*").gte("created_at", today).execute()
    snapshots = result.data if result.data else []
    print(f"扫描记录数量: {len(snapshots)}")
    
    tickers = set(s['ticker'] for s in snapshots)
    print(f"扫描股票数量: {len(tickers)}")
    print(f"股票列表: {', '.join(sorted(tickers))}")
    print()
    
    # 3. 查看今天的events
    print("📰 今天的新闻事件:")
    print("-" * 80)
    result = db.table("events").select("*").gte("created_at", today).execute()
    events = result.data if result.data else []
    print(f"新闻数量: {len(events)}")
    
    for e in events[:5]:
        print(f"  - {e.get('ticker', 'N/A')} | {e.get('source', 'N/A')} | {e.get('title', 'N/A')[:50]}...")
    print()
    
    # 4. 查看最近的signal_cooldowns
    print("⏱️ 最近的冷却期记录:")
    print("-" * 80)
    result = db.table("signal_cooldowns").select("*").order("triggered_at", desc=True).limit(10).execute()
    cooldowns = result.data if result.data else []
    print(f"最近10条冷却期记录:")
    
    for c in cooldowns:
        print(f"  - {c['ticker']} | {c['triggered_at']}")
    print()

if __name__ == "__main__":
    asyncio.run(check_today_signals())
