"""
飞书事件订阅诊断脚本
检查飞书长连接和事件订阅配置
"""

import asyncio
import logging
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class FeishuDiagnostics:
    """飞书诊断工具"""
    
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.client = None
        self.message_count = 0
        self.last_message = None
        
    def _create_event_handler(self):
        """创建事件处理器"""
        def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1):
            """处理接收消息事件"""
            self.message_count += 1
            self.last_message = data
            
            logger.info("=" * 60)
            logger.info(f"📨 收到消息 #{self.message_count}")
            logger.info("=" * 60)
            
            try:
                if data.event and data.event.message:
                    message = data.event.message
                    content = message.content
                    sender = data.event.sender
                    
                    logger.info(f"消息ID: {message.message_id}")
                    logger.info(f"消息类型: {message.msg_type}")
                    logger.info(f"创建时间: {message.create_time}")
                    
                    if sender and sender.sender_id:
                        logger.info(f"发送者ID: {sender.sender_id.user_id}")
                        logger.info(f"发送者类型: {sender.sender_id.type}")
                    
                    logger.info(f"原始内容: {content}")
                    
                    # 解析文本内容
                    import json
                    try:
                        content_dict = json.loads(content)
                        text = content_dict.get("text", "")
                        logger.info(f"文本内容: {text}")
                    except json.JSONDecodeError:
                        logger.warning("无法解析消息内容")
                
                logger.info("=" * 60)
                
            except Exception as e:
                logger.error(f"处理消息时出错: {e}")
                import traceback
                traceback.print_exc()
        
        # 构建事件处理器
        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
            .build()
        
        logger.info("✅ 事件处理器创建成功")
        return event_handler
    
    async def _run_client(self):
        """运行WebSocket客户端"""
        logger.info("🚀 启动飞书WebSocket客户端...")
        
        try:
            # 创建事件处理器
            event_handler = self._create_event_handler()
            
            # 创建Lark WebSocket客户端
            self.client = lark.ws.Client(
                self.app_id,
                self.app_secret,
                event_handler=event_handler,
                log_level=lark.LogLevel.INFO
            )
            
            logger.info("✅ Lark WebSocket客户端创建成功")
            
            # 启动客户端（阻塞）
            logger.info("📡 正在连接到飞书服务器...")
            self.client.start()
            
        except Exception as e:
            logger.error(f"❌ WebSocket客户端启动失败: {e}")
            import traceback
            traceback.print_exc()
    
    async def start(self):
        """启动诊断"""
        logger.info("=" * 60)
        logger.info("飞书事件订阅诊断工具")
        logger.info("=" * 60)
        logger.info(f"应用ID: {self.app_id}")
        logger.info(f"应用密钥: {self.app_secret[:10]}...")
        logger.info("=" * 60)
        
        # 启动客户端
        await self._run_client()
    
    def get_status(self):
        """获取状态"""
        status = {
            "message_count": self.message_count,
            "last_message": self.last_message,
            "is_connected": self.client is not None
        }
        return status


async def main():
    """主函数"""
    # 从环境变量读取配置
    from app.config import settings
    
    app_id = settings.feishu_app_id
    app_secret = settings.feishu_app_secret
    
    if not app_id or not app_secret:
        logger.error("❌ 飞书应用凭证未配置")
        logger.info("请在.env文件中设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        return
    
    # 创建诊断工具
    diagnostics = FeishuDiagnostics(app_id, app_secret)
    
    # 启动诊断
    await diagnostics.start()


if __name__ == "__main__":
    print("=" * 60)
    print("飞书事件订阅诊断工具")
    print("=" * 60)
    print()
    print("使用说明:")
    print("1. 确保StockQueen应用正在运行")
    print("2. 确保飞书开放平台已配置事件订阅")
    print("3. 将机器人添加到飞书群组")
    print("4. 在飞书中给机器人发送测试消息")
    print()
    print("测试命令:")
    print("  - status 或 状态")
    print("  - signals 或 信号")
    print("  - watchlist 或 关注")
    print()
    print("按 Ctrl+C 停止诊断")
    print("=" * 60)
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 诊断已停止")
