---
created: 2026-03-19
updated: 2026-03-22
source_date: 2026-03-19
source: app/services/rotation_service.py, app/services/regime_monitor.py, app/services/notification_service.py, app/routers/web.py
tags: [strategy, regime, market-state, monitoring, stockqueen]
---

# Regime 体制检测与监控系统

> Regime 是 StockQueen 的"大脑"——所有下游决策（选股池、因子权重、仓位分配、策略开关）都以体制判断为起点。
> 2026-03-19：新增每日监控 + 变化即时告警 + 轮动页面历史展示

---

## 设计哲学

**核心问题**: 同一套参数不可能在牛市和熊市都有效。

**解决方案**: 先判断市场处于什么状态，再决定怎么做。

```
市场数据 --> Regime Detection --> 4种状态之一
                                    |
                    +---------------+---------------+
                    |               |               |
              选什么股票?      用什么权重?     分多少仓位?
```

---

## 四信号评分模型

### 信号定义

| # | 信号 | 数据源 | 看多 | 中性 | 看空 |
|---|------|--------|------|------|------|
| 1 | SPY vs MA50 | SPY 收盘价 | >MA50*1.02: **+2** / >MA50: **+1** | - | <MA50*0.98: **-2** / else: **-1** |
| 2 | SPY vs MA20 | SPY 收盘价 | >MA20: **+1** | - | <=MA20: **-1** |
| 3 | 21日波动率 | SPY 日收益率 | <12%: **+1** | 12-25%: **0** | >25%: **-1** |
| 4 | 1月收益率 | SPY 收盘价 | >3%: **+1** | -3%~+3%: **0** | <-3%: **-1** |

**总分范围**: [-5, +5]

### 体制映射

| 总分 | 体制 | 含义 |
|------|------|------|
| >= 4 | **strong_bull** | 强势上涨 |
| 1 ~ 3 | **bull** | 温和上涨 |
| -1 ~ 0 | **choppy** | 震荡 |
| < -1 | **bear** | 下跌趋势 |

---

## Regime 与 Hedge Overlay 联动（V5 新增 2026-03-22）

> Regime 不仅影响选股和权重，还直接驱动对冲层的启停。

### 联动矩阵

| Regime | 选股门槛 | 动量权重偏好 | ATR止损 | **对冲仓位** |
|--------|---------|------------|---------|------------|
| strong_bull | -0.1（放宽） | 偏长期(15/35/50) | 1.5x | **0%** |
| bull | 0.0（基准） | 均衡(20/40/40) | 1.5x | **0%** |
| choppy | 0.2（收紧） | 偏短期(35/40/25) | 1.2x | **10%** |
| bear | 0.5（大幅收紧） | 快速反应(40/40/20) | 1.0x | **30%** |

### 对冲触发示意

```
Regime 信号评分
    |
    ├── >= 1 (bull/strong_bull)
    │       → 对冲关闭，全仓 Alpha 选股
    │
    ├── -1 ~ 0 (choppy)
    │       → 对冲开启 10%，选最弱指数对标反向ETF
    │       → Alpha 选股仓位缩减至 90%
    │
    └── < -1 (bear)
            → 对冲开启 30%，选最弱指数对标反向ETF
            → Alpha 选股仓位缩减至 70%
            → 同时选股门槛收紧至 0.5
```

> **关键设计**: 对冲是渐进式的，不是 0/1 开关。choppy 就开始小额建仓，不等崩盘才行动。

---

## 每日监控与即时告警

### 监控流程

```
每个交易日 09:20 NZT（美股收盘后5分钟）
    |
    v
Scheduler Job 1b: _run_regime_monitor()
    |
    v
regime_monitor.check_regime_and_alert()
    |
    +-- Step 1: detect_regime_details() 实时计算当前 regime
    +-- Step 2: 查 Supabase regime_history 表获取上一次记录
    +-- Step 3: 对比 --> 有变化?
    |       |               |
    |      YES             NO
    |       |               |
    |   发送 Feishu 告警    静默记录
    |       |               |
    +-- Step 4: 写入 regime_history 表（含 changed_from 字段）
```

