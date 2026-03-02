"""
测试飞书webhook连通性
"""

import requests
import os
from dotenv import load_dotenv

load_dotenv()

url = os.getenv("FEISHU_WEBHOOK_URL")

if not url:
    print("❌ FEISHU_WEBHOOK_URL 未配置")
    print("请在.env文件中设置 FEISHU_WEBHOOK_URL")
    exit(1)

print(f"📡 测试飞书webhook连接: {url}")
print()

payload = {
    "msg_type": "text",
    "content": {
        "text": "StockQueen 连通性测试 ✅"
    }
}

try:
    r = requests.post(url, json=payload, timeout=10)
    print(f"状态码: {r.status_code}")
    print(f"响应: {r.text}")
    
    if r.status_code == 200:
        print("\n✅ 飞书webhook连接成功！")
        print("请检查飞书群是否收到测试消息。")
    else:
        print(f"\n❌ 飞书webhook返回错误状态码: {r.status_code}")
        
except Exception as e:
    print(f"❌ 连接失败: {e}")
