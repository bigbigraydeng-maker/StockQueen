---
name: AI 组件与自学习系统
description: DeepSeek分类/OpenAI Embedding/Claude内容生成/RAG知识库/飞书聊天AI + 未来AI规划
type: reference
created: 2026-03-19
tags:
  - strategy
  - AI
  - deepseek
  - openai
  - claude
  - RAG
  - embedding
  - knowledge-base
---

# AI 组件与自学习系统

## 概览

StockQueen 的 AI 层目前以 **LLM API 调用** 为核心，尚无自训练模型（无 TensorFlow/PyTorch）。AI 服务于三大功能域：

```
AI 架构
├── 🔍 新闻事件分类 (DeepSeek) → 事件驱动策略入口
├── 📊 知识库 RAG (OpenAI Embedding + pgvector) → 情绪因子 + 基本面数据
├── 💬 飞书聊天机器人 (DeepSeek) → 实时问答
└── 📰 Newsletter 生成 (Claude + DeepSeek 备选)
```

---

## 1. 新闻事件 AI 分类

### DeepSeek API 集成
- **文件**: `app/services/ai_service.py:19-216`
- **模型**: DeepSeek Chat
- **温度**: 0.1（低温 → 一致性结果）
- **最大 Token**: 150

### 分类类型
```
Phase3_Positive  → 三期临床阳性
Phase3_Negative  → 三期临床阴性
FDA_Approval     → FDA 批准
CRL              → FDA 拒绝信
Breakthrough     → 突破性疗法认定
```

### 输出
```json
{
  "is_valid_event": true,
  "event_type": "FDA_Approval",
  "direction_bias": "bullish"
}
```

### 用途
- 触发 [[06-Multi-Strategy-Matrix|事件驱动策略]] 的入场信号
- 分类结果写入知识库供 RAG 检索

---

## 2. RAG 知识库系统

### 2.1 Embedding 服务
- **文件**: `app/services/embedding_service.py`
- **模型**: OpenAI `text-embedding-3-small`
- **维度**: 1536
- **批量处理**: 每次 20 条，指数退避重试
- **文本截断**: 8000 字符上限

### 2.2 知识库写入
- **文件**: `app/services/knowledge_service.py:35-196`
- **分块策略**:
  - 阈值: 1000 字符
  - 块大小: 600 字符
  - 重叠: 100 字符
  - 智能分割: 段落 > 句子 > 空格 > 硬切割

### 2.3 语义搜索
- **文件**: `app/services/knowledge_service.py:200-294`
- **实现**: Supabase pgvector RPC 向量相似度搜索
- **去重**: 同一父文档只保留最高分的 chunk

### 2.4 RAG 评分聚合
- **文件**: `app/services/knowledge_service.py:362-417`
- **多因子聚合权重**:

| 来源 | 权重 | 说明 |
|------|------|------|
| AI 情绪 | 25% | 新闻情绪分析结果 |
| 基本面质量 | 25% | 知识库中的基本面数据 |
| 盈利质量 | 20% | EPS surprise/beat 率 |
| 现金流健康 | 15% | FCF 相关数据 |
| 关键词备选 | 15% | 无结构化数据时的文本匹配 |

- **输出范围**: [-3.0, +3.0]

---

## 3. 飞书聊天 AI

### AIChatService
- **文件**: `app/services/ai_service.py:314-507`
- **模型**: DeepSeek Chat
- **温度**: 0.7（较高 → 更有创意的回答）
- **最大 Token**: 1000

### 功能
- 实时股票数据增强（自动注入当前价格/持仓）
- RAG 上下文集成（从知识库检索相关信息）
- 对话历史管理（内存存储，每用户最多 10 条）
- System prompt 包含：市场数据、实时价格、知识库上下文

---

## 4. Newsletter AI 内容生成

### 双 AI 后端（failover）
- **文件**: `scripts/newsletter/ai_content_generator.py`

