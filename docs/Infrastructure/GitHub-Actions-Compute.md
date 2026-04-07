---
created: 2026-03-20
updated: 2026-03-21
tags: [infrastructure, github-actions, compute, walkforward]
---

# GitHub Actions 大算力任务清单

## 工作流文件

| 文件 | 用途 |
|------|------|
| `.github/workflows/walk-forward.yml` | 主计算 workflow，手动触发，选策略 |
| `.github/workflows/upload-cache.yml` | 一次性上传行情 Cache 到 Actions Cache |

## 首次使用步骤

1. **打包本地缓存**（本地运行一次）
   ```bash
   cd StockQueen
   tar -czf cache.tar.gz .cache/
   ```
2. **上传到 GitHub Release**
   - 创建 tag: `massive-cache`
   - 上传 `cache.tar.gz` 作为 Release Asset
3. **触发 upload-cache workflow**（把 Release Asset 存入 Actions Cache）
4. **之后每次跑计算**：直接触发 `walk-forward.yml`，选策略即可

## GitHub Secrets 需要配置

| Secret | 说明 |
|--------|------|
| `MASSIVE_API_KEY` | Massive API Key（行情+基本面+财报）|
| `SUPABASE_URL` | Supabase URL |
| `SUPABASE_KEY` | Supabase Key |

---

## 大算力任务清单

### 🔴 高优先级（影响生产参数）

| # | 任务 | 预计时长 | 脚本 | 状态 |
|---|------|---------|------|------|
| 1 | **V4 top_n × HB 二维网格验证** | ~6小时 | `walk_forward_v5_full.py --strategy v4`（需改脚本加 HB 搜索）| ⏳ 待跑 |
| 2 | **Strategy Matrix 502股完整回测** | ~1小时 | `test_strategy_matrix.py --only alloc` | ⏳ Render跑过但被中断 |

### 🟡 中优先级（验证子策略）

| # | 任务 | 预计时长 | 脚本 | 状态 |
|---|------|---------|------|------|
| 3 | **ED Walk-Forward + regime_series 修复** | ~2小时 | `walk_forward_v5_full.py --strategy ed`（需先修复 regime_series 传参）| ⏳ 待修复后跑 |
| 4 | **ED 敏感性测试** | ~30分钟 | `sensitivity_test.py --strategy ed` | ⏳ 未跑 |
| 5 | **新分配矩阵回测验证**（V5.1 ED降权后）| ~1小时 | `test_strategy_matrix.py --only alloc` | ⏳ 待跑 |

### 🟢 低优先级（方法论修复）

| # | 任务 | 预计时长 | 脚本 | 状态 |
|---|------|---------|------|------|
| 6 | **Monte Carlo 修复 + 重跑** | ~1小时 | `monte_carlo_test.py`（需先修复：随机入场日期而非PnL顺序）| ⏳ 未修复 |
| 7 | **MR 敏感性测试** | ~30分钟 | `sensitivity_test.py --strategy mr` | ⏳ 未跑 |

---

## 算力预算估算（GitHub Actions 免费额度）

| 任务 | 分钟数 | 免费额度消耗 |
|------|--------|------------|
| V4 HB 二维验证（任务1）| ~360 min | 18% |
| 其余全部任务 | ~300 min | 15% |
| **合计** | **~660 min** | **33%**（2000 min/月免费）|

> 每月 2000 分钟免费（私有仓库），超出 $0.008/min。当前任务全部在免费额度内。
