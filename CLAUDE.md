  # StockQueen — Claude 工作指南

  ## 对话启动必做：读取 Obsidian 项目状态

  每次对话开始时，**必须按顺序拉取以下 Obsidian 文件**，以获取最新项目状态，再回答任何问题或开始任何任务：

  ```bash
  # 1. CORE 主索引（唯一入口，所有策略/技术文档的权威版本清单）
  curl -sk -H "Authorization: Bearer 266d6f82c9a9c630dd313b091b772ee13c747b5698fb6c105e559f2109a2819d" \
    "https://127.0.0.1:28000/vault/04-StockQueen/CORE/00-MASTER-INDEX.md"

  # 2. 仪表板（项目整体状态 KPI）
  curl -sk -H "Authorization: Bearer 266d6f82c9a9c630dd313b091b772ee13c747b5698fb6c105e559f2109a2819d" \
    "https://127.0.0.1:28000/vault/04-StockQueen/MOC-StockQueen.md"

  # 3. 活跃项目追踪
  curl -sk -H "Authorization: Bearer 266d6f82c9a9c630dd313b091b772ee13c747b5698fb6c105e559f2109a2819d" \
    "https://127.0.0.1:28000/vault/04-StockQueen/Projects/"
  ```

  读完后，**在回答用户第一条消息之前**，先做一句简短的状态确认（中文），让用户知道你已同步了最新上下文。

  > **重要**: 后续查阅策略细节时，必须从 MASTER-INDEX 表格找到对应 CORE/ 文件再读取，不要读旧目录下的同名文件。

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
  - **日期检查**: 涉及周期性操作（周一重平衡、下周、下月等）时，**必须用代码验证当前日期**，从不假设日期。输出给用户前检查一遍

  ---

  ## Vault 读取规则（强制执行）

  1. **优先级顺序**：`CORE/` > `WORKING/` > 其他目录 > `ARCHIVE/`（禁止读）
  2. **只读 ACTIVE 文件**：如果 frontmatter 中 `status != ACTIVE`，该文件内容不得用于任何决策或推理
  3. **策略查阅入口**：先读 `CORE/00-MASTER-INDEX.md`，按表格找到对应 ACTIVE 文件
  4. **发现冲突必须停止**：
    - 如果两个文件对同一主题有矛盾描述
    - 必须提示用户：「发现冲突：[文件A] 说X，[文件B] 说Y，请确认哪个是权威版本」
    - 不得自行判断、不得取平均、不得"综合两者"
  5. **引用必须注明来源**：每次引用策略逻辑，必须注明：「来源：CORE/Strategy/03 v2.0」
  6. **不读 Sessions/**：Sessions 是操作日志，不是知识文档
  7. **更新 Vault 必须遵守操作协议**：
    - 先扫描 CORE/ 找到相关 ACTIVE 文件
    - 更新主文件 + version + last_updated
    - 标记旧内容 DEPRECATED
    - 输出影响报告（修改了哪些文件、废弃了什么、需要同步什么）

  ---

  ## 参数同步自动化

  当修改以下核心服务文件后，**必须运行** `python scripts/sync_core_params.py` 更新参数快照：

  | 文件 | 对应参数 |
  |------|---------|
  | `app/config/rotation_watchlist.py` | 宝典 RotationConfig 全部参数 |
  | `app/services/multi_factor_scorer.py` | 因子权重（FACTOR_WEIGHTS） |
  | `app/services/portfolio_manager.py` | 资金分配矩阵、VIX 降杠杆 |
  | `app/services/mean_reversion_service.py` | MR 参数 |
  | `app/services/event_driven_service.py` | ED 参数 |

  脚本会自动提取代码中的参数值 → 生成 `scripts/params_snapshot.json` + 写入 Obsidian `CORE/PARAMS-SNAPSHOT.md`。

  ---

  ## Obsidian Local REST API

  - 地址：`https://127.0.0.1:28000`
  - Bearer Token：`266d6f82c9a9c630dd313b091b772ee13c747b5698fb6c105e559f2109a2819d`
  - 文档根目录：`/vault/04-StockQueen/`（Vault = Second-Brain）
  - 写文件用 Python urllib（Windows 下 curl --data-binary 会乱码）

  ---

  ## 安全规范（Fixxxxx 新增）

  ### 强制检查
  - **禁止硬编码** API keys / tokens / passwords — 全部走 `os.environ` 或 `.env`
  - Stripe webhook 必须验证签名（`stripe.Webhook.construct_event`）
  - Tiger API 凭证绝不能出现在日志中
  - Supabase service key 只用于服务端，永远不暴露给前端
  - 所有用户输入（API 参数）必须用 Pydantic 验证

  ### 金融数据安全
  - 交易相关操作必须在数据库事务中完成
  - 价格/收益数据修改必须有审计日志
  - 回测数据和实盘数据必须严格隔离

  ---

  ## 代码风格（Fixxxxx 新增）

  - 不可变优先：用 spread / 新对象替代原地修改
  - 函数 < 50 行，文件 < 800 行
  - `main.py` 已在合理范围内，新功能必须拆到 `services/` 或 `routers/`
  - 错误处理：每层都要捕获，API 层返回结构化错误，不泄露内部信息
  - 禁止 `console.log` / `print` 调试语句进入 main 分支

  ---

  ## Agent 使用指南（Fixxxxx 新增）

  | 场景 | 推荐 Agent |
  |------|-----------|
  | 新功能开发（如新策略） | `/plan` → `planner` |
  | 修改交易逻辑 | `security-reviewer`（必须） |
  | Stripe / 支付相关 | `security-reviewer`（必须） |
  | 构建失败 | `/build-fix` → `build-error-resolver` |
  | 代码提交前 | `/code-review` → `code-reviewer` |
  | CMS 前端修改 | `code-reviewer` |
  | 重构 services | `/refactor-clean` → `refactor-cleaner` |

  ---

  ## 禁止事项

  - 禁止直接操作实盘（Tiger real trading）除非用户三次确认
  - 禁止删除 Supabase 表或 migration — 只能新增
  - 禁止修改 `rotation_watchlist.py` 参数而不运行 `sync_core_params.py`
  - 禁止在非 CORE/ 目录创建策略文档
