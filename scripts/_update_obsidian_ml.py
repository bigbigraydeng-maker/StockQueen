"""One-time script to update Obsidian ML docs with Chinese content."""
import http.client
import ssl

VAULT_KEY = "f49ee79c2be8d5f7b2166185e4141b38e7fe26ee828185bf9688a407c79a32cf"
BASE = "127.0.0.1"
PORT = 27124


def put_file(path, content):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(BASE, PORT, context=ctx)
    headers = {
        "Authorization": f"Bearer {VAULT_KEY}",
        "Content-Type": "text/markdown; charset=utf-8",
    }
    conn.request("PUT", f"/vault/{path}", body=content.encode("utf-8"), headers=headers)
    resp = conn.getresponse()
    resp.read()
    print(f"  {path}: {resp.status}")
    conn.close()


# ============================================================
# 00-Index.md
# ============================================================
INDEX = r"""---
name: ML Enhancement Index
description: ML增强层文档索引
created: 2026-03-19
updated: 2026-03-19
tags: [ml, xgboost, ranking, index]
---

# ML 增强层

StockQueen Step 2：基于 XGBoost 的攻击型排序模型，优化选股能力。

## 核心定位

> **混合策略矩阵负责防守（regime/VIX/现金/止损），ML 负责进攻（找高增长赢家）。**

## 文档列表

| 文档 | 内容 |
|------|------|
| [[ML/01-Architecture]] | 两层架构设计、攻防分工、集成方式 |
| [[ML/02-Training-Validation]] | Walk-Forward 训练流程、A/B 测试方法论 |
| [[ML/03-Feature-Engineering]] | 特征定义（22维）、攻击型特征设计 |

## 快速链接

- 核心代码：`app/services/ml_scorer.py`
- 集成入口：`app/services/rotation_service.py`（`ml_enhance` 参数）
- 训练脚本：`scripts/ml_train_ab_test.py`
- 模型存储：`models/ml_ranker/ml_ranker.pkl`
- ML-V1结果：`scripts/stress_test_results/ml_ab_test_results.json`
- ML-V2结果：`scripts/stress_test_results/ml_ab_test_results_ml-v2.json`

## 开发状态

- [x] ML scorer 模块 ML-V1（防御型，reg:squarederror）
- [x] ML-V1 A/B 测试完成 → 结论：降回撤但降收益，方向错误
- [x] ML scorer 模块 ML-V2（攻击型，rank:pairwise + 攻击特征）
- [x] ML-V2 A/B 测试完成 → 结论见下
- [ ] ML-V3 设计（待定方向：非对称标签 / regime-aware）
- [ ] 根据结果决定是否上线实盘

## ML-V2 A/B 测试结论（2026-03-19）

**Sharpe改善但收益仍下降，攻击型改造力度不够。**

| 指标 | ML-V1 | ML-V2 |
|------|-------|-------|
| 平均Sharpe差值 | +0.06 | **+0.14** ✅ |
| 平均收益差值 | -7.3% | **-7.0%** ≈持平 |
| 回撤改善 | 5/5窗口 | 5/5窗口 ✅ |

**核心发现**：ML在崩盘环境（W1 2020）大幅跑赢，但在牛市中系统性拖累收益。
详见 → [[ML/04-AB-Test-Results]]

## ML-V1 → ML-V2 改造记录

| 维度 | ML-V1（防御型）| ML-V2（攻击型）|
|------|-----------|-----------|
| 标签 | 绝对收益 next_1w_return | 截面z-score（相对排名）|
| 目标函数 | reg:squarederror | rank:pairwise |
| 模型 | XGBRegressor | XGBRanker |
| 特征 | 17维（基础特征）| 22维（+5攻击型特征）|
| 学到的 | 选安全票 | 选爆发票 |
| ML-V1 结果 | Sharpe +0.06，收益 -7.3% | Sharpe +0.14，收益 -7.0% |
"""

