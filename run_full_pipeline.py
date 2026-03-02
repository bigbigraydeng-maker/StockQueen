#!/usr/bin/env python3
"""
运行完整流程: 新闻抓取 → AI分类 → 飞书通知
"""

import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.news_service import NewsService
from app.services.ai_service import AIClassificationService
from app.services.notification_service import FeishuClient

async def run_full_pipeline():
    """运行完整流程"""
    print("=" * 80)
    print("StockQueen 完整流程测试")
    print("=" * 80)
    print()
    
    # Step 1: 新闻抓取
    print("📰 Step 1: 新闻抓取...")
    print("-" * 80)
    news_service = NewsService()
    news_results = await news_service.fetch_and_process_all()
    
    print(f"  总抓取: {news_results['total_fetched']}")
    print(f"  过滤后: {news_results['total_filtered']}")
    print(f"  存储: {news_results['total_stored']}")
    print()
    
    if news_results['total_stored'] == 0:
        print("⚠️ 没有存储新闻，跳过AI分类")
        return
    
    # Step 2: AI分类
    print("🤖 Step 2: AI分类...")
    print("-" * 80)
    ai_service = AIClassificationService()
    ai_results = await ai_service.process_pending_events()
    
    print(f"  待处理: {ai_results['total_pending']}")
    print(f"  已处理: {ai_results['total_processed']}")
    print(f"  有效事件: {ai_results['total_valid']}")
    print()
    
    if ai_results['total_valid'] == 0:
        print("⚠️ 没有有效事件，跳过飞书通知")
        return
    
    # Step 3: 飞书通知
    print("📱 Step 3: 发送飞书通知...")
    print("-" * 80)
    
    feishu = FeishuClient()
    
    # 构建通知内容
    content = f"""📊 StockQueen 日报

📰 新闻抓取
- 抓取: {news_results['total_fetched']} 条
- 过滤: {news_results['total_filtered']} 条
- 存储: {news_results['total_stored']} 条

🤖 AI分类
- 处理: {ai_results['total_processed']} 条
- 有效: {ai_results['total_valid']} 条

✅ 系统运行正常"""
    
    success = await feishu.send_feishu_message(
        title="📊 StockQueen 日报",
        content=content
    )
    
    if success:
        print("  ✅ 飞书通知发送成功")
    else:
        print("  ❌ 飞书通知发送失败")
    
    print()
    print("=" * 80)
    print("完整流程执行完毕")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_full_pipeline())
