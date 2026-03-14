#!/usr/bin/env python3
"""
StockQueen Newsletter 测试邮件发送脚本
使用 Resend API - 最快最简单的方法
"""

import os
import sys

# 安装依赖: pip install resend

try:
    import resend
except ImportError:
    print("正在安装 resend...")
    os.system(f"{sys.executable} -m pip install resend")
    import resend

# ==================== 配置区域 ====================

# 1. 从 https://resend.com 获取 API Key（免费注册，每天100封）
RESEND_API_KEY = "re_xxxxxxxxxxxxxxxxxxxxxxxx"  # 替换为你的 API Key

# 2. 你的邮箱（需要先验证）
FROM_EMAIL = "onboarding@resend.dev"  # 或者用你的域名: "newsletter@stockqueen.io"

# 3. 收件人邮箱
TO_EMAIL = "your-email@example.com"  # 替换为你的邮箱

# 4. 邮件内容
SUBJECT = "StockQueen Weekly Report - Test Email"

HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>StockQueen Weekly Report</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">

    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 28px;">StockQueen</h1>
        <p style="color: #94a3b8; margin: 8px 0 0 0; font-size: 14px;">每周量化策略报告</p>
    </div>

    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
        <p style="color: #64748b; font-size: 12px; margin-bottom: 20px;">2026年3月21日 | 第12周</p>

        <h2 style="color: #0f172a; font-size: 20px; margin-bottom: 16px;">策略表现摘要</h2>

        <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
            <tr>
                <td style="padding: 15px; background: #f0fdf4; border-radius: 8px 0 0 8px; width: 33%; text-align: center;">
                    <p style="color: #64748b; font-size: 12px; margin: 0;">本周收益</p>
                    <p style="color: #059669; font-size: 28px; font-weight: bold; margin: 4px 0 0 0;">+2.8%</p>
                </td>
                <td style="padding: 15px; background: #fef2f2; width: 33%; text-align: center;">
                    <p style="color: #64748b; font-size: 12px; margin: 0;">标普500</p>
                    <p style="color: #dc2626; font-size: 28px; font-weight: bold; margin: 4px 0 0 0;">-1.2%</p>
                </td>
                <td style="padding: 15px; background: #f0fdf4; border-radius: 0 8px 8px 0; width: 33%; text-align: center;">
                    <p style="color: #64748b; font-size: 12px; margin: 0;">超额收益</p>
                    <p style="color: #059669; font-size: 28px; font-weight: bold; margin: 4px 0 0 0;">+4.0%</p>
                </td>
            </tr>
        </table>

        <h2 style="color: #0f172a; font-size: 18px; margin-bottom: 12px;">当前持仓</h2>
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
            <thead>
                <tr style="background: #f1f5f9;">
                    <th style="padding: 12px; text-align: left; font-size: 12px; color: #475569;">标的</th>
                    <th style="padding: 12px; text-align: right; font-size: 12px; color: #475569;">收益</th>
                </tr>
            </thead>
            <tbody>
                <tr style="border-bottom: 1px solid #e2e8f0;">
                    <td style="padding: 12px;">
                        <strong>SH</strong> <span style="color: #64748b; font-size: 12px;">做空标普500</span>
                    </td>
                    <td style="padding: 12px; text-align: right; color: #059669; font-weight: bold;">+4.1%</td>
                </tr>
                <tr style="border-bottom: 1px solid #e2e8f0;">
                    <td style="padding: 12px;">
                        <strong>PSQ</strong> <span style="color: #64748b; font-size: 12px;">做空纳指100</span>
                    </td>
                    <td style="padding: 12px; text-align: right; color: #059669; font-weight: bold;">+3.6%</td>
                </tr>
                <tr>
                    <td style="padding: 12px;">
                        <strong>DOG</strong> <span style="color: #64748b; font-size: 12px;">做空道指</span>
                    </td>
                    <td style="padding: 12px; text-align: right; color: #059669; font-weight: bold;">+2.9%</td>
                </tr>
            </tbody>
        </table>

        <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 16px; border-radius: 0 8px 8px 0; margin-bottom: 24px;">
            <p style="color: #92400e; font-size: 14px; margin: 0;">
                <strong>市场状态：</strong>熊市防御 (BEAR)
            </p>
        </div>

        <div style="text-align: center; margin: 30px 0;">
            <a href="https://stockqueen.io/weekly-report/" 
               style="display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #0891b2 100%); 
                      color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; 
                      font-weight: 600; font-size: 14px;">
                查看完整报告
            </a>
        </div>

        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">

        <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 0;">
            StockQueen 量化研究团队 | 瑞德资本<br>
            <a href="https://stockqueen.io" style="color: #0891b2; text-decoration: none;">stockqueen.io</a>
        </p>
    </div>

</body>
</html>
"""

# ==================== 发送函数 ====================

def send_email():
    """发送测试邮件"""

    if RESEND_API_KEY == "re_xxxxxxxxxxxxxxxxxxxxxxxx":
        print("❌ 错误：请先替换 RESEND_API_KEY")
        print("   1. 访问 https://resend.com 注册账号")
        print("   2. 获取 API Key")
        print("   3. 修改脚本中的 RESEND_API_KEY")
        return False

    if TO_EMAIL == "your-email@example.com":
        print("❌ 错误：请先替换 TO_EMAIL 为你的邮箱地址")
        return False

    try:
        resend.api_key = RESEND_API_KEY

        params = {
            "from": FROM_EMAIL,
            "to": [TO_EMAIL],
            "subject": SUBJECT,
            "html": HTML_CONTENT,
        }

        print(f"正在发送邮件到 {TO_EMAIL}...")
        email = resend.Emails.send(params)

        print(f"✅ 邮件发送成功！")
        print(f"   邮件 ID: {email['id']}")
        print(f"   收件人: {TO_EMAIL}")
        return True

    except Exception as e:
        print(f"❌ 发送失败: {e}")
        print("\n常见问题：")
        print("   - API Key 是否正确？")
        print("   - 发件邮箱是否已验证？")
        print("   - 收件邮箱地址是否正确？")
        return False

if __name__ == "__main__":
    send_email()