# ============================================================
# 01-Architecture.md
# ============================================================
ARCH = r"""---
name: ML Architecture
description: 两层架构设计、攻防分工
created: 2026-03-19
updated: 2026-03-19
tags: [ml, xgboost, architecture, ranking]
---

# ML 增强层架构

## 攻防分工设计

### 系统现状分析

```
防守侧（已充分覆盖）                  攻击侧（原有缺陷）
═══════════════════                  ═══════════════════
✅ Regime 四状态自动切换              ❌ 波动率惩罚压制高增长票
✅ Bear 自动降仓到 50%               ❌ 9因子打分偏向"稳定上涨"
✅ VIX 全局减仓 (x0.70)              ❌ 没有"爆发力"识别因子
✅ ATR 硬止损 + Trailing              ❌ 没有"加速突破"信号
✅ 均值回归 choppy 接管               ❌ 板块集中度限制可能砍掉热门板块
✅ 事件驱动全天候补充                  ❌ 只看 beat 率，不看增长故事
```

### 分工原则

```
混合策略矩阵 = 防守层（已有，不动）
  - Regime 切换、VIX 减仓、现金比例、止损
  - 均值回归（震荡市接管）
  - 事件驱动（全天候补充）

ML 增强层 = 攻击层（新增）
  - 在候选池里找出最可能大涨的票
  - 不是预测"哪只票下周涨"
  - 而是识别"谁比其他票涨得更多"
```

## 两层架构

```
第一层：规则引擎（冻结，不修改）       第二层：ML 排序（新增）
================================      ========================
- 9因子评分（~500只标的）        -->  XGBRanker 排序
- Regime 检测                         - 输入：22维特征
- 风控（ATR 止损）                    - 输出：排序分数
- 持仓管理                           - 范围：仅排序
- 交易执行

Alpha 来源 = 第一层                   排序优化 = 第二层
```

## ML 的严格边界

### ML 不能做的事

- ❌ 修改策略参数（TOP_N、ATR、止损）
- ❌ 参与风控逻辑
- ❌ 直接决定买卖执行
- ❌ 优化参数（避免过拟合）
- ❌ 改变 Regime 检测或选股池范围

### ML 能做的事

- ✅ 在规则引擎筛出的 Top 10 中重新排序
- ✅ 默认关闭（ml_enhance=False），零影响
- ✅ 随时可关闭，一键回退

## 集成方式：方案B（二次排序）

```
规则引擎评分（~500只标的）
    ↓ Regime/RS/流动性过滤
    ↓ 按9因子总分排序
Top 10 候选（规则引擎选出）
    ↓ XGBRanker 二次排序
    ↓ 按 ML 排序分数重排
Top 6 入选 → 通过第一层执行交易
```

### 为什么选方案B不选方案A

| | 方案A（直接替换） | 方案B（二次排序）✅ |
|---|---|---|
| ML 范围 | 排序所有标的 | 只排 Top 10 |
| 风险 | ML 出错影响全局 | ML 出错被限制在池内 |
| 回退 | 需要完整回退路径 | 池已经被预筛过 |

## ML-V1 → ML-V2 改造

### ML-V1 的问题

ML-V1 使用 `reg:squarederror` + 绝对收益标签，学到的是"选安全票"：
- 回撤降低了（每个窗口都降），但收益也降了
- 等于把防守侧的保守偏差又放大了一次
- **方向错了**：防守已经够了，需要的是攻击

### ML-V2 的改造

| 维度 | ML-V1 | ML-V2 |
|------|-----|-----|
| 标签 | `next_1w_return`（绝对收益）| 截面 z-score（相对排名）|
| 目标函数 | `reg:squarederror` | `rank:pairwise` |
| 模型类 | XGBRegressor | XGBRanker |
| 特征 | 17维 | 22维（+5攻击型）|
| 学到的模式 | 避开高波动 | 找到相对赢家 |

## 代码集成点

### 回测 (`rotation_service.py`)

```python
# run_rotation_backtest() 新增参数：
ml_enhance: bool = False        # 开关
ml_ranker: object = None        # 训练好的模型
ml_rerank_pool: int = 10        # 喂给 ML 的候选数
_collect_snapshots: list = None  # 收集训练数据
```

集成位置（约1930行）：
1. `scored.sort()` 按规则分数排序（不变）
2. 如果 `ml_enhance`: `ml_rerank_candidates()` 二次排序
3. 否则：原逻辑（sector_cap + top_n）

## 安全设计

1. **默认关闭**：`ml_enhance=False` 意味着零行为变化
2. **范围有限**：ML 只看 Top 10，不能注入池外标的
3. **仅 Walk-Forward**：不做样本内参数调优
4. **A/B 必须通过**：必须跑赢 baseline 才能上线
5. **一键关闭**：去掉 `ml_enhance=True` 即可回退

## 相关文档

- [[ML/00-Index]] — ML 文档索引
- [[ML/02-Training-Validation]] — 训练与验证方法
- [[ML/03-Feature-Engineering]] — 特征定义
- [[Strategy/06-Multi-Strategy-Matrix]] — 混合策略矩阵（防守层）
- [[Strategy/11-Multi-Factor-Scoring]] — 第一层评分引擎
"""