### 告警消息格式（Feishu）

```
标题: REGIME DOWNGRADE: Bull --> Bear

Regime Change: Bull --> Bear
Direction: DOWNGRADE
Score: -2 (range: -5 to +5)
SPY: $521.30

--- Signal Breakdown ---
  SPY vs MA50: -2.3% (-2 pts)
  SPY vs MA20: -1.1% (-1 pts)
  波动率 (21d): 28.5% (-1 pts)
  1个月回报: -4.2% (-1 pts)

--- Impact ---
  Pool: DEFENSIVE + INVERSE ETFs only (7 tickers)
  Cash: ~50% minimum
```

### 调度时间线

| 时间 (NZT) | 事件 |
|------------|------|
| 09:15 | Job 1: 拉取市场数据 |
| **09:20** | **Job 1b: Regime 监控** |
| 09:30 | Job 2: D+1 确认引擎 |
| 09:40 | Job 3: 入场检查 |
| 09:45 | Job 4: 退出检查 |
| 周六 10:00 | Job 10: 周度轮动 |

---

## 前端展示

### 轮动策略页面 `/rotation`

页面结构（上到下）：

| Section | 内容 | 加载方式 |
|---------|------|---------|
| 1.0 | 当前市场环境 Badge | 直接渲染 |
| 1.5 | Regime 状态机 + 信号仪表盘 | HTMX `/htmx/regime-map` |
| **1.6** | **Regime 变化日志（新增）** | **HTMX `/htmx/regime-history`** |
| 2.0 | Top 3 入选标的 | 直接渲染 |
| 3.0 | 评分分布 + 板块热力图 | 直接渲染 |
| 4.0 | 全部评分表 | 直接渲染 |
| 5.0 | 轮动历史 Timeline | 直接渲染 |
| 6.0 | 手动操作面板 | 直接渲染 |

### Regime 变化日志 UI 特性

- **时间线布局**: 竖向时间轴，最新在上
- **变化高亮**: 体制变化行黄色左边框 + 黄色圆点
- **UPGRADE/DOWNGRADE 徽章**: 绿色/红色标记方向
- **信号分解**: 变化行展开显示 4 信号的分值贡献
- **稳定行**: 仅显示日期 + regime + score + SPY价格
- **统计摘要**: 顶部显示"近 N 天内发生 X 次体制转换"

### API 端点

| 端点 | 用途 |
|------|------|
| `/htmx/regime-map` | 状态机 + 信号仪表盘 |
| `/htmx/regime-history` | 变化日志 Timeline |
| `/api/public/regime-details` | JSON API（完整详情） |

---

## Regime 对策略的5层影响

### Layer 1: 选股池切换

| 体制 | 可用池 | 约多少只 |
|------|--------|---------|
| strong_bull | 攻击ETF + 大盘蓝筹 + 中盘成长 | ~500 |
| bull | 攻击ETF + 大盘蓝筹 + 中盘成长 | ~500 |
| choppy | 防守ETF + 攻击ETF + 大盘蓝筹 | ~120 |
| **bear** | **防守ETF + 反向ETF** | **7** |

### Layer 2: 动量因子权重

| 体制 | 1W | 1M | 3M | 策略意图 |
|------|-----|-----|-----|---------|
| strong_bull | 0.15 | 0.35 | **0.50** | 重仓长期趋势 |
| bull | 0.20 | 0.40 | 0.40 | 均衡 |
| choppy | **0.35** | 0.40 | 0.25 | 偏重短期反转 |
| bear | **0.40** | 0.40 | 0.20 | 快速反应 |

### Layer 2.5: ATR 止盈止损倍数（2026-03-20 新增）

熊市防守ETF/反向ETF 快打快撤，强牛市让利润奔跑。R:R 全机制维持 >= 2:1。

