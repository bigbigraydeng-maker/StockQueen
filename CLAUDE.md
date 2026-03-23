# StockQueen — Claude 工作指南

## 对话启动必做：读取 Obsidian 项目状态

每次对话开始时，**必须先拉取以下 Obsidian 文件**，以获取最新项目状态，再回答任何问题或开始任何任务：

```bash
# 仪表板（项目整体状态）
curl -sk -H "Authorization: Bearer 266d6f82c9a9c630dd313b091b772ee13c747b5698fb6c105e559f2109a2819d" \
  "https://127.0.0.1:28000/vault/04-StockQueen/MOC-StockQueen.md"

# 活跃项目追踪
curl -sk -H "Authorization: Bearer 266d6f82c9a9c630dd313b091b772ee13c747b5698fb6c105e559f2109a2819d" \
  "https://127.0.0.1:28000/vault/04-StockQueen/Projects/"
```

读完后，**在回答用户第一条消息之前**，先做一句简短的状态确认（中文），让用户知道你已同步了最新上下文。

---

## 项目命名规范

| 代号 | 含义 |
|------|------|
| **破浪** | 整个 StockQueen V5 系统（产品化工程） |
| **宝典** | `rotation_service` 核心趋势轮动策略（V4/V5） |
| **MR** | `mean_reversion_service` 均值回归策略 |
| **ED** | `event_driven_service` 事件驱动策略 |

代码内部 key 不变，仅对话中使用上述中文代号。

---

## 关键现状（以 Obsidian 为准，此处仅备份）

- **宝典 V5**：TOP_N=3，已推送 main，Render 生产运行
- **Tiger API**：已接入**模拟盘**（paper trading），未切实盘
- **动态选股池**：`USE_DYNAMIC_UNIVERSE=True`，1,688 只动态池已上线
- **Supabase / AV / Render**：均为付费版，不要随意建新项目

---

## 门面更新（"门面" 定义）

当用户说 **"门面更新"** 时，必须更新以下**所有**内容，不得遗漏：

| 分类 | 文件 / 位置 |
|------|------------|
| 融资材料 | `output/StockQueen_DataPack_2026.docx` |
| 融资材料 | `Desktop/stockqueen-pitch-v4-fixed.pptx`（或最新版 pptx） |
| 融资材料 | `output/StockQueen_IM_2026.docx` |
| Obsidian | `/vault/04-StockQueen/` 相关文档（用 API 写入） |
| 官网 EN | `site/index.html` + `site/index-zh.html` |
| 官网 Blog | `site/blog/` 相关文章 |
| 官网数据 | `site/data/backtest-summary.json` |
| 官网数据 | `site/data/walk-forward-validation.json` |
| 后台 Lab | `app/templates/lab.html` |
| 后台配置 | `app/config/luohan.json` |

**执行顺序**：先更新 JSON 数据文件 → 再更新 HTML/模板 → 再更新文档（docx/pptx）→ 最后更新 Obsidian → push to main

**数据一致性原则**：所有材料中的同一指标（Sharpe、CAGR、累计收益等）必须引用相同数据源，中英文版本数字完全一致。

---

## 行为规范

- 所有对话**必须用中文**输出
- 不要 push 到 git，除非用户明确要求
- push 到 main 后必须提供 7 位 commit hash
- worktree 创建后必须 cp .env 到 worktree 目录
- 不要臆测项目状态——以 Obsidian 为唯一事实来源

---

## Obsidian Local REST API

- 地址：`https://127.0.0.1:28000`
- Bearer Token：`266d6f82c9a9c630dd313b091b772ee13c747b5698fb6c105e559f2109a2819d`
- 文档根目录：`/vault/04-StockQueen/`（Vault = Second-Brain）
- 写文件用 Python urllib（Windows 下 curl --data-binary 会乱码）