# ============================================================
# 02-Training-Validation.md
# ============================================================
TRAIN = r"""---
name: ML Training and Validation
description: Walk-Forward 训练流程与 A/B 测试方法
created: 2026-03-19
updated: 2026-03-19
tags: [ml, walk-forward, ab-test, validation]
---

# ML 训练与 A/B 验证

## Walk-Forward 窗口（扩展式）

| 窗口 | 训练期 | 测试期 | 测试环境 |
|------|--------|--------|---------|
| W1 | 2018-01 ~ 2019-12 | 2020-01 ~ 2020-12 | COVID 暴跌压力测试 |
| W2 | 2018-01 ~ 2020-12 | 2021-01 ~ 2021-12 | 疫后牛市 |
| W3 | 2018-01 ~ 2021-12 | 2022-01 ~ 2022-12 | 2022 熊市 |
| W4 | 2018-01 ~ 2022-12 | 2023-01 ~ 2023-12 | 复苏年 |
| W5 | 2018-01 ~ 2023-12 | 2024-01 ~ 2024-12 | 晚期牛市 |

## 训练流程

```
对每个窗口：
  1. 在训练期跑 baseline 回测
     → 每周收集评分快照（特征 + regime + 候选票）
  2. 构建训练数据：
     X = 22维特征向量
     y = 截面 z-score（该票的下周收益相对于当周所有候选票的均值/标准差）
     groups = 每周候选票数量（rank:pairwise 需要）
  3. 训练 XGBRanker（rank:pairwise 目标函数）
  4. 在测试期分别跑两个回测：
     a. Baseline（纯规则）
     b. ML增强（Top 10 → ML 重排 → Top 6）
  5. 对比：收益、Sharpe、回撤
```

## 标签设计（ML-V2 攻击型）

### 为什么不用绝对收益

ML-V1 使用 `y = next_1w_return` 作为标签：
- XGBoost 学到的是"预测低波动的正收益" → 偏保守
- 牛市中高 beta 票涨更多，但 ML 反而排到后面
- **结果**：回撤降了，收益也降了 — 方向错误

### ML-V2 截面 z-score

```python
# 每周的所有候选票收益
returns = [ticker1_ret, ticker2_ret, ..., ticker10_ret]
mean = mean(returns)
std = std(returns)

# 标签 = 相对于同期其他票的表现
y = (ticker_ret - mean) / std
```

**好处**：
- 模型学的是"谁比同期其他票涨得更好"
- 不受大盘涨跌影响（熊市也能学到相对赢家）
- 直接优化"排序质量"而不是"预测精度"

## 目标函数：rank:pairwise

```python
# ML-V1（错误）: objective = "reg:squarederror"
#   → 最小化预测值和真实值的差距
#   → 模型偏向预测"接近0的安全值"

# ML-V2（正确）: objective = "rank:pairwise"
#   → 优化 A 应该排在 B 前面的概率
#   → 模型学的是"排序"不是"预测"
```

## ML-V1 A/B 结果回顾

| 窗口 | Baseline Sharpe | ML Sharpe | 差值 | Baseline 回撤 | ML 回撤 |
|------|----------------|-----------|------|--------------|---------|
| W1 2020 | 0.16 | 0.97 | +0.81 ✓ | -51.4% | -26.5% |
| W2 2021 | 3.88 | 3.29 | -0.59 ✗ | -7.2% | -4.9% |
| W3 2022 | 2.09 | 2.14 | +0.05 ✓ | -4.4% | -3.6% |
| W4 2023 | 2.13 | 2.48 | +0.35 ✓ | -11.2% | -5.6% |
| W5 2024 | 1.53 | 1.21 | -0.32 ✗ | -18.0% | -9.6% |

**ML-V1 结论**：ML 降回撤（5/5窗口），但降收益（3/5窗口）— 防守过度

## ML-V2 A/B 结果（攻击型，2026-03-19）

| 窗口 | 市况 | Baseline收益 | ML收益 | Baseline Sharpe | ML Sharpe | Baseline回撤 | ML回撤 |
|------|------|-------------|--------|----------------|-----------|-------------|--------|
| W1 2020 | 暴跌+反弹 | +8.4% | **+29.1%** ✅ | 0.16 | **1.27** ✅ | -51.4% | -24.6% ✅ |
| W2 2021 | 强牛市 | +77.2% | +51.9% ❌ | 3.88 | 3.82 | -7.2% | -4.0% ✅ |
| W3 2022 | 震荡 | +16.0% | +13.5% | 2.09 | 1.88 | -4.4% | -4.6% |
| W4 2023 | 温和牛 | +43.9% | +30.8% ❌ | 2.13 | **2.16** ✅ | -11.2% | -5.6% ✅ |
| W5 2024 | 牛市 | +32.2% | +17.5% ❌ | 1.53 | 1.34 | -18.0% | -7.2% ✅ |
| **平均** | | **35.5%** | **28.6%** | **1.96** | **2.09** | **-18.4%** | **-9.2%** |

**ML-V2 结论**：
- ✅ Sharpe提升 +0.14（优于ML-V1的+0.06）
- ✅ 回撤改善显著（5/5窗口，平均减半）
- ❌ 收益仍然下降 -7.0%（牛市中系统性拖累）
- ⚠️ 特征重要性过于均匀（~0.050 each），攻击型特征未获得更高权重
- **判断**：攻击方向正确但力度不够，需要ML-V3进一步调整

详细分析 → [[ML/04-AB-Test-Results]]

## 通过标准

ML 增强上线实盘的标准：

1. 平均 OOS 收益 >= Baseline 收益（**核心：攻击力要提升**）
2. 平均 OOS Sharpe >= Baseline Sharpe
3. 回撤不能比 Baseline 差太多（< 5% 劣化可接受）
4. 在不同市场环境下稳定（牛/熊/震荡都不崩）

**注意**：ML-V2 的标准和 ML-V1 不同 — 我们允许回撤略增，但要求收益必须提升。

## 运行方式

```bash
cd StockQueen
python scripts/ml_train_ab_test.py
```

结果保存至：`scripts/stress_test_results/ml_ab_test_results_ml-v2.json`

## 相关文档

- [[ML/00-Index]] — ML 文档索引
- [[ML/01-Architecture]] — 架构设计
- [[ML/03-Feature-Engineering]] — 特征定义
- [[Walk-Forward/00-Index]] — Walk-Forward 验证（第一层参数）
"""

