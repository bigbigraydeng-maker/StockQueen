#!/usr/bin/env python3
"""
查看市场快照数据
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.db_service import MarketDataService

async def check_snapshots():
    """查看市场快照"""
    print("=" * 80)
    print("市场快照数据")
    print("=" * 80)
    print()
    
    service = MarketDataService()
    
    # 获取最近的快照
    snapshots = await service.get_snapshots_for_signal_generation()
    
    print(f"快照数量: {len(snapshots)}")
    print()
    
    for snapshot in snapshots:
        print(f"📈 {snapshot.ticker}")
        print(f"   当前价格: ${snapshot.current_price:.2f}")
        print(f"   日涨跌幅: {snapshot.day_change_pct * 100:.2f}%")
        print(f"   成交量: {snapshot.volume:,}")
        print(f"   30日均量: {snapshot.avg_volume_30d:,}")
        print(f"   成交量倍数: {snapshot.volume / snapshot.avg_volume_30d:.2f}x" if snapshot.avg_volume_30d > 0 else "   成交量倍数: N/A")
        print(f"   市值: ${snapshot.market_cap:,.0f}")
        
        # 检查信号条件
        long_condition = snapshot.day_change_pct >= 0.25 and snapshot.volume >= snapshot.avg_volume_30d * 3
        short_condition = snapshot.day_change_pct <= -0.30 and snapshot.volume >= snapshot.avg_volume_30d * 3
        
        if long_condition:
            print(f"   ✅ 满足做多条件")
        elif short_condition:
            print(f"   ✅ 满足做空条件")
        else:
            print(f"   ❌ 不满足信号条件")
            if snapshot.day_change_pct < 0.25 and snapshot.day_change_pct > -0.30:
                print(f"      - 涨跌幅未达标 (需要 ≥25% 或 ≤-30%)")
            if snapshot.volume < snapshot.avg_volume_30d * 3:
                print(f"      - 成交量未达标 (需要 ≥3倍均值)")
        print()

if __name__ == "__main__":
    asyncio.run(check_snapshots())
