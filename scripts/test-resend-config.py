#!/usr/bin/env python3
"""
Resend 配置测试脚本
验证 API Key、域名配置和发送功能
"""

import os
import sys

def install_package(package):
    """安装缺失的包"""
    print(f"正在安装 {package}...")
    os.system(f"{sys.executable} -m pip install {package}")

try:
    from dotenv import load_dotenv
except ImportError:
    install_package("python-dotenv")
    from dotenv import load_dotenv

try:
    import resend
except ImportError:
    install_package("resend")
    import resend

# 加载环境变量
load_dotenv()

print("=" * 60)
print("🔍 Resend 配置测试")
print("=" * 60)

# 1. 检查 API Key
api_key = os.getenv("RESEND_API_KEY", "")
print(f"\n1️⃣ API Key: {'✅ 已设置' if api_key else '❌ 未设置'}")
if api_key:
    print(f"   Key 前缀: {api_key[:10]}...")

# 2. 检查发件人邮箱
print("\n2️⃣ 发件人邮箱配置:")
senders = {
    "Newsletter": os.getenv("NEWSLETTER_FROM", ""),
    "Contact": os.getenv("CONTACT_FROM", ""),
    "Noreply": os.getenv("NOREPLY_FROM", ""),
    "Default": os.getenv("DEFAULT_FROM", "onboarding@resend.dev")
}
for name, email in senders.items():
    status = "✅" if email else "⚠️"
    print(f"   {status} {name}: {email or '未设置'}")

# 3. 检查收件人邮箱
print("\n3️⃣ 收件人邮箱配置:")
recipients = {
    "Contact": os.getenv("CONTACT_TO", ""),
    "Newsletter Admin": os.getenv("NEWSLETTER_ADMIN", ""),
    "Support": os.getenv("SUPPORT_TO", ""),
    "Default": os.getenv("DEFAULT_TO", "")
}
for name, email in recipients.items():
    status = "✅" if email else "⚠️"
    print(f"   {status} {name}: {email or '未设置'}")

# 4. 测试 API 连接
print("\n4️⃣ API 连接测试:")
if api_key:
    resend.api_key = api_key
    try:
        # 尝试获取域名列表来验证 API Key
        domains = resend.Domains.list()
        print("   ✅ API 连接成功")
        print(f"   📋 已验证域名数量: {len(domains.get('data', []))}")
        for domain in domains.get('data', []):
            print(f"      - {domain.get('name')} ({domain.get('status')})")
    except Exception as e:
        print(f"   ❌ API 连接失败: {e}")
else:
    print("   ⚠️ 无法测试，API Key 未设置")

# 5. 发送测试邮件
print("\n5️⃣ 发送测试邮件:")
test_email = os.getenv("TO_EMAIL") or os.getenv("DEFAULT_TO")
if api_key and test_email:
    try:
        params = {
            "from": os.getenv("DEFAULT_FROM", "onboarding@resend.dev"),
            "to": [test_email],
            "subject": "StockQueen Resend 配置测试",
            "html": """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Resend 配置测试</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 28px;">StockQueen</h1>
        <p style="color: #94a3b8; margin: 8px 0 0 0; font-size: 14px;">Resend 配置测试</p>
    </div>
    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
        <h2 style="color: #0f172a; font-size: 20px; margin-bottom: 16px;">✅ 配置测试成功！</h2>
        <p style="color: #374151; font-size: 14px; line-height: 1.8;">
            这是一封测试邮件，用于验证 Resend 邮件服务配置是否正确。
        </p>
        <div style="background: #f0fdf4; border-radius: 8px; padding: 16px; margin: 24px 0;">
            <p style="color: #166534; font-size: 14px; margin: 0;">
                <strong>测试时间:</strong> {}<br>
                <strong>发件人:</strong> {}<br>
                <strong>收件人:</strong> {}
            </p>
        </div>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
        <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 0;">
            StockQueen Quantitative Research Team | Rayde Capital<br>
            <a href="https://stockqueen.tech" style="color: #0891b2; text-decoration: none;">stockqueen.tech</a>
        </p>
    </div>
</body>
</html>
            """.format(
                __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                os.getenv("DEFAULT_FROM", "onboarding@resend.dev"),
                test_email
            )
        }
        
        email = resend.Emails.send(params)
        print(f"   ✅ 测试邮件发送成功!")
        print(f"   📧 邮件 ID: {email.get('id')}")
        print(f"   📮 收件人: {test_email}")
    except Exception as e:
        print(f"   ❌ 发送失败: {e}")
else:
    print("   ⚠️ 跳过测试（API Key 或收件人未设置）")

print("\n" + "=" * 60)
print("🎉 测试完成！")
print("=" * 60)
