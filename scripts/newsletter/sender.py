"""
StockQueen Newsletter - 邮件发送模块
通过 Resend API 发送 Newsletter，按 free/paid 标签分组
"""

import os
import logging
from typing import Optional

logger = logging.getLogger("newsletter.sender")


class NewsletterSender:
    """通过 Resend API 发送 Newsletter"""

    def __init__(self, api_key: Optional[str] = None, from_email: Optional[str] = None):
        self.api_key = api_key or os.getenv("RESEND_API_KEY", "")
        self.from_email = from_email or os.getenv(
            "NEWSLETTER_FROM",
            "StockQueen Newsletter <newsletter@stockqueen.tech>"
        )
        self._resend = None

    def _get_resend(self):
        """延迟初始化 Resend SDK"""
        if self._resend is None:
            try:
                import resend
                resend.api_key = self.api_key
                self._resend = resend
            except ImportError:
                raise RuntimeError("请安装 resend: pip install resend")
        return self._resend

    def validate_config(self) -> bool:
        """验证配置是否完整"""
        if not self.api_key:
            logger.error("❌ RESEND_API_KEY 未设置")
            return False
        if not self.api_key.startswith("re_"):
            logger.error("❌ RESEND_API_KEY 格式不正确（应以 're_' 开头）")
            return False
        return True

    # ------------------------------------------------------------------
    # 按标签获取联系人（从 Resend Audience 获取）
    # ------------------------------------------------------------------

    async def get_contacts_by_tag(self, audience_id: str, tag: str) -> list:
        """
        从 Resend Audience 获取特定标签的联系人
        tag: "free" | "paid" | "free-zh" | "free-en" | "paid-zh" | "paid-en"
        返回: [{"email": "...", "first_name": "...", "tags": [...]}]

        注意：Resend 联系人管理需要后续集成 Stripe Webhook 来自动打标签
        目前先返回 audience 全部联系人，后续按 tag 过滤
        """
        resend = self._get_resend()
        try:
            contacts = resend.Contacts.list(audience_id=audience_id)
            # 按 tag 过滤（Resend 联系人有 unsubscribed 字段）
            active = [c for c in contacts.get("data", []) if not c.get("unsubscribed", False)]
            logger.info(f"[RESEND] Audience {audience_id}: {len(active)} 活跃联系人")
            return active
        except Exception as e:
            logger.error(f"[RESEND] 获取联系人失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 发送单封邮件
    # ------------------------------------------------------------------

    def send_single(self, to_email: str, subject: str, html: str,
                    tags: Optional[list] = None) -> Optional[str]:
        """
        发送单封邮件
        返回 email_id 或 None
        """
        resend = self._get_resend()
        try:
            params = {
                "from": self.from_email,
                "to": [to_email],
                "subject": subject,
                "html": html,
            }
            if tags:
                params["tags"] = [{"name": t, "value": "true"} for t in tags]

            result = resend.Emails.send(params)
            email_id = result.get("id", "unknown")
            logger.info(f"[RESEND] ✅ 发送成功: {to_email} (ID: {email_id})")
            return email_id
        except Exception as e:
            logger.error(f"[RESEND] ❌ 发送失败 {to_email}: {e}")
            return None

    # ------------------------------------------------------------------
    # 批量发送
    # ------------------------------------------------------------------

    def send_batch(self, recipients: list, subject: str, html: str,
                   tags: Optional[list] = None, batch_size: int = 50) -> dict:
        """
        批量发送 Newsletter
        recipients: [{"email": "...", "first_name": "..."}]
        返回: {"sent": N, "failed": N, "email_ids": [...]}
        """
        resend = self._get_resend()

        results = {"sent": 0, "failed": 0, "email_ids": []}

        # Resend 支持批量发送（最多100封/批）
        for i in range(0, len(recipients), batch_size):
            batch = recipients[i:i + batch_size]
            batch_params = []
            for r in batch:
                email = r if isinstance(r, str) else r.get("email", "")
                if not email:
                    continue
                params = {
                    "from": self.from_email,
                    "to": [email],
                    "subject": subject,
                    "html": html,
                }
                if tags:
                    params["tags"] = [{"name": t, "value": "true"} for t in tags]
                batch_params.append(params)

            if not batch_params:
                continue

            try:
                # Resend batch API
                batch_result = resend.Batch.send(batch_params)
                sent_ids = batch_result.get("data", [])
                results["sent"] += len(sent_ids)
                results["email_ids"].extend([r.get("id", "") for r in sent_ids])
                logger.info(f"[RESEND] 批次 {i // batch_size + 1}: {len(sent_ids)} 封成功")
            except Exception as e:
                results["failed"] += len(batch_params)
                logger.error(f"[RESEND] 批次 {i // batch_size + 1} 失败: {e}")

        logger.info(f"[RESEND] 发送完成: {results['sent']} 成功, {results['failed']} 失败")
        return results

    # ------------------------------------------------------------------
    # 发送测试邮件
    # ------------------------------------------------------------------

    def send_test(self, to_email: str, html: str, version: str = "free-en") -> bool:
        """发送测试邮件（单封）"""
        subject = f"[TEST] StockQueen Weekly Report ({version})"
        result = self.send_single(to_email, subject, html, tags=["test", version])
        return result is not None

    # ------------------------------------------------------------------
    # 发送全部 Newsletter
    # ------------------------------------------------------------------

    def send_all_newsletters(self, rendered: dict, audience_id: str,
                              week_number: int, year: int) -> dict:
        """
        发送全部4种 Newsletter
        rendered: {"free-zh": html, "free-en": html, "paid-zh": html, "paid-en": html}

        TODO: 联系人标签管理（需要 Resend Audience 按 tag 分组）
        目前先发送到测试邮箱，后续集成 Stripe 后自动分组
        """
        subjects = {
            "free-zh": f"StockQueen 第{week_number}周策略报告",
            "free-en": f"StockQueen Week {week_number} Strategy Report",
            "paid-zh": f"StockQueen 第{week_number}周完整信号报告",
            "paid-en": f"StockQueen Week {week_number} Full Signal Report",
        }

        all_results = {}
        for version, html in rendered.items():
            subject = subjects.get(version, f"StockQueen Week {week_number}")
            # TODO: 从 audience 获取对应标签的联系人
            # contacts = await self.get_contacts_by_tag(audience_id, version)
            # result = self.send_batch(contacts, subject, html, tags=[version])
            all_results[version] = {"subject": subject, "status": "ready", "html_length": len(html)}
            logger.info(f"[NEWSLETTER] {version}: {subject} ({len(html)} chars)")

        return all_results
