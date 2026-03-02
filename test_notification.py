"""
手动发送测试通知到飞书
"""

import asyncio
from app.services.notification_service import NotificationService
from app.models import Signal
from datetime import datetime


async def send_test_notification():
    """发送测试通知"""
    print("=" * 60)
    print("StockQueen - 手动发送测试通知")
    print("=" * 60)
    print()
    
    service = NotificationService()
    
    # 创建测试信号
    test_signal = Signal(
        event_id="test_event_001",
        market_snapshot_id="test_snapshot_001",
        ticker="MRNA",
        direction="long",
        entry_price=120.50,
        stop_loss=115.00,
        target_price=140.00,
        reason="FDA approval announcement - TEST"
    )
    
    print("📊 发送测试信号摘要...")
    print(f"Ticker: {test_signal.ticker}")
    print(f"Direction: {test_signal.direction}")
    print(f"Entry: ${test_signal.entry_price}")
    print(f"Stop: ${test_signal.stop_loss}")
    print(f"Target: ${test_signal.target_price}")
    print()
    
    # 发送交易确认通知
    result = await service.send_trade_confirmation(test_signal, "TEST_ORDER_123456")
    
    if result:
        print("✅ 测试通知发送成功！")
        print()
        print("请检查飞书群是否收到测试消息。")
    else:
        print("❌ 测试通知发送失败！")
        print()
        print("可能的原因：")
        print("1. 飞书API凭证配置错误")
        print("2. 飞书机器人未添加到群组")
        print("3. 飞书机器人权限不足")
        print()
        print("请检查日志获取详细错误信息。")
    
    print()
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(send_test_notification())
    except KeyboardInterrupt:
        print("\n\n👋 测试已停止")
    except Exception as e:
        print(f"\n\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
