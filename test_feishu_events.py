"""
Test Feishu Event Subscription
验证飞书事件订阅是否正常工作
"""

import asyncio
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
import os
from dotenv import load_dotenv

load_dotenv()

app_id = os.getenv("FEISHU_APP_ID")
app_secret = os.getenv("FEISHU_APP_SECRET")

print("=" * 60)
print("飞书事件订阅测试")
print("=" * 60)
print(f"App ID: {app_id}")
print(f"App Secret: {app_secret[:10]}..." if app_secret else "None")
print()

if not app_id or not app_secret:
    print("错误：FEISHU_APP_ID 或 FEISHU_APP_SECRET 未配置")
    exit(1)

def create_event_handler():
    """创建事件处理器"""
    print("创建事件处理器...")
    
    def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1):
        """处理接收消息事件"""
        print("=" * 60)
        print("✅ 收到飞书消息事件！")
        print("=" * 60)
        print(f"完整数据：")
        print(lark.JSON.marshal(data, indent=2))
        print("=" * 60)
        
        # 提取关键信息
        if data.event and data.event.message:
            message = data.event.message
            content = message.content
            sender = data.event.sender
            chat_id = data.event.chat_id if data.event else "unknown"
            
            print(f"Chat ID: {chat_id}")
            print(f"Sender ID: {sender.sender_id.user_id if sender and sender.sender_id else 'unknown'}")
            print(f"Message Content: {content}")
            print("=" * 60)
    
    # 构建事件处理器
    event_handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
        .build()
    
    print("事件处理器创建成功")
    return event_handler

async def main():
    """主函数"""
    print("创建飞书WebSocket客户端...")
    
    event_handler = create_event_handler()
    
    client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO
    )
    
    print("WebSocket客户端创建成功")
    print()
    print("正在连接飞书服务器...")
    print()
    
    try:
        # 启动客户端
        await client._connect()
        print("✅ 飞书长连接已建立！")
        print()
        print("现在请在飞书中给机器人发送一条消息（例如：'测试'）")
        print("如果收到消息事件，会显示在下方...")
        print()
        print("按 Ctrl+C 停止测试")
        print("=" * 60)
        print()
        
        # 保持连接
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\n正在断开连接...")
        await client._disconnect()
        print("已断开连接")
    except Exception as e:
        print(f"错误：{e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
