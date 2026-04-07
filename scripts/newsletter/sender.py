"""
StockQueen Newsletter - 邮件发送模块
通过 Resend API 发送 Newsletter
Phase 1: 全部发完整版(paid)  Phase 2: 按 free/paid 分组发送
"""

import os
import hashlib
import hmac
import logging
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger("newsletter.sender")

# 用于生成 unsubscribe token 的密钥
UNSUB_SECRET = os.getenv("UNSUB_SECRET", "stockqueen-unsub-2026")


def _make_unsub_url(email: str) -> str:
    """生成取消订阅 URL（HMAC 签名，无需数据库）"""
    token = hmac.new(
        UNSUB_SECRET.encode(), email.lower().encode(), hashlib.sha256
    ).hexdigest()[:32]
    base = os.getenv("STOCKQUEEN_API_BASE", "https://stockqueen-api.onrender.com")
    return f"{base}/api/newsletter/unsubscribe?email={quote(email)}&token={token}"


def verify_unsub_token(email: str, token: str) -> bool:
    """验证取消订阅 token"""
    expected = hmac.new(
        UNSUB_SECRET.encode(), email.lower().encode(), hashlib.sha256
    ).hexdigest()[:32]
    return hmac.compare_digest(token, expected)


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
    # 获取联系人并按语言分组
    # ------------------------------------------------------------------

    def get_contacts(self, audience_id: str) -> dict:
        """
        从 Resend Audience 获取全部活跃联系人，按语言分组
        返回: {"zh": ["a@b.com", ...], "en": ["c@d.com", ...]}

        语言存储在 first_name 字段（订阅时写入）
        """
        resend = self._get_resend()
        result = {"zh": [], "en": []}
        try:
            resp = resend.Contacts.list(audience_id=audience_id)
            # SDK v2 可能返回 dict 或 list
            contacts = resp.get("data", []) if isinstance(resp, dict) else resp

            for c in contacts:
                if isinstance(c, dict) and c.get("unsubscribed"):
                    continue
                email = c.get("email", "") if isinstance(c, dict) else getattr(c, "email", "")
                lang = c.get("first_name", "en") if isinstance(c, dict) else getattr(c, "first_name", "en")
                if not email:
                    continue
                if lang == "zh":
                    result["zh"].append(email)
                else:
                    result["en"].append(email)

            logger.info(f"[RESEND] Audience 联系人: {len(result['zh'])} 中文, {len(result['en'])} 英文")
        except Exception as e:
            logger.error(f"[RESEND] 获取联系人失败: {e}")

        return result

    # ------------------------------------------------------------------
    # 替换邮件中的 unsubscribe 占位符
    # ------------------------------------------------------------------

    def _inject_unsub(self, html: str, email: str) -> str:
        """将 {{unsubscribe_url}} 替换为真实取消订阅链接"""
        unsub_url = _make_unsub_url(email)
        return html.replace("{{unsubscribe_url}}", unsub_url)

    # ------------------------------------------------------------------
    # 发送单封邮件
    # ------------------------------------------------------------------

    def send_single(self, to_email: str, subject: str, html: str,
                    tags: Optional[list] = None) -> Optional[str]:
        """发送单封邮件，返回 email_id 或 None"""
        resend = self._get_resend()
        # 注入取消订阅链接
        html = self._inject_unsub(html, to_email)
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
            email_id = result.get("id", "unknown") if isinstance(result, dict) else getattr(result, "id", "unknown")
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
        recipients: ["email@example.com", ...]
        返回: {"sent": N, "failed": N, "email_ids": [...]}
        """
        resend = self._get_resend()
        results = {"sent": 0, "failed": 0, "email_ids": []}

        for i in range(0, len(recipients), batch_size):
            batch = recipients[i:i + batch_size]
            batch_params = []
            for email in batch:
                if not email:
                    continue
                params = {
                    "from": self.from_email,
                    "to": [email],
                    "subject": subject,
                    "html": self._inject_unsub(html, email),
                }
                if tags:
                    params["tags"] = [{"name": t, "value": "true"} for t in tags]
                batch_params.append(params)

            if not batch_params:
                continue

            try:
                batch_result = resend.Batch.send(batch_params)
                sent_data = batch_result.get("data", []) if isinstance(batch_result, dict) else batch_result
                sent_count = len(sent_data) if isinstance(sent_data, list) else 1
                results["sent"] += sent_count
                if isinstance(sent_data, list):
                    results["email_ids"].extend([
                        r.get("id", "") if isinstance(r, dict) else getattr(r, "id", "")
                        for r in sent_data
                    ])
                logger.info(f"[RESEND] 批次 {i // batch_size + 1}: {sent_count} 封成功")
            except Exception as e:
                results["failed"] += len(batch_params)
                logger.error(f"[RESEND] 批次 {i // batch_size + 1} 失败: {e}")

        logger.info(f"[RESEND] 发送完成: {results['sent']} 成功, {results['failed']} 失败")
        return results

    # ------------------------------------------------------------------
    # 发送测试邮件
    # ------------------------------------------------------------------

    def send_test(self, to_email: str, html: str, version: str = "free-en") -> bool:
        """发送测试邮件（单封），顶部注入审阅横幅 + 审批链接"""
        subject = f"[审阅] StockQueen Weekly Report ({version})"
        html = self._inject_review_banner(html, version)
        result = self.send_single(to_email, subject, html, tags=["test", version])
        return result is not None

    def _inject_review_banner(self, html: str, version: str) -> str:
        """在邮件 <body> 后注入审阅横幅，含一键审批链接"""
        import hashlib, hmac
        from datetime import datetime as dt

        now = dt.now()
        week_key = f"{now.year}-W{now.isocalendar()[1]:02d}"
        secret = os.getenv("UNSUB_SECRET", "stockqueen-unsub-2026")
        token = hmac.new(secret.encode(), week_key.encode(), hashlib.sha256).hexdigest()[:16]
        base = os.getenv("STOCKQUEEN_API_BASE", "https://stockqueen-api.onrender.com")
        approve_url = f"{base}/api/admin/newsletter/approve?week={week_key}&token={token}"

        banner = f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:0;">
  <tr><td style="background:#fef3c7;border:2px solid #f59e0b;border-radius:12px;padding:18px 24px;text-align:center;">
    <p style="margin:0 0 8px;font-size:14px;color:#92400e;font-weight:700;">
      &#x1F4E8; 审阅预览 &middot; {week_key} &middot; {version}
    </p>
    <p style="margin:0 0 12px;font-size:12px;color:#a16207;">
      这是测试邮件，仅发送给管理员。审阅无误后点击下方按钮批准发送。
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto;">
      <tr>
        <td style="background:#16a34a;border-radius:8px;">
          <a href="{approve_url}" style="display:inline-block;color:#ffffff;padding:10px 28px;text-decoration:none;font-weight:700;font-size:14px;">
            &#x2705; 批准发送给全部订阅者
          </a>
        </td>
      </tr>
    </table>
  </td></tr>
</table>
"""
        # 在 <body> 标签后、第一个 <table> 前插入 banner
        insert_marker = '<table role="presentation" width="100%"'
        if insert_marker in html:
            html = html.replace(insert_marker, banner + insert_marker, 1)
        return html

    # ------------------------------------------------------------------
    # 正式发送全部 Newsletter
    # ------------------------------------------------------------------

    def send_all_newsletters(self, rendered: dict, audience_id: str,
                              week_number: int, year: int) -> dict:
        """
        发送全部 Newsletter 到所有订阅者
        rendered: {"free-zh": html, "free-en": html, "paid-zh": html, "paid-en": html}

        Phase 1（当前）: 所有用户发 paid 版（完整信号）
        Phase 2（未来）: free 用户发 free 版，paid 用户发 paid 版
        """
        subjects = {
            "zh": f"StockQueen 第{week_number}周完整信号报告",
            "en": f"StockQueen Week {week_number} Full Signal Report",
        }

        # 获取联系人（按语言分组）
        contacts = self.get_contacts(audience_id)
        all_results = {}

        # Phase 1: 全部发 paid 版（完整版）
        for lang in ["zh", "en"]:
            recipients = contacts.get(lang, [])
            if not recipients:
                logger.info(f"[NEWSLETTER] {lang}: 无订阅者，跳过")
                all_results[f"paid-{lang}"] = {"sent": 0, "failed": 0, "recipients": 0}
                continue

            html = rendered.get(f"paid-{lang}", "")
            subject = subjects.get(lang, f"StockQueen Week {week_number}")

            logger.info(f"[NEWSLETTER] 发送 paid-{lang} → {len(recipients)} 位订阅者")
            result = self.send_batch(recipients, subject, html, tags=[f"paid-{lang}", f"week-{week_number}"])
            all_results[f"paid-{lang}"] = {**result, "recipients": len(recipients)}

        total_sent = sum(r.get("sent", 0) for r in all_results.values())
        total_failed = sum(r.get("failed", 0) for r in all_results.values())
        logger.info(f"[NEWSLETTER] === 全部完成: {total_sent} 成功, {total_failed} 失败 ===")

        return all_results
