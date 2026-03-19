---
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
