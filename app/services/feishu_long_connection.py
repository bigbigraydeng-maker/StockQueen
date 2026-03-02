"""
StockQueen V1 - Feishu Long Connection Service
WebSocket long connection for Feishu event subscription
"""

import asyncio
import logging
import lark_oapi
from lark_oapi import EventDispatcherHandler
from lark_oapi.ws import Client as WsClient

from app.config import settings

logger = logging.getLogger(__name__)


class FeishuLongConnectionService:
    """Feishu long connection service using WebSocket"""

    def __init__(self):
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.client = None
        self.is_running = False

    def _create_event_handler(self):
        """Create event handler for Feishu events"""
        class EventHandler(EventDispatcherHandler):
            def handle_p2_im_message_receive_v1(self, data):
                """Handle receive message event"""
                logger.info(f"Received message event: {data}")
                # Process message event here
                return None

        return EventHandler()

    async def start(self):
        """Start long connection"""
        if not self.app_id or not self.app_secret:
            logger.error("Feishu APP_ID or APP_SECRET not configured")
            return False

        try:
            # Create event handler
            event_handler = self._create_event_handler()

            # Create long connection client
            self.client = WsClient(
                app_id=self.app_id,
                app_secret=self.app_secret,
                event_handler=event_handler
            )

            # Start connection (synchronous start)
            logger.info("Starting Feishu long connection...")
            import threading
            def start_client():
                try:
                    self.client.start()
                except Exception as e:
                    logger.error(f"Error in client thread: {e}")

            # Start client in a separate thread
            thread = threading.Thread(target=start_client, daemon=True)
            thread.start()

            # Wait a bit for connection to establish
            await asyncio.sleep(2)

            self.is_running = True
            logger.info("Feishu long connection started successfully")
            return True

        except Exception as e:
            logger.error(f"Error starting Feishu long connection: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def stop(self):
        """Stop long connection"""
        if self.client:
            try:
                self.client.stop()
                self.is_running = False
                logger.info("Feishu long connection stopped")
            except Exception as e:
                logger.error(f"Error stopping Feishu long connection: {e}")

    def is_connected(self):
        """Check if connection is active"""
        return self.is_running


# Global instance
feishu_long_connection = FeishuLongConnectionService()


async def start_feishu_long_connection():
    """Start Feishu long connection"""
    return await feishu_long_connection.start()


async def stop_feishu_long_connection():
    """Stop Feishu long connection"""
    return await feishu_long_connection.stop()


def get_feishu_long_connection():
    """Get Feishu long connection instance"""
    return feishu_long_connection
