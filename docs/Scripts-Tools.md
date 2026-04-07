---
name: 工具脚本清单
description: 一次性脚本、研究工具、部署工具完整列表
type: reference
created: 2026-03-19
tags: [scripts, tools, one-off, deployment]
---

# 工具脚本清单

## 部署初始化脚本

| 脚本 | 用途 | 运行时机 |
|------|------|---------|
| `scripts/create_admin_users.py` | 创建Supabase管理员 | 首次部署 |
| `scripts/populate_ohlcv_cache.py` | 预加载AV完整历史 | 首次部署/数据重置 |
| `scripts/stripe_setup.py` | 初始化Stripe产品和价格 | 首次部署 |

## 测试/调试脚本

| 脚本 | 用途 | 运行时机 |
|------|------|---------|
| `scripts/send-test-email.py` | 测试Resend邮件（中文） | 配置验证 |
| `scripts/send-test-email-en.py` | 测试Resend邮件（英文） | 配置验证 |
| `scripts/test-resend-config.py` | 验证Resend API配置 | 配置验证 |
| `scripts/test_v5.py` | V5特性安全性测试 | 开发验证 |

## 研究/回测脚本

| 脚本 | 用途 | 运行时机 |
|------|------|---------|
| `scripts/walk_forward_test.py` | Walk-Forward 6窗口参数搜索 | V5研究 |
| `scripts/test_strategy_matrix.py` | 策略矩阵独立回测 | 策略研究 |

## 内容/发布脚本

| 脚本 | 用途 | 运行时机 |
|------|------|---------|
| `scripts/social_publish.py` | 发布社交媒体内容 | 手动周度 |
| `scripts/generate_changelog.py` | 从Git生成更新日志 | 每次发布 |

## Newsletter 脚本 (scripts/newsletter/)

| 文件 | 用途 |
|------|------|
| `generate.py` | 主生成脚本（CLI入口） |
| `__main__.py` | `python -m newsletter` 入口 |
| `ai_content_generator.py` | Claude/DeepSeek AI内容生成 |
| `data_fetcher.py` | 从API获取周度数据 |
| `renderer.py` | Jinja2 HTML/MD渲染 |
| `sender.py` | Resend邮件发送 |
| `social_generator.py` | 社交媒体文案生成 |

> Newsletter 由调度器 Job #18 自动运行（Sat 12:00 NZT），也可手动 `python -m scripts.newsletter`

## SQL 脚本 (database/)

| 文件 | 用途 |
|------|------|
| `create_regime_history.sql` | 创建regime_history表 ✅ 已执行 |
| 其他迁移脚本 | 数据库schema变更 |
