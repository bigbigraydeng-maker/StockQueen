---
name: Project C2 - After-Hours AI Event Signals
description: 每日盘后 AI 新闻事件扫描与飞书推送
created: 2026-03-19
updated: 2026-03-19
tags: [project, ai, events, news, feishu, scheduler]
status: completed
---

# 📰 Project C2：盘后 AI 事件信号

## ✅ 已完成（2026-03-19）

---

## 实现架构

```
每天 NZT 09:55（美股收盘后55分钟）自动运行：

scheduler.py
  └── _run_event_signal_scan()
        └── NewsEventScanner.run_daily_scan()
              ├── _get_scan_universe()          # Tiger持仓 + 轮动候选池 top40
              ├── _fetch_and_classify()         # AV NEWS_SENTIMENT + DeepSeek分类
              │     └── DeepSeekStockClassifier.classify()
              │           └── _keyword_classify()  # 关键词兜底（零API成本）
              ├── _save_events()               # 写入 event_signals 表
              └── _send_feishu_summary()        # 飞书推送
```

---

## 新增文件

| 文件 | 说明 |
|------|------|
| `app/services/news_scanner_service.py` | 扫描主服务（新建） |
| `database/create_event_signals.sql` | DB 迁移 SQL |

---

## 修改文件

| 文件 | 修改内容 |
|------|---------|
| `app/services/ai_service.py` | 新增 `DeepSeekStockClassifier`（通用股票事件分类） |
| `app/scheduler.py` | 新增 Job 5b（NZT 09:55 Tue-Sat） |
| `app/routers/web.py` | 新增 `POST /api/admin/run-event-scan` |

---

## 数据库表

**`event_signals`**（已通过 Supabase MCP 创建）：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| date | DATE | 信号日期 |
| ticker | TEXT | 股票代码 |
| event_type | TEXT | 事件类型（见下） |
| direction | TEXT | bullish/bearish/neutral |
| headline | TEXT | 新闻标题（前200字符） |
| summary | TEXT | 摘要（前400字符） |
| signal_strength | FLOAT | 综合信号强度（relevance × sentiment） |
| relevance_score | FLOAT | AV 相关性评分 |
| sentiment_score | FLOAT | AV 情绪评分 |
| source | TEXT | 新闻来源 |
| url | TEXT UNIQUE | 去重键 |
| published | TEXT | 发布时间 |
| created_at | TIMESTAMPTZ | 入库时间 |

---

## 事件类型枚举

| event_type | 说明 | emoji |
|------------|------|-------|
| earnings_beat | 财报超预期 | ✅ |
| earnings_miss | 财报不及预期 | ❌ |
| analyst_upgrade | 分析师升级 | 📈 |
| analyst_downgrade | 分析师降级 | 📉 |
| guidance_raise | 业绩指引上调 | 🚀 |
| guidance_cut | 业绩指引下调 | ⚠️ |
| fda_approval | FDA 批准 | 💊 |
| fda_rejection | FDA 拒绝 | 🚫 |
| ma_activity | 并购传言 | 🤝 |
| management_change | 管理层变动 | 👤 |
| buyback | 股票回购 | 💰 |
| macro_risk | 宏观风险 | 🌍 |
| other_positive | 其他利多 | 🟢 |
| other_negative | 其他利空 | 🔴 |
| noise | 噪音 | ⚪（过滤不推送） |

---

## 手动触发

```bash
curl -X POST https://api.stockqueen.tech/api/admin/run-event-scan \
  -H "X-Admin-Token: <ADMIN_TOKEN>"
```

---

## 参数配置（news_scanner_service.py）

| 参数 | 值 | 说明 |
|------|-----|------|
| MIN_SIGNAL_STRENGTH | 0.30 | 低于此值不推送 |
| MIN_RELEVANCE_SCORE | 0.30 | AV relevance 门槛 |
| MAX_EVENTS_PER_PUSH | 12 | 每次飞书最多推送条数 |
| LOOKBACK_HOURS | 26 | 只看最近26小时新闻 |
| Max tickers | 60 | 每天最多扫描 60 只 |

---

## 归档说明

- ✅ `event_signals` 表已在 Supabase 创建
- ✅ [[Backend-Services]] 中已添加 `news_scanner_service`
- ✅ [[Scheduler-Jobs]] 中已添加 Job 5b
- ✅ [[Projects/00-Active-Projects]] 状态已更新

---

## 📎 相关文档

- [[Projects/C3-Newsletter-Product]] — 信号内容的下游消费者
- [[Projects/00-Active-Projects]] — 返回项目总览