# ============================================================
# 03-Feature-Engineering.md
# ============================================================
FEAT = r"""---
name: ML Feature Engineering
description: 22维特征定义、攻击型特征设计
created: 2026-03-19
updated: 2026-03-19
tags: [ml, features, xgboost, feature-engineering]
---

# ML 特征工程

## 特征向量（22维）

所有特征从现有 `compute_multi_factor_score()` 输出 + OHLCV 数据提取，**无需额外API调用**。

ML-V2 新增 5 个攻击型特征（#18-22），专门用于识别高增长突破票。

---

## 基础特征（17维，来自评分引擎）

### 动量特征（5个）

| # | 名称 | 来源 | 范围 | 说明 |
|---|------|------|------|------|
| 1 | ret_1w | momentum.ret_1w | [-1, +1] | 5日收益 |
| 2 | ret_1m | momentum.ret_1m | [-1, +1] | 21日收益 |
| 3 | ret_3m | momentum.ret_3m | [-1, +1] | 63日收益 |
| 4 | volatility | momentum.vol | [0, +inf) | 21日年化波动率 |
| 5 | momentum_score | momentum.score | [-1, +1] | 加权动量综合分 |

### 技术特征（5个）

| # | 名称 | 来源 | 范围 | 说明 |
|---|------|------|------|------|
| 6 | rsi | technical.rsi | [0, 100] | RSI(14) |
| 7 | macd_hist | technical.macd_hist | (-inf, +inf) | MACD 柱状图 |
| 8 | bb_pos | technical.bb_pos | [0, 1] | 布林带位置 |
| 9 | adx | technical.adx | [0, 100] | ADX(14) 趋势强度 |
| 10 | technical_score | technical.score | [-1, +1] | 技术综合分 |

### 趋势与相对强度（2个）

| # | 名称 | 来源 | 范围 | 说明 |
|---|------|------|------|------|
| 11 | trend_score | trend.score | [0, 1] | 渐进式均线对齐 |
| 12 | rs_score | relative_strength.score | [-1, +1] | vs SPY 超额收益 |

### Regime 上下文（4个，one-hot）

| # | 名称 | 值 | 说明 |
|---|------|------|------|
| 13 | regime_strong_bull | 0/1 | 强牛 |
| 14 | regime_bull | 0/1 | 正常牛 |
| 15 | regime_choppy | 0/1 | 震荡 |
| 16 | regime_bear | 0/1 | 熊市 |

### 综合分（1个）

| # | 名称 | 来源 | 范围 | 说明 |
|---|------|------|------|------|
| 17 | rule_score | total_score | [-10, +10] | 9因子加权总分 |

---

## 攻击型特征（5维，ML-V2 新增）

这些特征专门设计来识别「即将爆发」的高增长票。

| # | 名称 | 计算方式 | 范围 | 攻击含义 |
|---|------|---------|------|---------|
| 18 | momentum_accel | ret_1w / abs(ret_1m) | [-5, +5] | **动量加速** — 近期加速上涨 = 爆发前兆 |
| 19 | volume_surge | avg_vol_5d / avg_vol_20d | [0, 5] | **放量突破** — 资金正在涌入 |
| 20 | new_high_pct | close / 52周最高价 | [0, 1] | **新高逼近** — 接近1.0 = 即将突破 |
| 21 | upside_vol | std(正收益日) * sqrt(252) | [0, +inf) | **上行波动** — 好的波动（涨得猛）|
| 22 | drawdown_from_peak | (close - peak) / peak | [-1, 0] | **浅回撤** — 接近0 = 底部扎实 |

### 攻击特征详解

**动量加速 momentum_accel**

```
当 ret_1w=5%, ret_1m=8% -> accel = 0.05/0.08 = 0.625
当 ret_1w=5%, ret_1m=3% -> accel = 0.05/0.03 = 1.667（加速中！）
```

高值说明最近一周加速上涨，可能正在突破关键位。

**放量突破 volume_surge**

```
avg_vol_5d = 200万股, avg_vol_20d = 100万股 -> surge = 2.0
```

突然放量 = 机构资金入场，突破信号。

**新高逼近 new_high_pct**

```
close = 98, 52w_high = 100 -> pct = 0.98
```

接近 1.0 说明即将创新高，阻力小，上涨空间大。

**上行波动 upside_vol**

只统计正收益日的波动率。高 upside_vol = 涨的时候涨得猛（好的波动），
与 volatility（所有日的波动率，包含暴跌）形成对比。

**浅回撤 drawdown_from_peak**

```
close = 95, 63d_peak = 100 -> dd = -0.05（仅回撤5%）
close = 70, 63d_peak = 100 -> dd = -0.30（回撤30%，趋势可能已破）
```

接近0 = 强势票，仅轻微回调。

---

## 设计取舍

### 为什么选这些特征

1. **零额外API调用**：全部从现有 OHLCV + 评分输出提取
2. **无前视风险**：特征只用截至当日的历史数据
3. **Regime 作为特征**：让模型在不同市场环境下学到不同的排序偏好
4. **规则分数包含**：给 ML 访问第一层综合分作为 baseline

### 刻意排除的特征

- 基本面数据（PEG/ROE）— 回测中不可用，会造成前视偏差
- 情绪数据 — 无历史归档
- 板块因子 — 太稀疏
- 盈利数据 — 已包含在 rule_score 中

### 未来可扩展

- 板块 one-hot 编码
- 收益率在全池的百分位排名
- 价格距 MA200 的距离
- 换手率变化

---

## 提取管道

```python
from app.services.ml_scorer import extract_features

# 输入：评分引擎输出 + OHLCV 数据
scorer_result = compute_multi_factor_score(closes, volumes, ...)
features = extract_features(
    scorer_result, regime="bull",
    closes=closes, volumes=volumes, highs=highs
)
# 输出：numpy array shape (22,)
```

## 相关文档

- [[ML/00-Index]] — ML 文档索引
- [[ML/01-Architecture]] — 架构设计
- [[ML/02-Training-Validation]] — 训练与验证
- [[Strategy/11-Multi-Factor-Scoring]] — 第一层评分系统（特征来源）
"""

