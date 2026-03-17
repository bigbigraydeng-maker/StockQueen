"""
StockQueen - Stripe 支付集成
支持三种订阅计划：月付 $49 / 季付 $129 / 年付 $399
包含 7 天免费试用

环境变量:
    STRIPE_SECRET_KEY      - Stripe Secret Key (sk_live_xxx 或 sk_test_xxx)
    STRIPE_PUBLISHABLE_KEY - Stripe Publishable Key (pk_live_xxx 或 pk_test_xxx)
    STRIPE_WEBHOOK_SECRET  - Webhook 签名密钥 (whsec_xxx)
    STRIPE_PRICE_MONTHLY   - 月付 Price ID (price_xxx)
    STRIPE_PRICE_QUARTERLY - 季付 Price ID (price_xxx)
    STRIPE_PRICE_YEARLY    - 年付 Price ID (price_xxx)
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, HTMLResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["payments"])


def _get_stripe():
    """延迟初始化 Stripe SDK"""
    import stripe
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    return stripe


# ==================================================================
# 价格配置
# ==================================================================

PLANS = {
    "monthly": {
        "name_en": "Pro Monthly",
        "name_zh": "专业版 月付",
        "amount": 4900,  # cents
        "display": "$49/mo",
        "interval": "month",
        "interval_count": 1,
        "trial_days": 7,
    },
    "quarterly": {
        "name_en": "Pro Quarterly",
        "name_zh": "专业版 季付",
        "amount": 12900,
        "display": "$129/quarter",
        "interval": "month",
        "interval_count": 3,
        "trial_days": 7,
    },
    "yearly": {
        "name_en": "Pro Yearly",
        "name_zh": "专业版 年付",
        "amount": 39900,
        "display": "$399/year",
        "interval": "year",
        "interval_count": 1,
        "trial_days": 7,
    },
}


# ==================================================================
# 创建 Checkout Session
# ==================================================================

@router.post("/api/payments/create-checkout", response_class=JSONResponse)
async def create_checkout_session(request: Request):
    """
    创建 Stripe Checkout Session
    Body: { "plan": "monthly"|"quarterly"|"yearly", "email": "...", "lang": "en"|"zh" }
    返回: { "url": "https://checkout.stripe.com/..." }
    """
    try:
        body = await request.json()
        plan_key = body.get("plan", "monthly")
        email = body.get("email", "").strip().lower()
        lang = body.get("lang", "en")

        if plan_key not in PLANS:
            return JSONResponse({"error": "Invalid plan"}, status_code=400)

        if not email or "@" not in email:
            return JSONResponse({"error": "Invalid email"}, status_code=400)

        stripe = _get_stripe()
        if not stripe.api_key:
            return JSONResponse({"error": "Payment service not configured"}, status_code=503)

        plan = PLANS[plan_key]

        # 获取或创建 Price ID
        price_id = _get_price_id(stripe, plan_key)
        if not price_id:
            return JSONResponse({"error": "Price configuration error"}, status_code=500)

        # 根据语言设置回调 URL
        if lang == "zh":
            success_url = "https://stockqueen.tech/payment-success-zh.html?session_id={CHECKOUT_SESSION_ID}"
            cancel_url = "https://stockqueen.tech/subscribe-zh.html"
        else:
            success_url = "https://stockqueen.tech/payment-success.html?session_id={CHECKOUT_SESSION_ID}"
            cancel_url = "https://stockqueen.tech/subscribe.html"

        # 创建 Checkout Session
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            customer_email=email,
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            subscription_data={
                "trial_period_days": plan["trial_days"],
                "metadata": {
                    "plan": plan_key,
                    "lang": lang,
                },
            },
            metadata={
                "plan": plan_key,
                "lang": lang,
            },
            success_url=success_url,
            cancel_url=cancel_url,
            allow_promotion_codes=True,
        )

        logger.info(f"[STRIPE] Checkout session created: {session.id} ({plan_key}, {email})")
        return JSONResponse({"url": session.url, "session_id": session.id})

    except Exception as e:
        logger.error(f"[STRIPE] Create checkout error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


def _get_price_id(stripe, plan_key: str) -> Optional[str]:
    """获取 Stripe Price ID — 先查环境变量，没有则自动创建"""
    env_map = {
        "monthly": "STRIPE_PRICE_MONTHLY",
        "quarterly": "STRIPE_PRICE_QUARTERLY",
        "yearly": "STRIPE_PRICE_YEARLY",
    }

    # 优先使用环境变量中配置的 Price ID
    price_id = os.getenv(env_map.get(plan_key, ""), "")
    if price_id:
        return price_id

    # 自动创建 Product + Price（仅开发/首次部署时使用）
    plan = PLANS[plan_key]
    try:
        # 查找或创建 Product
        product_id = os.getenv("STRIPE_PRODUCT_ID", "")
        if not product_id:
            product = stripe.Product.create(
                name="StockQueen Pro",
                description="Full access to StockQueen quantitative trading signals, including entry/exit prices, stop-loss, take-profit, and weekly strategy reports.",
                metadata={"app": "stockqueen"},
            )
            product_id = product.id
            logger.info(f"[STRIPE] Created product: {product_id}")

        # 创建 Price
        price_params = {
            "product": product_id,
            "currency": "usd",
            "unit_amount": plan["amount"],
            "recurring": {
                "interval": plan["interval"],
                "interval_count": plan["interval_count"],
            },
            "metadata": {"plan": plan_key},
        }
        price = stripe.Price.create(**price_params)
        logger.info(f"[STRIPE] Created price: {price.id} for {plan_key} (${plan['amount']/100})")
        return price.id

    except Exception as e:
        logger.error(f"[STRIPE] Price creation failed: {e}")
        return None


# ==================================================================
# Webhook 处理
# ==================================================================

@router.post("/api/payments/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe Webhook 处理器
    处理事件:
    - checkout.session.completed → 激活订阅
    - customer.subscription.updated → 更新状态
    - customer.subscription.deleted → 取消订阅
    - invoice.payment_failed → 支付失败通知
    """
    stripe = _get_stripe()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        else:
            # 开发环境：不验证签名
            import json
            event = stripe.Event.construct_from(
                json.loads(payload), stripe.api_key
            )

        event_type = event["type"]
        data = event["data"]["object"]
        logger.info(f"[STRIPE WEBHOOK] {event_type}")

        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(stripe, data)

        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(stripe, data)

        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(stripe, data)

        elif event_type == "invoice.payment_failed":
            await _handle_payment_failed(stripe, data)

        return JSONResponse({"received": True})

    except stripe.error.SignatureVerificationError:
        logger.error("[STRIPE WEBHOOK] Invalid signature")
        return JSONResponse({"error": "Invalid signature"}, status_code=400)
    except Exception as e:
        logger.error(f"[STRIPE WEBHOOK] Error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


async def _handle_checkout_completed(stripe, session):
    """Checkout 完成 → 升级用户到 paid"""
    email = session.get("customer_email", "")
    subscription_id = session.get("subscription", "")
    metadata = session.get("metadata", {})
    plan = metadata.get("plan", "monthly")
    lang = metadata.get("lang", "en")

    logger.info(f"[STRIPE] ✅ Checkout completed: {email} → {plan} (sub: {subscription_id})")

    # 更新 Resend Audience 中的用户标记为 paid
    try:
        import resend
        resend.api_key = os.getenv("RESEND_API_KEY", "")
        audience_id = os.getenv("RESEND_AUDIENCE_ID", "")
        if audience_id and email:
            # 更新 last_name 为 "paid" 标记（first_name 已用于语言）
            contacts_resp = resend.Contacts.list(audience_id=audience_id)
            contacts = contacts_resp.get("data", []) if isinstance(contacts_resp, dict) else contacts_resp
            for c in contacts:
                c_email = c.get("email", "") if isinstance(c, dict) else getattr(c, "email", "")
                c_id = c.get("id", "") if isinstance(c, dict) else getattr(c, "id", "")
                if c_email.lower() == email.lower() and c_id:
                    resend.Contacts.update({
                        "audience_id": audience_id,
                        "id": c_id,
                        "last_name": f"paid:{plan}:{subscription_id}",
                    })
                    logger.info(f"[STRIPE] Updated Resend contact: {email} → paid:{plan}")
                    break
            else:
                # 用户不在列表中，创建
                resend.Contacts.create({
                    "audience_id": audience_id,
                    "email": email,
                    "first_name": lang,
                    "last_name": f"paid:{plan}:{subscription_id}",
                    "unsubscribed": False,
                })
                logger.info(f"[STRIPE] Created paid contact: {email}")
    except Exception as e:
        logger.error(f"[STRIPE] Resend update failed: {e}")

    # 发送确认邮件
    try:
        import resend
        resend.api_key = os.getenv("RESEND_API_KEY", "")
        from_email = os.getenv("NEWSLETTER_FROM", "StockQueen <newsletter@stockqueen.tech>")

        if lang == "zh":
            subject = "🎉 欢迎成为 StockQueen 高级会员！"
            html = _payment_success_email_zh(email, plan)
        else:
            subject = "🎉 Welcome to StockQueen Premium!"
            html = _payment_success_email_en(email, plan)

        resend.Emails.send({
            "from": from_email,
            "to": [email],
            "subject": subject,
            "html": html,
        })
        logger.info(f"[STRIPE] Confirmation email sent: {email}")
    except Exception as e:
        logger.error(f"[STRIPE] Confirmation email failed: {e}")

    # 通知管理员
    try:
        import resend
        resend.api_key = os.getenv("RESEND_API_KEY", "")
        from_email = os.getenv("NEWSLETTER_FROM", "StockQueen <newsletter@stockqueen.tech>")
        admin_email = os.getenv("ADMIN_NOTIFY_EMAIL", "bigbigraydeng@gmail.com")
        resend.Emails.send({
            "from": from_email,
            "to": [admin_email],
            "subject": f"💰 New Paid Subscriber: {email} ({plan})",
            "html": f"<h2>New Payment!</h2><p>Email: {email}<br>Plan: {plan}<br>Subscription: {subscription_id}</p>",
        })
    except Exception:
        pass


async def _handle_subscription_updated(stripe, subscription):
    """订阅状态更新"""
    status = subscription.get("status", "")
    customer = subscription.get("customer", "")
    logger.info(f"[STRIPE] Subscription updated: customer={customer}, status={status}")


async def _handle_subscription_deleted(stripe, subscription):
    """订阅取消/过期 → 降级为 free"""
    customer_id = subscription.get("customer", "")
    logger.info(f"[STRIPE] Subscription cancelled: customer={customer_id}")

    # 获取客户邮箱
    try:
        customer = stripe.Customer.retrieve(customer_id)
        email = customer.get("email", "")
        if email:
            # 更新 Resend 标记为 free
            import resend
            resend.api_key = os.getenv("RESEND_API_KEY", "")
            audience_id = os.getenv("RESEND_AUDIENCE_ID", "")
            if audience_id:
                contacts_resp = resend.Contacts.list(audience_id=audience_id)
                contacts = contacts_resp.get("data", []) if isinstance(contacts_resp, dict) else contacts_resp
                for c in contacts:
                    c_email = c.get("email", "") if isinstance(c, dict) else getattr(c, "email", "")
                    c_id = c.get("id", "") if isinstance(c, dict) else getattr(c, "id", "")
                    if c_email.lower() == email.lower() and c_id:
                        resend.Contacts.update({
                            "audience_id": audience_id,
                            "id": c_id,
                            "last_name": "free",
                        })
                        logger.info(f"[STRIPE] Downgraded to free: {email}")
                        break
    except Exception as e:
        logger.error(f"[STRIPE] Downgrade failed: {e}")


async def _handle_payment_failed(stripe, invoice):
    """支付失败通知"""
    customer_id = invoice.get("customer", "")
    attempt_count = invoice.get("attempt_count", 0)
    logger.warning(f"[STRIPE] Payment failed: customer={customer_id}, attempt={attempt_count}")


# ==================================================================
# 查询订阅状态
# ==================================================================

@router.get("/api/payments/status", response_class=JSONResponse)
async def get_subscription_status(request: Request):
    """
    查询用户订阅状态
    Query: ?email=xxx
    返回: { "plan": "free"|"monthly"|"quarterly"|"yearly", "status": "active"|"trialing"|"past_due"|"cancelled" }
    """
    email = request.query_params.get("email", "").strip().lower()
    if not email:
        return JSONResponse({"error": "Email required"}, status_code=400)

    try:
        stripe = _get_stripe()
        if not stripe.api_key:
            return JSONResponse({"plan": "free", "status": "unknown", "reason": "stripe_not_configured"})

        # 查找客户
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return JSONResponse({"plan": "free", "status": "no_account"})

        customer = customers.data[0]

        # 查找活跃订阅
        subscriptions = stripe.Subscription.list(
            customer=customer.id,
            status="all",
            limit=5,
        )

        active_sub = None
        for sub in subscriptions.data:
            if sub.status in ("active", "trialing"):
                active_sub = sub
                break

        if not active_sub:
            # 检查是否有过期/取消的
            for sub in subscriptions.data:
                if sub.status in ("past_due", "unpaid"):
                    return JSONResponse({
                        "plan": sub.metadata.get("plan", "unknown"),
                        "status": sub.status,
                    })
            return JSONResponse({"plan": "free", "status": "cancelled"})

        return JSONResponse({
            "plan": active_sub.metadata.get("plan", "monthly"),
            "status": active_sub.status,
            "current_period_end": active_sub.current_period_end,
            "cancel_at_period_end": active_sub.cancel_at_period_end,
        })

    except Exception as e:
        logger.error(f"[STRIPE] Status check error: {e}")
        return JSONResponse({"plan": "free", "status": "error", "error": str(e)})


# ==================================================================
# Customer Portal（管理订阅/取消/更改支付方式）
# ==================================================================

@router.post("/api/payments/portal", response_class=JSONResponse)
async def create_customer_portal(request: Request):
    """
    创建 Stripe Customer Portal Session
    允许用户管理订阅（取消、更改计划、更改支付方式）
    Body: { "email": "..." }
    """
    try:
        body = await request.json()
        email = body.get("email", "").strip().lower()
        if not email:
            return JSONResponse({"error": "Email required"}, status_code=400)

        stripe = _get_stripe()
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return JSONResponse({"error": "No subscription found"}, status_code=404)

        session = stripe.billing_portal.Session.create(
            customer=customers.data[0].id,
            return_url="https://stockqueen.tech/",
        )

        return JSONResponse({"url": session.url})

    except Exception as e:
        logger.error(f"[STRIPE] Portal error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ==================================================================
# 健康检查
# ==================================================================

@router.get("/api/payments/health", response_class=JSONResponse)
async def payments_health(request: Request):
    """支付系统健康检查"""
    checks = {
        "stripe_key_set": bool(os.getenv("STRIPE_SECRET_KEY", "")),
        "stripe_key_prefix": os.getenv("STRIPE_SECRET_KEY", "")[:12] + "..." if os.getenv("STRIPE_SECRET_KEY", "") else "",
        "stripe_publishable_key_set": bool(os.getenv("STRIPE_PUBLISHABLE_KEY", "")),
        "webhook_secret_set": bool(os.getenv("STRIPE_WEBHOOK_SECRET", "")),
        "price_monthly": os.getenv("STRIPE_PRICE_MONTHLY", "(auto-create)"),
        "price_quarterly": os.getenv("STRIPE_PRICE_QUARTERLY", "(auto-create)"),
        "price_yearly": os.getenv("STRIPE_PRICE_YEARLY", "(auto-create)"),
    }

    try:
        stripe = _get_stripe()
        if stripe.api_key:
            # 验证 API key
            stripe.Product.list(limit=1)
            checks["stripe_api_valid"] = True
    except Exception as e:
        checks["stripe_api_valid"] = False
        checks["stripe_api_error"] = str(e)

    return JSONResponse(checks)


# ==================================================================
# 付费确认邮件模板
# ==================================================================

def _payment_success_email_en(email: str, plan: str) -> str:
    plan_display = {"monthly": "$49/month", "quarterly": "$129/quarter", "yearly": "$399/year"}.get(plan, plan)
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="color-scheme" content="light only"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #eef2f7;">
    <table width="100%" cellpadding="0" cellspacing="0" bgcolor="#eef2f7"><tr><td align="center" style="padding: 24px;">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; width: 100%;">
        <tr><td bgcolor="#1e1b4b" style="background-color: #1e1b4b; padding: 32px 28px; text-align: center; border-radius: 14px 14px 0 0;">
            <h1 style="margin: 0; font-size: 28px;"><span style="color: #a5b4fc;">Stock</span><span style="color: #67e8f9;">Queen</span></h1>
            <p style="margin: 8px 0 0; color: #a5b4fc; font-size: 14px;">Premium Membership Activated</p>
            <span style="display: inline-block; background: linear-gradient(135deg, #fbbf24, #f59e0b); color: #78350f; font-size: 10px; font-weight: 700; padding: 3px 10px; border-radius: 20px; margin-top: 8px;">⭐ PREMIUM</span>
        </td></tr>
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 32px 28px;">
            <h2 style="color: #0f172a; margin: 0 0 16px; font-size: 22px;">Welcome to Premium! 🎉</h2>
            <p style="color: #334155; font-size: 14px; line-height: 1.8; margin: 0 0 20px;">
                Your <strong>{plan_display}</strong> subscription is now active with a <strong>7-day free trial</strong>.
                You now have full access to all StockQueen trading signals.
            </p>
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px;">
                <tr><td bgcolor="#f0fdf4" style="background-color: #f0fdf4; padding: 20px; border-radius: 12px; border: 1px solid #bbf7d0;">
                    <p style="color: #14532d; font-size: 14px; margin: 0; line-height: 1.8;">
                        <strong>Your Premium Benefits:</strong><br>
                        ✅ Full buy/sell signals with entry prices<br>
                        ✅ Stop-loss & take-profit levels<br>
                        ✅ Complete position details<br>
                        ✅ Real-time market regime alerts<br>
                        ✅ Priority support
                    </p>
                </td></tr>
            </table>
            <table cellpadding="0" cellspacing="0" style="margin: 0 auto;"><tr>
                <td bgcolor="#4f46e5" style="background-color: #4f46e5; border-radius: 10px;">
                    <a href="https://stockqueen.tech/weekly-report/" style="display: inline-block; color: #ffffff; padding: 14px 36px; text-decoration: none; font-weight: 700; font-size: 15px;">View Latest Report →</a>
                </td>
            </tr></table>
        </td></tr>
        <tr><td bgcolor="#0f172a" style="background-color: #0f172a; padding: 20px 28px; text-align: center; border-radius: 0 0 14px 14px;">
            <p style="color: #475569; font-size: 11px; margin: 0;">StockQueen Quant Research | Rayde Capital</p>
            <p style="margin: 4px 0 0; font-size: 11px;"><a href="https://stockqueen.tech" style="color: #818cf8; text-decoration: none;">stockqueen.tech</a></p>
        </td></tr>
    </table>
    </td></tr></table>
</body></html>"""


def _payment_success_email_zh(email: str, plan: str) -> str:
    plan_display = {"monthly": "$49/月", "quarterly": "$129/季", "yearly": "$399/年"}.get(plan, plan)
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="color-scheme" content="light only"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #eef2f7;">
    <table width="100%" cellpadding="0" cellspacing="0" bgcolor="#eef2f7"><tr><td align="center" style="padding: 24px;">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; width: 100%;">
        <tr><td bgcolor="#1e1b4b" style="background-color: #1e1b4b; padding: 32px 28px; text-align: center; border-radius: 14px 14px 0 0;">
            <h1 style="margin: 0; font-size: 28px;"><span style="color: #a5b4fc;">Stock</span><span style="color: #67e8f9;">Queen</span></h1>
            <p style="margin: 8px 0 0; color: #a5b4fc; font-size: 14px;">高级会员已激活</p>
            <span style="display: inline-block; background: linear-gradient(135deg, #fbbf24, #f59e0b); color: #78350f; font-size: 10px; font-weight: 700; padding: 3px 10px; border-radius: 20px; margin-top: 8px;">⭐ 高级会员</span>
        </td></tr>
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 32px 28px;">
            <h2 style="color: #0f172a; margin: 0 0 16px; font-size: 22px;">欢迎成为高级会员！🎉</h2>
            <p style="color: #334155; font-size: 14px; line-height: 1.8; margin: 0 0 20px;">
                您的 <strong>{plan_display}</strong> 订阅已激活，享有 <strong>7天免费试用</strong>。
                您现在可以查看 StockQueen 的全部交易信号。
            </p>
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px;">
                <tr><td bgcolor="#f0fdf4" style="background-color: #f0fdf4; padding: 20px; border-radius: 12px; border: 1px solid #bbf7d0;">
                    <p style="color: #14532d; font-size: 14px; margin: 0; line-height: 1.8;">
                        <strong>您的高级权益：</strong><br>
                        ✅ 完整买卖信号及进仓价格<br>
                        ✅ 止损位和止盈位<br>
                        ✅ 完整持仓明细<br>
                        ✅ 实时市场状态提醒<br>
                        ✅ 优先客服支持
                    </p>
                </td></tr>
            </table>
            <table cellpadding="0" cellspacing="0" style="margin: 0 auto;"><tr>
                <td bgcolor="#4f46e5" style="background-color: #4f46e5; border-radius: 10px;">
                    <a href="https://stockqueen.tech/weekly-report/index-zh.html" style="display: inline-block; color: #ffffff; padding: 14px 36px; text-decoration: none; font-weight: 700; font-size: 15px;">查看最新报告 →</a>
                </td>
            </tr></table>
        </td></tr>
        <tr><td bgcolor="#0f172a" style="background-color: #0f172a; padding: 20px 28px; text-align: center; border-radius: 0 0 14px 14px;">
            <p style="color: #475569; font-size: 11px; margin: 0;">StockQueen 量化研究团队 | 瑞得资本</p>
            <p style="margin: 4px 0 0; font-size: 11px;"><a href="https://stockqueen.tech/index-zh.html" style="color: #818cf8; text-decoration: none;">stockqueen.tech</a></p>
        </td></tr>
    </table>
    </td></tr></table>
</body></html>"""