| 优先级 | AI | 模型 | 温度 | Token |
|--------|-----|------|------|-------|
| 1 | Anthropic Claude | claude-opus-4-5 | — | 4096 |
| 2 (备选) | DeepSeek | deepseek-chat | 0.7 | 4096 |

### 生成内容
```json
{
  "strategy_pulse": "200-350字策略脉搏 + 150-250 words English",
  "quant_insight": "标题 + 600-900字深度分析（双语）",
  "strategy_notes": "模型状态 + 参数（50-100字双语）",
  "free_teaser_insight": "免费版钩子（80-120字双语）"
}
```

---

## 5. XGBoost ML 模型系统（V3A）

### ML Ranker（排名模型）
- **文件**: `models/ml_ranker/ml_ranker.pkl` (299KB)
- **类型**: XGBoost `ranking:pairwise`
- **用途**: 规则层 Top-N 之后 ML 重排（攻守结合）
- **特征数**: 23维（动量/技术/Regime编码/攻击信号）
- **重训**: 每月1日 13:00 NZT，滑动18个月窗口
- **状态**: ✅ 生产运行（USE_ML_ENHANCE=True）

### ML Exit Scorer（出场评分器）
- **文件**: `models/exit_scorer/exit_scorer.pkl` (473KB)
- **类型**: XGBoost 二分类（出场概率预测）
- **特征数**: 10维（持仓天数/浮盈/RSI/ATR/Regime等）
- **阈值**: 0.65（WF验证）
- **状态**: ✅ Phase 1 信号采集中（每日09:46 NZT，不执行交易）
- **下一步**: D1 Tranche B 执行层开发后启用自动出场

### 两层排名架构
```
Layer 1: 规则层（防守）→ 9因子评分 → 候选Top-10
Layer 2: ML层（进攻） → XGBRanker重排 → 最终Top-3
```

---

## 6. 知识收集器（数据管线）

### 8 个收集器
- **文件**: `app/services/knowledge_collectors.py`

| 收集器 | 功能 |
|--------|------|
| SignalOutcomeCollector | 跟踪信号 P&L (1d/5d/20d 窗口) |
| NewsOutcomeCollector | 新闻事件后续表现 |
| PatternStatCollector | 技术形态统计 |
| SectorRotationCollector | 板块轮动数据 |
| AISentimentCollector | AI情绪评分（DeepSeek分析） |
| ETFFlowCollector | ETF资金流向追踪 |
| EarningsReportCollector | SEC财报质量分析 |
| InstitutionalHoldingsCollector | 13F机构持仓检查 |

所有数据写入知识库，供 RAG 系统检索使用。

---

## 6. 当前 AI 能力边界

### ✅ 已实现
- LLM API 调用（分类、生成、问答）
- 向量 Embedding + 语义搜索
- RAG 增强的评分调整
- 知识库自动积累

### ✅ 2026-03-20 新增（ML-V3A）
- XGBoost ML Ranker（非对称标签，规则层后重排）
- XGBoost Exit Scorer（出场概率预测）
- 月度自动重训（滑动18个月窗口）

### ❌ 尚未实现
- 无神经网络训练（无 TensorFlow/PyTorch）
- 无强化学习

### 🔮 V5 规划
- **Phase 3.2**: 盘后 AI 事件信号
  - 每日 16:30 ET 自动扫描 AV NEWS_SENTIMENT
  - AI 分类: earnings beat / analyst upgrade / FDA / M&A
  - 匹配持仓或候选池
  - 成本: $0（包含在 AV $49 月费中）

---

## 关键文件

| 文件 | 说明 |
|------|------|
| `app/services/ai_service.py` | DeepSeek 分类 + 飞书 AI 聊天 |
| `app/services/embedding_service.py` | OpenAI Embedding 客户端 |
| `app/services/knowledge_service.py` | RAG 知识库核心（~1000行） |
| `app/services/knowledge_collectors.py` | 4个数据收集器 |
| `scripts/newsletter/ai_content_generator.py` | Newsletter AI 生成 |
| `app/config/settings.py` | API Keys 配置 |
