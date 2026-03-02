#!/usr/bin/env python3
"""
手动触发市场扫描和信号生成
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.market_service import MarketDataService
from app.services.signal_service import SignalEngine
from app.services.db_service import AIEventService
from app.models import DirectionBias

async def manual_scan():
    """手动执行扫描"""
    print("=" * 80)
    print("手动市场扫描")
    print("=" * 80)
    print()
    
    # 1. 获取有效事件
    print("📋 步骤1: 获取有效AI事件...")
    ai_service = AIEventService()
    valid_events = await ai_service.get_valid_events()
    print(f"   找到 {len(valid_events)} 个有效事件")
    
    if not valid_events:
        print("   ⚠️ 没有有效事件，扫描结束")
        return
    
    for event in valid_events[:5]:
        print(f"   - {event.ticker} | {event.direction_bias}")
    print()
    
    # 2. 获取市场数据
    print("📊 步骤2: 获取市场数据...")
    market_service = MarketDataService()
    
    for event in valid_events:
        try:
            snapshot = await market_service.fetch_market_data(event.ticker, event.event_id)
            if snapshot:
                print(f"   ✅ {event.ticker}: 收盘价=${snapshot.current_price:.2f}, 日涨跌={snapshot.day_change_pct*100:.2f}%, 成交量倍数={snapshot.volume_multiplier:.2f}x")
            else:
                print(f"   ❌ {event.ticker}: 无法获取市场数据")
        except Exception as e:
            print(f"   ❌ {event.ticker}: 错误 - {e}")
    print()
    
    # 3. 生成信号
    print("🎯 步骤3: 生成交易信号...")
    signal_engine = SignalEngine()
    
    # 初始化冷却期缓存
    await signal_engine._initialize_cooldown_cache()
    
    signals_generated = 0
    
    for event in valid_events:
        try:
            # 获取对应的市场快照
            from app.services.db_service import MarketDataService as DBMarketService
            db_market = DBMarketService()
            snapshots = await db_market.get_snapshots_for_signal_generation()
            
            # 找到对应这个事件的快照
            event_snapshot = None
            for s in snapshots:
                if s.event_id == event.event_id:
                    event_snapshot = s
                    break
            
            if not event_snapshot:
                continue
            
            # 生成信号
            signal = await signal_engine.generate_signal(
                ticker=event.ticker,
                event_id=event.event_id,
                direction_bias=DirectionBias(event.direction_bias),
                market_type=None
            )
            
            if signal:
                print(f"   ✅ {event.ticker}: 生成{signal.direction}信号 ({signal.rating})")
                signals_generated += 1
            else:
                print(f"   ⏭️ {event.ticker}: 未触发信号（可能在冷却期或条件不满足）")
                
        except Exception as e:
            print(f"   ❌ {event.ticker}: 错误 - {e}")
    
    print()
    print("=" * 80)
    print(f"扫描完成，生成 {signals_generated} 个信号")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(manual_scan())
