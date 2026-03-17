#!/usr/bin/env python3
"""
StockQueen Stripe 初始化脚本
自动在 Stripe 账号中创建产品和价格，并输出需要配置的环境变量

使用方法：
  1. 先确保 .env 中有 STRIPE_SECRET_KEY（从 Stripe Dashboard 获取）
  2. 运行: python scripts/stripe_setup.py
  3. 脚本会输出 STRIPE_PRICE_MONTHLY 等环境变量值
  4. 复制到 Render 后台的 Environment Variables 中

注意: 建议先在 Stripe Test Mode 运行（key 以 sk_test_ 开头）
"""

import asyncio
import os
import sys
from pathlib import Path

# 加载 .env
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

import stripe


def setup_stripe_products():
    """
    在 Stripe 中创建 StockQueen Premium 产品和3种订阅价格
    返回价格 ID 字典
    """
    api_key = os.getenv("STRIPE_SECRET_KEY", "")
    if not api_key:
        print("❌ 错误: 未找到 STRIPE_SECRET_KEY 环境变量")
        print("   请先在 .env 文件中设置: STRIPE_SECRET_KEY=sk_test_...")
        sys.exit(1)

    stripe.api_key = api_key

    is_test = api_key.startswith("sk_test_")
    mode_label = "TEST MODE ⚠️" if is_test else "LIVE MODE 🔴"
    print(f"\n{'='*60}")
    print(f"StockQueen Stripe 初始化 — {mode_label}")
    print(f"{'='*60}\n")

    if not is_test:
        confirm = input("⚠️  这是 LIVE 模式，将创建真实计费产品。继续？(yes/no): ")
        if confirm.lower() != "yes":
            print("已取消。建议先在 Test Mode 运行。")
            sys.exit(0)

    # ──────────────────────────────────────
    # 1. 创建产品
    # ──────────────────────────────────────
    print("Step 1: 创建产品...")

    # 检查是否已有同名产品
    existing_products = stripe.Product.list(limit=100)
    sq_product = None
    for p in existing_products.data:
        if p.name == "StockQueen Premium" and p.active:
            sq_product = p
            print(f"  ✅ 已存在产品: {p.name} (id: {p.id})")
            break

    if not sq_product:
        sq_product = stripe.Product.create(
            name="StockQueen Premium",
            description="AI-powered quantitative trading newsletter. Weekly signals with entry prices, stop-loss, and take-profit levels.",
            metadata={
                "product": "newsletter_premium",
                "website": "https://stockqueen.tech",
            }
        )
        print(f"  ✅ 创建产品: {sq_product.name} (id: {sq_product.id})")

    product_id = sq_product.id

    # ──────────────────────────────────────
    # 2. 创建3种价格
    # ──────────────────────────────────────
    print("\nStep 2: 创建订阅价格（7天免费试用）...")

    plans = [
        {
            "key": "monthly",
            "nickname": "Monthly - $49",
            "amount": 4900,
            "interval": "month",
            "interval_count": 1,
            "env_var": "STRIPE_PRICE_MONTHLY",
        },
        {
            "key": "quarterly",
            "nickname": "Quarterly - $129",
            "amount": 12900,
            "interval": "month",
            "interval_count": 3,
            "env_var": "STRIPE_PRICE_QUARTERLY",
        },
        {
            "key": "yearly",
            "nickname": "Yearly - $399",
            "amount": 39900,
            "interval": "year",
            "interval_count": 1,
            "env_var": "STRIPE_PRICE_YEARLY",
        },
    ]

    price_ids = {}

    for plan in plans:
        # 检查是否已存在相同价格
        existing_prices = stripe.Price.list(product=product_id, active=True, limit=100)
        found_price = None
        for ep in existing_prices.data:
            if (ep.unit_amount == plan["amount"] and
                ep.recurring and
                ep.recurring.interval == plan["interval"] and
                ep.recurring.interval_count == plan["interval_count"]):
                found_price = ep
                print(f"  ✅ 已存在价格: {plan['nickname']} (id: {ep.id})")
                break

        if not found_price:
            found_price = stripe.Price.create(
                product=product_id,
                unit_amount=plan["amount"],
                currency="usd",
                recurring={
                    "interval": plan["interval"],
                    "interval_count": plan["interval_count"],
                    "trial_period_days": 7,
                },
                nickname=plan["nickname"],
                metadata={"plan": plan["key"]},
            )
            print(f"  ✅ 创建价格: {plan['nickname']} (id: {found_price.id})")

        price_ids[plan["key"]] = found_price.id

    # ──────────────────────────────────────
    # 3. 配置 Customer Portal（可选）
    # ──────────────────────────────────────
    print("\nStep 3: 配置 Customer Portal...")
    try:
        stripe.billing_portal.Configuration.create(
            business_profile={
                "headline": "StockQueen — 管理您的订阅",
                "privacy_policy_url": "https://stockqueen.tech/privacy",
                "terms_of_service_url": "https://stockqueen.tech/terms",
            },
            features={
                "customer_update": {"allowed_updates": ["email"], "enabled": True},
                "invoice_history": {"enabled": True},
                "payment_method_update": {"enabled": True},
                "subscription_cancel": {
                    "enabled": True,
                    "mode": "at_period_end",
                    "proration_behavior": "none",
                },
                "subscription_pause": {"enabled": False},
            },
        )
        print("  ✅ Customer Portal 已配置")
    except stripe.error.InvalidRequestError as e:
        if "already exists" in str(e) or "default" in str(e).lower():
            print("  ✅ Customer Portal 已存在")
        else:
            print(f"  ⚠️  Customer Portal 配置失败（可手动在 Dashboard 配置）: {e}")

    # ──────────────────────────────────────
    # 4. 输出环境变量
    # ──────────────────────────────────────
    print(f"\n{'='*60}")
    print("✅ Stripe 初始化完成！")
    print(f"{'='*60}")
    print("\n请将以下环境变量添加到 Render Dashboard:")
    print("(Settings → Environment → Add environment variable)\n")
    print("─" * 60)

    env_vars = {
        "STRIPE_SECRET_KEY": api_key,
        "STRIPE_PRICE_MONTHLY": price_ids.get("monthly", ""),
        "STRIPE_PRICE_QUARTERLY": price_ids.get("quarterly", ""),
        "STRIPE_PRICE_YEARLY": price_ids.get("yearly", ""),
    }

    for key, val in env_vars.items():
        print(f"  {key}={val}")

    print("─" * 60)
    print("\n⚠️  STRIPE_WEBHOOK_SECRET 需要另外设置（见下方说明）")
    print("\n设置 Webhook:")
    print("  1. 进入 Stripe Dashboard → Developers → Webhooks")
    print("  2. 点击 'Add endpoint'")
    print("  3. URL: https://stockqueen-api.onrender.com/api/payments/webhook")
    print("  4. 选择事件:")
    print("     - checkout.session.completed")
    print("     - customer.subscription.deleted")
    print("     - invoice.payment_failed")
    print("  5. 创建后，复制 'Signing secret'")
    print("  6. 在 Render 添加: STRIPE_WEBHOOK_SECRET=whsec_...")

    # 保存到本地文件（供参考）
    output_file = PROJECT_ROOT / ".stripe_setup_output.txt"
    with open(output_file, "w") as f:
        f.write("# StockQueen Stripe 配置输出\n")
        f.write("# 请勿提交此文件到 Git！\n\n")
        f.write("# Render 环境变量:\n")
        for key, val in env_vars.items():
            f.write(f"{key}={val}\n")
        f.write(f"\n# Product ID: {product_id}\n")
    print(f"\n📄 配置已保存到: {output_file}")
    print("   ⚠️  此文件包含 API Key，请勿提交到 Git！")

    return price_ids


if __name__ == "__main__":
    setup_stripe_products()
