"""
飞书API客户端 - 用于企业自建应用发送消息
"""

import httpx
import logging
import json
from typing import Optional
from datetime import datetime, timedelta

from app.config import settings

logger = logging.getLogger(__name__)


class FeishuAPIClient:
    """飞书API客户端 - 用于企业自建应用"""
    
    def __init__(self):
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.base_url = "https://open.feishu.cn/open-apis"
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
    
    async def _get_access_token(self) -> str:
        """获取访问令牌"""
        if self.access_token and self.token_expires_at and datetime.utcnow() < self.token_expires_at:
            return self.access_token
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": self.app_id,
                        "app_secret": self.app_secret
                    },
                    timeout=10
                )
                response.raise_for_status()
                
                data = response.json()
                self.access_token = data.get("tenant_access_token")
                expires_in = data.get("expire", 7200)
                self.token_expires_at = datetime.utcnow().replace(second=0, microsecond=0) + timedelta(seconds=expires_in - 300)
                
                logger.info("Feishu access token obtained successfully")
                return self.access_token
                
        except Exception as e:
            logger.error(f"Failed to get Feishu access token: {e}")
            raise
    
    async def send_message(self, receive_id: str, content: str, msg_type: str = "text") -> bool:
        """发送消息
        
        Args:
            receive_id: 接收者ID（用户ID、群组ID或邮件）
            content: 消息内容
            msg_type: 消息类型（text, post, interactive等）
        """
        try:
            token = await self._get_access_token()
            
            if msg_type == "text":
                content_json = json.dumps({"text": content}, ensure_ascii=False)
            elif msg_type == "post":
                content_json = json.dumps({
                    "post": {
                        "zh_cn": {
                            "title": "StockQueen",
                            "content": [[{"tag": "text", "text": content}]]
                        }
                    }
                }, ensure_ascii=False)
            else:
                logger.error(f"Unsupported message type: {msg_type}")
                return False
            
            payload = {
                "receive_id": receive_id,
                "msg_type": msg_type,
                "content": content_json
            }
            
            async with httpx.AsyncClient() as client:
                logger.info(f"[FeishuAPI] Sending message to {receive_id}")
                logger.info(f"[FeishuAPI] Payload: {json.dumps(payload, ensure_ascii=False)}")
                
                response = await client.post(
                    f"{self.base_url}/im/v1/messages?receive_id_type=open_id",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json; charset=utf-8"
                    },
                    content=json.dumps(payload, ensure_ascii=False),
                    timeout=10
                )
                
                logger.info(f"[FeishuAPI] Response status: {response.status_code}")
                logger.info(f"[FeishuAPI] Response body: {response.text}")
                
                response.raise_for_status()
                
                logger.info(f"Feishu message sent successfully to {receive_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to send Feishu message: {e}")
            return False
    
    async def send_text_message(self, receive_id: str, text: str) -> bool:
        """发送文本消息"""
        return await self.send_message(receive_id, text, "text")
    
    async def send_post_message(self, receive_id: str, title: str, content: str) -> bool:
        """发送富文本消息"""
        full_content = f"{title}\n\n{content}"
        return await self.send_message(receive_id, full_content, "text")
