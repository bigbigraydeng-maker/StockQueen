#!/usr/bin/env python3
"""
完整流程: 市场数据 → 信号生成 → 飞书通知
"""

import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.market_service import MarketDataFetcher
from app.services.signal_service import SignalEngine
from app.services.notification_service import FeishuClient

async def run_signal_pipeline():
    """运行信号生成流程"""
    print("=" * 80)
    print("StockQueen 信号生成流程")
    print("=" * 80)
    print()
    
    # Step 1: 获取市场数据
    print("📊 Step 1: 获取市场数据...")
    print("-" * 80)
    fetcher = MarketDataFetcher()
    market_results = await fetcher.fetch_market_data_for_valid_events()
    
    print(f"  有效事件: {market_results['total_valid_events']}")
    print(f"  成功获取: {market_results['total_fetched']}")
    print(f"  Yahoo Finance: {market_results['yahoo_fallback']}")
    print()
    
    # Step 2: 生成信号
    print("🎯 Step 2: 生成交易信号...")
    print("-" * 80)
    engine = SignalEngine()
    signals = await engine.generate_signals()
    
    print(f"  生成信号: {len(signals)} 个")
    
    if signals:
        print()
        for signal in signals:
            direction_emoji = "📈" if signal.direction == "long" else "📉"
            print(f"  {direction_emoji} {signal.ticker} ({signal.direction})")
            print(f"     入场价: ${signal.entry_price:.2f}")
            print(f"     止损价: ${signal.stop_loss:.2f}")
            print(f"     目标价: ${signal.target_price:.2f}")
            print(f"     信心度: {signal.confidence_score:.1f}%")
    print()
    
    # Step 3: 发送飞书通知
    print("📱 Step 3: 发送飞书通知...")
    print("-" * 80)
    
    feishu = FeishuClient()
    token = await feishu._get_access_token()
    
    if signals:
        content = f"""🎯 StockQueen 交易信号

📊 市场数据
- 获取: {market_results['total_fetched']} 只股票
- 来源: Yahoo Finance

🎯 生成信号: {len(signals)} 个

"""
        for signal in signals:
            direction_emoji = "📈" if signal.direction == "long" else "📉"
            content += f"""{direction_emoji} {signal.ticker} ({signal.direction.upper()})
- 入场: ${signal.entry_price:.2f}
- 止损: ${signal.stop_loss:.2f}
- 目标: ${signal.target_price:.2f}
- 信心: {signal.confidence_score:.1f}%

"""
    else:
        content = f"""📊 StockQueen 日报

📊 市场数据
- 获取: {market_results['total_fetched']} 只股票
- 来源: Yahoo Finance

⚠️ 今日无满足条件的交易信号

信号触发条件:
- 做多: 日涨幅 ≥ 25% + 成交量 ≥ 3倍均值
- 做空: 日跌幅 ≤ -30% + 成交量 ≥ 3倍均值
"""
    
    message_text = f"🎯 StockQueen 信号报告\n\n{content}"
    content_json = json.dumps({"text": message_text}, ensure_ascii=False)
    
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": feishu.receive_id,
                "msg_type": "text",
                "content": content_json
            },
            timeout=10
        )
        
        if response.status_code == 200:
            print("  ✅ 飞书通知发送成功")
        else:
            print(f"  ❌ 发送失败: {response.status_code}")
    
    print()
    print("=" * 80)
    print("流程执行完毕")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_signal_pipeline())
