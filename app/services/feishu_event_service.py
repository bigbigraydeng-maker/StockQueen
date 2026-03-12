"""
StockQueen V1 - Feishu Platform WebSocket Connection
Feishu Open Platform event subscription long connection
Updated with AI chat support
"""

import asyncio
import logging
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class FeishuEventService:
    """
    Feishu Platform Event Service using Lark SDK
    
    Establishes WebSocket long connection to receive Feishu events:
    - Messages
    - Group joins
    - Bot mentions
    - Card actions
    """
    
    def __init__(self):
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.client = None
        self.is_running = False
        self._initialized = False
        self._connect_task = None
        
        logger.info(f"[FeishuEventService.__init__] Initialized for app: {self.app_id[:10]}...")
    
    def _create_event_handler(self):
        """Create event handler for Feishu events"""
        logger.info("[FeishuEventService._create_event_handler] Creating event handler...")
        
        def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1):
            """Handle receive message event v2.0"""
            try:
                logger.info(f"[FeishuEventService] Received message event v2.0")
                logger.info(f"[FeishuEventService] Data: {lark.JSON.marshal(data, indent=2)}")
                
                # Extract message content
                if data.event and data.event.message:
                    message = data.event.message
                    content = message.content
                    sender = data.event.sender
                    chat_id = message.chat_id if message else "unknown"
                    
                    # TEMPORARY: Print chat_id for configuration
                    sender_id = sender.sender_id.open_id if sender and sender.sender_id else "unknown"
                    print("=" * 60)
                    print(f"📨 收到飞书消息")
                    print(f"Chat ID: {chat_id}")
                    print(f"Sender ID: {sender_id}")
                    print("=" * 60)
                    
                    # Parse content
                    import json
                    try:
                        content_dict = json.loads(content)
                        text = content_dict.get("text", "")
                        
                        logger.info(f"[FeishuEventService] Message from {sender_id}: {text}")
                        
                        # Process message
                        asyncio.create_task(self._process_user_message(text, sender_id, data))
                    except json.JSONDecodeError:
                        logger.warning(f"[FeishuEventService] Failed to parse message content: {content}")
                
            except Exception as e:
                logger.error(f"[FeishuEventService] Error handling message event: {e}")
                import traceback
                traceback.print_exc()
        
        # Build event handler
        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
            .build()
        
        logger.info("[FeishuEventService._create_event_handler] Event handler created successfully")
        return event_handler
    
    async def _process_user_message(self, text: str, user_id: str, event_data):
        """Process user message and respond"""
        text_lower = text.lower().strip()
        
        # Command handling
        if text_lower in ["status", "状态", "help", "帮助"]:
            await self._send_status_message(user_id)
        elif text_lower in ["signals", "信号"]:
            await self._send_signals_message(user_id)
        elif text_lower in ["watchlist", "关注"]:
            await self._send_watchlist_message(user_id)
        elif text_lower in ["clear", "清除", "清空"]:
            from app.services.ai_service import get_ai_chat_service
            ai_service = get_ai_chat_service()
            ai_service.clear_history(user_id)
            await self._send_message(user_id, "✅ 对话历史已清除")
        elif text_lower.startswith("/feed ") or text_lower.startswith("#投喂"):
            # Knowledge feed via Feishu
            await self._handle_knowledge_feed(text, user_id)
        else:
            # Use AI to respond
            await self._send_ai_response(user_id, text)

    async def _handle_knowledge_feed(self, text: str, user_id: str):
        """Handle knowledge feed from Feishu message"""
        try:
            # Strip the command prefix
            if text.lower().startswith("/feed "):
                content = text[6:].strip()
            elif text.startswith("#投喂"):
                content = text[3:].strip()
            else:
                content = text.strip()

            if not content:
                await self._send_message(user_id, "请在命令后输入要投喂的内容")
                return

            from app.services.knowledge_service import get_knowledge_service
            ks = get_knowledge_service()

            entry = await ks.add_knowledge(
                content=content,
                source_type="user_feed_text",
                category=None,  # Auto-detect
            )

            if entry:
                tickers_str = ", ".join(entry.tickers) if entry.tickers else "无"
                await self._send_message(
                    user_id,
                    f"已收录到知识库 ✅\n标的: {tickers_str}\n摘要: {entry.summary or content[:100]}"
                )
            else:
                await self._send_message(user_id, "知识入库失败，请稍后重试")

        except Exception as e:
            logger.error(f"Error handling knowledge feed: {e}")
            await self._send_message(user_id, f"投喂失败: {str(e)}")
    
    async def _send_ai_response(self, user_id: str, message: str):
        """Send AI-generated response"""
        try:
            from app.services.ai_service import get_ai_chat_service
            ai_service = get_ai_chat_service()
            
            # Show typing indicator (optional)
            logger.info(f"[FeishuEventService] Generating AI response for user {user_id[:10]}...")
            
            # Get AI response
            response = await ai_service.chat(user_id, message)
            
            # Send response
            await self._send_message(user_id, response)
            
        except Exception as e:
            logger.error(f"[FeishuEventService] Error getting AI response: {e}")
            await self._send_message(user_id, f"抱歉，处理您的消息时出错。请稍后重试。\n\n发送 '帮助' 查看可用命令。")
    
    async def _send_message(self, user_id: str, content: str):
        """Send message to user via Feishu API"""
        try:
            from app.services.feishu_api_client import FeishuAPIClient
            client = FeishuAPIClient()
            success = await client.send_text_message(user_id, content)
            if success:
                logger.info(f"[FeishuEventService] Message sent to {user_id}")
            else:
                logger.error(f"[FeishuEventService] Failed to send message to {user_id}")
            return success
        except Exception as e:
            logger.error(f"[FeishuEventService] Error sending message: {e}")
            return False
    
    async def _send_status_message(self, user_id: str):
        """Send system status"""
        from datetime import datetime
        message = "📊 StockQueen 状态\n\n"
        message += "✅ 系统: 运行中\n"
        message += "✅ AI服务: 已连接\n"
        message += "✅ WebSocket: 已连接\n"
        message += f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += "\n📋 可用命令:\n"
        message += "- 帮助 / help - 显示此帮助信息\n"
        message += "- 状态 / status - 查看系统状态\n"
        message += "- 信号 / signals - 查看今日信号\n"
        message += "- 关注 / watchlist - 查看关注列表\n"
        message += "- 清除 / clear - 清除对话历史\n\n"
        message += "💬 直接发送消息即可与AI助手对话"
        
        await self._send_message(user_id, message)
    
    async def _send_signals_message(self, user_id: str):
        """Send current signals"""
        message = "📈 今日信号\n\n"
        message += "暂无新信号\n"
        message += "系统正在监控医药股新闻..."
        
        await self._send_message(user_id, message)
    
    async def _send_watchlist_message(self, user_id: str):
        """Send watchlist info"""
        message = "👀 关注列表\n\n"
        message += "医药股监控中...\n"
        message += "包括: SAVA, GILD, MRK 等"
        
        await self._send_message(user_id, message)
    
    async def _run_client(self):
        """Run WebSocket client in background"""
        try:
            logger.info("[FeishuEventService._run_client] Starting Feishu WebSocket client...")
            # Connect directly instead of using start()
            await self.client._connect()
            logger.info("[FeishuEventService._run_client] Feishu WebSocket connected successfully")
        except Exception as e:
            logger.error(f"[FeishuEventService._run_client] Error in Feishu client: {e}")
            import traceback
            traceback.print_exc()
    
    async def initialize(self):
        """Initialize and start event listening"""
        logger.info(f"[FeishuEventService.initialize] Called. _initialized={self._initialized}")
        
        if self._initialized:
            logger.info("[FeishuEventService.initialize] Already initialized, returning True")
            return True
        
        if not self.app_id or not self.app_secret:
            logger.warning("[FeishuEventService.initialize] Feishu app credentials not configured, skipping event service")
            return False
        
        logger.info("[FeishuEventService.initialize] Initializing Feishu Event Service...")
        
        try:
            # Create event handler
            event_handler = self._create_event_handler()
            
            # Create Lark WebSocket client
            logger.info("[FeishuEventService.initialize] Creating Lark WebSocket client...")
            self.client = lark.ws.Client(
                self.app_id,
                self.app_secret,
                event_handler=event_handler,
                log_level=lark.LogLevel.INFO
            )
            logger.info("[FeishuEventService.initialize] Lark WebSocket client created")
            
            # Start client as background task
            logger.info("[FeishuEventService.initialize] Starting client as background task...")
            self._connect_task = asyncio.create_task(self._run_client())
            
            # Wait a bit for connection to establish
            logger.info("[FeishuEventService.initialize] Waiting 3 seconds for connection to establish...")
            await asyncio.sleep(3)
            
            self.is_running = True
            self._initialized = True
            logger.info("[FeishuEventService.initialize] Feishu Event Service initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"[FeishuEventService.initialize] Failed to initialize Feishu Event Service: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def shutdown(self):
        """Shutdown service"""
        if not self._initialized:
            return
        
        logger.info("[FeishuEventService.shutdown] Shutting down Feishu Event Service...")
        self.is_running = False
        
        # Cancel connect task
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
            try:
                await self._connect_task
            except asyncio.CancelledError:
                pass
        
        if self.client:
            try:
                await self.client._disconnect()
                logger.info("[FeishuEventService.shutdown] Feishu WebSocket client stopped")
            except Exception as e:
                logger.error(f"[FeishuEventService.shutdown] Error stopping Feishu client: {e}")
        
        self._initialized = False
        logger.info("[FeishuEventService.shutdown] Feishu Event Service shutdown complete")
    
    def is_connected(self):
        """Check if connection is active"""
        return self.is_running


# Singleton instance
_feishu_event_service: Optional[FeishuEventService] = None


def get_feishu_event_service() -> FeishuEventService:
    """Get or create singleton instance"""
    global _feishu_event_service
    if _feishu_event_service is None:
        logger.info("[get_feishu_event_service] Creating new FeishuEventService instance")
        _feishu_event_service = FeishuEventService()
    else:
        logger.info("[get_feishu_event_service] Returning existing FeishuEventService instance")
    return _feishu_event_service


# Convenience functions
async def start_feishu_event_client() -> bool:
    """Start Feishu event client globally"""
    logger.info("[start_feishu_event_client] Called")
    service = get_feishu_event_service()
    try:
        logger.info("[start_feishu_event_client] Calling service.initialize()...")
        result = await service.initialize()
        logger.info(f"[start_feishu_event_client] service.initialize() returned: {result}")
        return result
    except Exception as e:
        logger.error(f"[start_feishu_event_client] Failed to start Feishu event client: {e}")
        import traceback
        traceback.print_exc()
        return False


async def stop_feishu_event_client():
    """Stop Feishu event client globally"""
    logger.info("[stop_feishu_event_client] Called")
    service = get_feishu_event_service()
    await service.shutdown()