| 体制 | 止损倍数 | 止盈倍数 | R:R | 核心逻辑 |
|------|---------|---------|-----|---------|
| strong_bull | 1.5x ATR | 4.0x ATR | 2.67:1 | 趋势强，让利润奔跑 |
| bull | 1.5x ATR | 3.0x ATR | 2:1 | WF 锁定值（默认） |
| choppy | 1.2x ATR | 2.5x ATR | 2.08:1 | 反弹幅度有限，提前锁利 |
| **bear** | **1.0x ATR** | **2.0x ATR** | **2:1** | **TLT/GLD/反向ETF 快打快撤** |

> 反向ETF（SH/PSQ/RWM/DOG）每日衰减，持有越久损耗越大；bear 模式止盈收紧到 2.0x ATR 避免过度持仓。
> 详见 [[10-Stop-Loss-Take-Profit]]

### Layer 3: 三策略仓位分配

| 体制 | V4 轮动 | 均值回归 | 事件驱动 | 现金 |
|------|---------|---------|---------|------|
| strong_bull | 70% | 0% | 30% | 0% |
| bull | 60% | 10% | 30% | 0% |
| choppy | 30% | 50% | 20% | 0% |
| **bear** | 20% | 0% | 30% | **50%** |

### Layer 4: VIX 全局减仓

| VIX | 乘数 | bear+VIX=38 场景 |
|-----|------|----------------|
| > 35 | x0.70 | 50% x 0.70 = **35%仓位, 65%现金** |
| > 25 | x0.85 | |
| < 25 | x1.00 | |

### Layer 5: 子策略开关

| 子策略 | 激活体制 |
|--------|---------|
| V4 动量轮动 | 全部（bear 仅操作防守/反向ETF） |
| 均值回归 | **仅 bull** |
| 事件驱动 | 全部 |

---

## 数据存储

### regime_history 表

```sql
CREATE TABLE regime_history (
    id           BIGSERIAL PRIMARY KEY,
    date         DATE NOT NULL UNIQUE,
    regime       TEXT NOT NULL,
    score        INTEGER NOT NULL,
    spy_price    NUMERIC(10, 2),
    signals      JSONB,
    changed_from TEXT,          -- 有变化时记录上一个 regime
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
```

### 相关表

| 表 | 记录内容 |
|----|---------|
| `regime_history` | 每日 regime + score + 变化标记 |
| `rotation_snapshots` | 每周轮动快照（含 regime） |
| `sector_snapshots` | 板块评分快照（含 regime） |
| `positions` | 持仓（含入场时 market_regime） |

---

## 已知问题与改进方向

| 问题 | 状态 | 备注 |
|------|------|------|
| ~~无每日监控~~ | **已解决** | Job 1b 每日 09:20 检测 |
| ~~无变化告警~~ | **已解决** | Feishu 即时推送 |
| ~~无历史展示~~ | **已解决** | 轮动页面 Section 1.6 |
| 无确认延迟 | 待启用 | REGIME_CONFIRM_DAYS=3 已定义未实现 |
| 均值回归仅 bull | 设计决策 | 可扩展到 choppy |

---

## 代码文件索引

| 功能 | 文件 | 关键函数 |
|------|------|---------|
| 体制检测 | `app/services/rotation_service.py` | `_detect_regime()`, `detect_regime_details()` |
| 每日监控 | `app/services/regime_monitor.py` | `check_regime_and_alert()` |
| 变化告警 | `app/services/notification_service.py` | `notify_regime_change()` |
| Scheduler | `app/scheduler.py` | Job 1b `_run_regime_monitor()` |
| 历史展示 | `app/routers/web.py` | `/htmx/regime-history` |
| 历史模板 | `app/templates/partials/_regime_history.html` | Timeline UI |
| 状态机模板 | `app/templates/partials/_regime_map.html` | 状态机 + 仪表盘 |
| 建表 SQL | `database/create_regime_history.sql` | - |
