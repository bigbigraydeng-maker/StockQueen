# StockQueen 周一开盘操作清单

**日期**：NZT 周一 2026-04-14
**美股开盘**：EDT 09:30 = NZT 01:30
**体制**：BULL（中等强度）

---

## 时间表

| 美股时间 | NZT时间 | 任务 | 状态 |
|---------|--------|------|------|
| 08:30 EDT | 00:30 NZT | 提醒：开盘前1小时 | 准备 |
| **09:30 EDT** | **01:30 NZT** | **美股开盘** | 🟢 GO |
| 09:40 EDT | 01:40 NZT | daily_entry_check 运行 | 自动 |
| 09:40-10:00 EDT | 01:40-02:00 NZT | **逐笔确认进场** | 你的操作 |
| 11:00 EDT | 03:00 NZT | 订单确认截止 | 检查 |
| 15:00 EDT | 23:00 NZT | 日汇总报告 | 自动 |

---

## 候选清单（共 20 个）

### 新增 MR 信号（16 个，刚补课）
```
MMM (3M)
GE (通用电气)
KO (可口可乐)
HD (家得宝)
JNJ (强生)
PEP (百事)
MO (菲利普莫里斯)
AMGN (安进)
AFL (艾弗劳瑞)
BMY (必和必拓)
HCA (医疗保健)
META (Meta)
ABBV (艾伯维)
MCD (麦当劳)
HON (霍尼韦尔)
GILD (吉利德)
```

### 历史待进（4 个）
```
VIAV (Viavi Solutions)
GLW (康宁)
AAOI (Applied Optoelectronics)
SNDK (SanDisk)
```

---

## 进场前检查清单

对每个候选逐项验证：

### 技术面
- [ ] 当前价 > MA5（反转趋势确认）
- [ ] RSI < 28（深度超卖）
- [ ] 布林带位置 < 0.05（极端下轨）
- [ ] 盘中成交量 > 1.5M（MR放量确认）

### 仓位管理
- [ ] 单笔进场金额 <= $50K
- [ ] 总投入 <= $1M（BULL+MR = 10% 账户）
- [ ] 已有仓位 LITE 不与新进重仓同一行业

### 止损/止盈
- [ ] 止损点 = 进场价 - 2×ATR（系统会计算）
- [ ] 止盈点 = 进场价 + 3×ATR（目标反转完成）
- [ ] 时间止损 = 8 天（MR 最长持仓）

### 风险检查
- [ ] 今日亏损 < $20K（熔断阈值）
- [ ] 单个仓位 < 30% 净值（集中度）
- [ ] Regime 仍为 BULL（变化立即重评）

---

## 进场操作流程

### 1. 确认候选（09:35 EDT）
登录 https://stockqueen-api.onrender.com/lab，查看系统推荐。

### 2. 验证信号（09:40 EDT）
daily_entry_check 运行后，Supabase 会更新 entry_condition_met 字段。

### 3. 逐笔下单（09:40-10:00 EDT）
对每个推荐标的：
```
1. 查看 signal_price（系统扫描时的价格）
2. 对比当前实时价格（可能已变化）
3. 确认 MA5 + 止损 + 止盈
4. 计算数量 = 金额 / 当前价
5. Tiger 买入单
6. 确认成交
```

### 4. 记录成交（11:00 EDT）
在 rotation_positions 中更新：
- entry_price = 实际成交价
- quantity = 实际成交量
- tiger_order_id = 订单 ID
- status = active

---

## 当前仓位

| 股票 | 状态 | 进场价 | 数量 | 注释 |
|------|------|--------|------|------|
| LITE | Active | $895.14 | 199 | 继续持有 |

---

## 事件信号补充

**NKE**（Nike）
- 信号类型：内幕大额买入 $500K
- 强度：0.8/1.0
- 方向：看涨
- 状态：已记录，不在 MR 候选中（可单独关注）

---

## 风险警告

### 绝对禁止
- 单笔 > $50K
- 总持仓 > $1M
- 仓位集中 > 30%
- Regime 变化仍按旧逻辑操作

### 立即止损条件
- 单日亏损 > $20K（自动熔断）
- RSI 反弹失败（>40）
- Regime 转向 BEAR

### 监控指标
- 每 15 分钟检查一次 Tiger 持仓
- 关注美股大盘 VIX（若 > 25 收紧仓位）

---

## 常用 API 端点

```
# 查看进场候选
GET /api/rotation-signals

# 手动更新止损/止盈
POST /api/positions/{position_id}/update-sl-tp

# 查看实时仓位
GET /api/tiger-positions

# 查看 Regime
GET /api/regime/current

# 提交进场确认
POST /api/positions/{position_id}/activate
```

---

## 备备案

如果系统异常：

### 候选数据源
Supabase → rotation_positions 表 → status='pending_entry' 且 entry_condition_met=true

### 信号验证
manual check：
- AlphaVantage RSI（最近 14 根 daily bar）
- Bollinger Band 位置（20 日 MA ± 2σ）
- 成交量对比（20 日均值）

### 备用下单
Tiger API 直接下单（跳过系统确认流程）

---

## 成功标志

- [ ] 第一笔订单成交
- [ ] rotation_positions 出现 status=active 的新行
- [ ] Tiger 账户余额 < 初始值
- [ ] Feishu 收到下单通知

祝交易顺利！

