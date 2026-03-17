#!/usr/bin/env python3
"""
StockQueen Newsletter 内容生成器 - 主入口

用法:
    # 生成全部内容（4种邮件 + 5种社交媒体）
    python -m scripts.newsletter.generate

    # 只生成邮件，不生成社交媒体
    python -m scripts.newsletter.generate --email-only

    # 发送测试邮件到指定邮箱
    python -m scripts.newsletter.generate --test your@email.com

    # 使用自定义 API 地址
    python -m scripts.newsletter.generate --api-base http://localhost:8001

    # 正式发送到所有订阅者
    python -m scripts.newsletter.generate --send

输出目录:
    output/newsletters/
        free-zh.html, free-en.html, paid-zh.html, paid-en.html
    output/social/
        facebook-zh.txt, facebook-en.txt, twitter-en.txt, linkedin-en.txt, wechat-zh.md
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 Python path 中
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from scripts.newsletter.data_fetcher import DataFetcher
from scripts.newsletter.renderer import NewsletterRenderer
from scripts.newsletter.social_generator import SocialGenerator
from scripts.newsletter.sender import NewsletterSender

# 输出目录
OUTPUT_DIR = PROJECT_ROOT / "output"
NEWSLETTER_DIR = OUTPUT_DIR / "newsletters"
SOCIAL_DIR = OUTPUT_DIR / "social"

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("newsletter")


async def generate(api_base: str = None, email_only: bool = False) -> dict:
    """
    主生成流程
    1. 从 API 获取数据
    2. 渲染4种邮件 HTML
    3. 生成5种社交媒体内容
    4. 保存到 output/ 目录
    返回: {"data": {...}, "newsletters": {...}, "social": {...}}
    """
    logger.info("=" * 60)
    logger.info("StockQueen Newsletter Generator")
    logger.info("=" * 60)

    # 1. 获取数据
    logger.info("📡 正在获取数据...")
    fetcher = DataFetcher(api_base=api_base)
    data = await fetcher.fetch_all()

    logger.info(f"  市场状态: {data['market_regime']}")
    logger.info(f"  当前持仓: {len(data['positions'])} 个")
    logger.info(f"  新买入: {len(data['new_entries'])} | 新卖出: {len(data['new_exits'])}")
    logger.info(f"  本周平仓: {len(data['recent_exits'])} 笔")

    # 2. 渲染邮件
    logger.info("📧 正在渲染邮件模板...")
    renderer = NewsletterRenderer()
    newsletters = renderer.render_all(data)

    # 保存邮件 HTML
    NEWSLETTER_DIR.mkdir(parents=True, exist_ok=True)
    for name, html in newsletters.items():
        filepath = NEWSLETTER_DIR / f"{name}.html"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"  ✅ {filepath.name} ({len(html):,} chars)")

    result = {"data": data, "newsletters": newsletters}

    # 3. 生成社交媒体内容
    if not email_only:
        logger.info("📱 正在生成社交媒体内容...")
        social = SocialGenerator()
        social_content = social.generate_all(data)

        # 保存社交媒体内容
        SOCIAL_DIR.mkdir(parents=True, exist_ok=True)
        ext_map = {"wechat-zh": ".md"}  # 微信用 Markdown
        for name, content in social_content.items():
            ext = ext_map.get(name, ".txt")
            filepath = SOCIAL_DIR / f"{name}{ext}"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"  ✅ {filepath.name} ({len(content):,} chars)")

        result["social"] = social_content

    # 4. 保存数据快照（供调试）
    data_file = OUTPUT_DIR / "last_data.json"
    # 过滤不可序列化的字段
    serializable = {k: v for k, v in data.items() if k not in ("newsletters",)}
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"  📁 数据快照: {data_file}")

    logger.info("=" * 60)
    logger.info("✅ 全部内容生成完成！")
    logger.info(f"  邮件: {NEWSLETTER_DIR}")
    if not email_only:
        logger.info(f"  社交: {SOCIAL_DIR}")
    logger.info("=" * 60)

    return result


async def send_test(to_email: str, api_base: str = None, version: str = "all"):
    """生成并发送测试邮件"""
    result = await generate(api_base=api_base)
    newsletters = result["newsletters"]

    sender = NewsletterSender()
    if not sender.validate_config():
        logger.error("发送配置无效，请检查 RESEND_API_KEY")
        return

    if version == "all":
        versions = newsletters.keys()
    else:
        versions = [version]

    for v in versions:
        if v in newsletters:
            logger.info(f"📧 发送测试邮件: {v} → {to_email}")
            success = sender.send_test(to_email, newsletters[v], version=v)
            if success:
                logger.info(f"  ✅ {v} 发送成功")
            else:
                logger.error(f"  ❌ {v} 发送失败")


async def send_production(api_base: str = None):
    """正式发送 Newsletter 到所有订阅者"""
    result = await generate(api_base=api_base)
    newsletters = result["newsletters"]
    data = result["data"]

    sender = NewsletterSender()
    if not sender.validate_config():
        logger.error("发送配置无效，请检查 RESEND_API_KEY")
        return

    audience_id = os.getenv("RESEND_AUDIENCE_ID", "")
    if not audience_id:
        logger.error("❌ RESEND_AUDIENCE_ID 未设置")
        return

    results = sender.send_all_newsletters(
        newsletters,
        audience_id=audience_id,
        week_number=data["week_number"],
        year=data["year"],
    )

    for version, info in results.items():
        logger.info(f"  {version}: {info}")


def main():
    parser = argparse.ArgumentParser(description="StockQueen Newsletter Generator")
    parser.add_argument("--api-base", type=str, default=None,
                        help="API 基础 URL (默认: STOCKQUEEN_API_BASE 环境变量)")
    parser.add_argument("--email-only", action="store_true",
                        help="只生成邮件，跳过社交媒体内容")
    parser.add_argument("--test", type=str, metavar="EMAIL",
                        help="发送测试邮件到指定地址")
    parser.add_argument("--test-version", type=str, default="all",
                        choices=["all", "free-zh", "free-en", "paid-zh", "paid-en"],
                        help="测试邮件版本 (默认: all)")
    parser.add_argument("--send", action="store_true",
                        help="正式发送到所有订阅者")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="显示详细日志")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.test:
        asyncio.run(send_test(args.test, api_base=args.api_base, version=args.test_version))
    elif args.send:
        asyncio.run(send_production(api_base=args.api_base))
    else:
        asyncio.run(generate(api_base=args.api_base, email_only=args.email_only))


if __name__ == "__main__":
    main()