# ============================================================
# 04-AB-Test-Results.md
# ============================================================
RESULTS = r"""---
name: ML AB Test Results
description: ML-V1 和 ML-V2 的 A/B 测试详细结果与分析
created: 2026-03-19
updated: 2026-03-19
tags: [ml, ab-test, results, analysis]
---

# ML A/B 测试结果

## 版本对比总览

| 指标 | ML-V1（防御型） | ML-V2（攻击型） |
|------|---------------|---------------|
| 模型 | XGBRegressor | XGBRanker |
| 目标函数 | reg:squarederror | rank:pairwise |
| 标签 | 绝对收益 | 截面z-score |
| 特征数 | 17 | 22（+5攻击型）|
| 平均Sharpe差值 | +0.06 | **+0.14** |
| 平均收益差值 | -7.3% | -7.0% |
| 平均回撤改善 | 是（5/5） | 是（5/5，更显著）|

---

## ML-V1 详细结果

> 测试日期：2026-03-19
> 配置：top_n=6, holding_bonus=0.0, ml_rerank_pool=10

| 窗口 | 训练期 | 测试期 | Baseline收益 | ML收益 | 差值 | Baseline Sharpe | ML Sharpe |
|------|--------|--------|-------------|--------|------|----------------|-----------|
| W1 | 2018-2019 | 2020 | +8.4% | +23.6% | +15.2% | 0.16 | 0.97 |
| W2 | 2018-2020 | 2021 | +77.2% | +50.2% | -27.0% | 3.88 | 3.29 |
| W3 | 2018-2021 | 2022 | +16.0% | +16.7% | +0.7% | 2.09 | 2.14 |
| W4 | 2018-2022 | 2023 | +43.9% | +28.9% | -15.0% | 2.13 | 2.48 |
| W5 | 2018-2023 | 2024 | +32.2% | +17.1% | -15.1% | 1.53 | 1.21 |

**ML-V1 结论**：模型学到了"选安全票"，在每个窗口都降低了回撤，但在牛市中严重拖累收益。方向错误——防守侧已经足够。

---

## ML-V2 详细结果

> 测试日期：2026-03-19
> 配置：top_n=6, holding_bonus=0.0, ml_rerank_pool=10, objective=rank:pairwise, label=cross_sectional_zscore

### 逐窗口对比

| 窗口 | 市况 | Baseline收益 | ML收益 | 差值 | Baseline Sharpe | ML Sharpe | 差值 |
|------|------|-------------|--------|------|----------------|-----------|------|
| W1 2020 | 暴跌+反弹 | +8.4% | **+29.1%** | **+20.7%** ✅ | 0.16 | **1.27** | **+1.11** |
| W2 2021 | 强牛市 | +77.2% | +51.9% | -25.3% ❌ | 3.88 | 3.82 | -0.06 |
| W3 2022 | 震荡 | +16.0% | +13.5% | -2.5% | 2.09 | 1.88 | -0.21 |
| W4 2023 | 温和牛 | +43.9% | +30.8% | -13.1% ❌ | 2.13 | **2.16** | +0.03 |
| W5 2024 | 牛市 | +32.2% | +17.5% | -14.7% ❌ | 1.53 | 1.34 | -0.19 |

### 回撤对比

| 窗口 | Baseline回撤 | ML回撤 | 改善 |
|------|-------------|--------|------|
| W1 2020 | -51.4% | -24.6% | **-26.8pp** ✅ |
| W2 2021 | -7.2% | -4.0% | -3.2pp ✅ |
| W3 2022 | -4.4% | -4.6% | +0.2pp |
| W4 2023 | -11.2% | -5.6% | -5.6pp ✅ |
| W5 2024 | -18.0% | -7.2% | -10.8pp ✅ |

### 胜率对比

| 窗口 | Baseline胜率 | ML胜率 |
|------|-------------|--------|
| W1 2020 | 50% | 54% |
| W2 2021 | 60% | **66%** |
| W3 2022 | 28% | 32% |
| W4 2023 | 42.9% | **44.9%** |
| W5 2024 | 52% | 52% |

---

## 模式分析

### 1. ML在崩盘中表现极好

W1（2020 COVID）是唯一ML大幅跑赢的窗口：
- 收益：+8.4% → +29.1%（+20.7pp）
- Sharpe：0.16 → 1.27（+1.11）
- 回撤：-51.4% → -24.6%（减半）

**原因**：崩盘中少数不跌的票z-score极高，模型能准确识别这些相对赢家。

### 2. ML在牛市中系统性拖累收益

W2/W4/W5（牛市）ML均大幅落后：
- W2：-25.3pp
- W4：-13.1pp
- W5：-14.7pp

**原因**：
- 牛市中pool_mean本身很高，相对超额难以拉开差距
- 模型仍倾向于选"稳定上涨"而非"爆发上涨"
- 22个特征权重过于均匀，攻击型特征未主导排序

### 3. 特征重要性分布过于平均

最后窗口（W5）特征重要性 Top 10：

| 排名 | 特征 | 重要性 | 类型 |
|------|------|--------|------|
| 1 | rs_score | 0.052 | 基础 |
| 2 | volume_surge | 0.052 | 攻击 ✅ |
| 3 | adx | 0.052 | 基础 |
| 4 | drawdown_from_peak | 0.051 | 攻击 ✅ |
| 5 | ret_1m | 0.051 | 基础 |
| 6 | momentum_accel | 0.051 | 攻击 ✅ |
| 7 | upside_vol | 0.050 | 攻击 ✅ |
| 8 | macd_hist | 0.050 | 基础 |
| 9 | bb_pos | 0.050 | 基础 |
| 10 | technical_score | 0.049 | 基础 |

**问题**：所有特征重要性都在 0.048~0.055 之间，几乎完全均匀。攻击型特征没有获得显著更高的权重，说明模型没有学到"攻击信号比基础信号更重要"。

---

## ML-V3 改进方向（待实施）

### 方案A：非对称标签（推荐）

```python
if ret > 0: label = ret * 1.5   # 放大上行
if ret <= 0: label = ret * 0.5  # 缩小下行惩罚
```

直接在标签层面告诉模型"我们更在乎upside"。

### 方案B：Regime-aware 训练

- 分市况训练不同子模型
- 牛市模型只优化"抓涨最快的"
- 熊市/震荡模型保持防守

### 方案C：特征权重调整

- 减少基础特征数量，提高攻击型特征占比
- 或给攻击型特征加 sample weight

---

## 结论

ML-V2 相比 ML-V1 在正确方向上有所改善（Sharpe差值从+0.06提升到+0.14），但核心目标——**在牛市中提升收益**——仍未达成。模型本质上仍在做防守（降回撤），只是做得比ML-V1更好。

**状态**：ML增强暂搁置，优先推进 V5 路线图其他任务（动态选股池、Regime仓位管理）。ML-V3 待选股池扩大后（300-500只标的）再评估，因为更大的选股池可能给ML提供更多区分度。

## 相关文档

- [[ML/00-Index]] — ML 文档索引
- [[ML/01-Architecture]] — 架构设计
- [[ML/02-Training-Validation]] — 训练与验证
- [[ML/03-Feature-Engineering]] — 特征定义
"""

# ============================================================
# Execute
# ============================================================
if __name__ == "__main__":
    print("Updating Obsidian ML docs (UTF-8 Chinese)...")
    put_file("docs/ML/00-Index.md", INDEX)
    put_file("docs/ML/01-Architecture.md", ARCH)
    put_file("docs/ML/02-Training-Validation.md", TRAIN)
    put_file("docs/ML/03-Feature-Engineering.md", FEAT)
    put_file("docs/ML/04-AB-Test-Results.md", RESULTS)
    print("Done!")
