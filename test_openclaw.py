"""
测试OpenClaw集成
"""

import asyncio
import httpx
from datetime import datetime
from app.services.notification_service import NotificationService
from app.models import Signal


async def test_openclaw_connection():
    """测试OpenClaw连接"""
    from app.config import settings
    
    webhook_url = settings.openclaw_webhook_url
    
    if not webhook_url:
        print("❌ OPENCLAW_WEBHOOK_URL 未配置")
        print("请在.env文件中设置 OPENCLAW_WEBHOOK_URL")
        return False
    
    print(f"📡 测试OpenClaw连接: {webhook_url}")
    
    payload = {
        "type": "test",
        "message": "Test notification from StockQueen",
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, timeout=10)
            print(f"✅ 状态码: {response.status_code}")
            print(f"📄 响应: {response.text}")
            return response.status_code == 200
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return False


async def test_signal_notification():
    """测试信号通知"""
    print("\n📊 测试信号通知...")
    
    service = NotificationService()
    
    # 创建测试信号
    signal = Signal(
        ticker="MRNA",
        direction="long",
        entry_price=120.50,
        stop_loss=115.00,
        target_price=140.00,
        reason="FDA approval announcement"
    )
    
    # 发送交易确认通知
    result = await service.send_trade_confirmation(signal, "ORDER123456")
    
    if result:
        print("✅ 信号通知发送成功")
    else:
        print("❌ 信号通知发送失败")
    
    return result


async def test_signal_summary():
    """测试信号摘要"""
    print("\n📋 测试信号摘要...")
    
    service = NotificationService()
    
    # 创建测试信号列表
    signals = [
        Signal(
            ticker="MRNA",
            direction="long",
            entry_price=120.50,
            stop_loss=115.00,
            target_price=140.00,
            reason="FDA approval announcement"
        ),
        Signal(
            ticker="PFE",
            direction="short",
            entry_price=45.00,
            stop_loss=48.00,
            target_price=40.00,
            reason="Clinical trial failure"
        )
    ]
    
    # 发送信号摘要
    result = await service.send_signal_summary(signals)
    
    if result:
        print("✅ 信号摘要发送成功")
    else:
        print("❌ 信号摘要发送失败")
    
    return result


async def main():
    """主函数"""
    print("=" * 60)
    print("StockQueen - OpenClaw 集成测试")
    print("=" * 60)
    print()
    
    # 测试1: 连接测试
    connection_ok = await test_openclaw_connection()
    
    if not connection_ok:
        print("\n⚠️  OpenClaw连接失败，跳过后续测试")
        return
    
    # 测试2: 信号通知
    await test_signal_notification()
    
    # 测试3: 信号摘要
    await test_signal_summary()
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    print("=" * 60)
    print("StockQueen - OpenClaw 集成测试")
    print("=" * 60)
    print()
    print("使用说明:")
    print("1. 确保OpenClaw已部署并运行")
    print("2. 在.env文件中配置OPENCLAW_WEBHOOK_URL")
    print("3. 运行此脚本测试连接")
    print()
    print("配置示例:")
    print("OPENCLAW_WEBHOOK_URL=http://localhost:8080/api/webhook/{your-webhook-id}")
    print()
    print("=" * 60)
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 测试已停止")
