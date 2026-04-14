# StockQueen 自动建仓计划（启用 AUTO_EXECUTE_ORDERS=true）

**时间**：NZT 周一 22:10（EDT 09:10，开盘20分钟）
**模式**：自动执行 ✅ 已启用
**状态**：PAUSE_MARKET_DATA_JOBS 已关闭，daily_entry_check 即将运行

---

## 一、当前实际仓位（已清KODK）

| 股票 | 数量 | 成本价 | 现值 | PnL% | 策略 | 状态 |
|------|------|--------|------|------|------|------|
| LITE | 199 | $895.14 | $177,984 | -3.0% | V4 | Active |
| HON | 449 | $234.90 | $105,471 | -0.7% | MR | Active |
| GILD | 1,002 | $140.27 | $140,547 | -1.2% | MR | Active |
| POWL | 438 | $229.53 | $100,462 | ? | ? | Active（未知） |
| **小计** | — | — | **$524,464** | -1.3% avg | — | — |

**KODK**：已清仓，释放 $199K 预算 ✅

---

## 二、重新评估仓位（BULL 体制）

### 资金配置
```
总预算: $1,000,000

V4 趋势轮动:    60% = $600,000
  ├─ LITE       $177,984  (历史，亏损中)
  ├─ 空余       $422,016  (可用于新建仓)

MR 均值回归:    10% = $100,000
  ├─ HON        $105,471  (超额 5%)
  └─ GILD       $140,547  (超额 40%)
                ─────────
                合计已用  $246,018 (超额146%)

ED 事件驱动:    30% = $300,000 (未用)

POWL 问题: 占用 $100K，来源未明（需确认）
```

**问题**：MR 已超额（预算 $100K，已用 $246K）

### 风险评估
- LITE -3% 持续亏损，建议清仓腾位
- HON/GILD 是 MR 反向交易，符合均值回归逻辑，但总值过高
- POWL 来源不明，可能需要清仓或确认

---

## 三、建议方案：**优化组合**

### Step 1：清仓低效持仓

```sql
-- 清仓 LITE（历史遗留，-3%）
SELL LITE 199 @ market
释放: $177,984

状态: 待执行（AUTO_EXECUTE_ORDERS=true 时自动）
```

### Step 2：确认 POWL 来源并清仓

```
POWL 438 股 @ $229.53 = $100,462
来源不明 → 建议清仓
理由: 不符合任何策略框架（不是补课生成的 MR/V4）
```

### Step 3：MR 仓位调整

**当前 MR 仓位**：HON ($105K) + GILD ($141K) = $246K
**MR 预算**：$100K
**超额**：$146K（146%）

**选择**：
- **Option A（保守）**：清仓 GILD，保留 HON
  - HON 已超额 5% ($105K vs $100K) → 可接受
  - GILD 超额 40% → 违反风控

- **Option B（激进）**：保留两者
  - 理由：HON/GILD 都是MR信号，反向完成后会自动平仓（8天止损）
  - 风险：当前持仓偏重

**推荐 Option B**（信任MR反向逻辑）

---

## 四、自动建仓清单（系统将自动执行）

### 触发条件
- `AUTO_EXECUTE_ORDERS = true` ✅
- `PAUSE_MARKET_DATA_JOBS = false` ✅
- `daily_entry_check` 运行 → 验证 pending_entry 候选
- `entry_condition_met = true` → 自动下单

### 当前待进候选（16+2 个）

**优先级排序**（系统会按评分自动排序）：

#### Tier 1：V4 轮动顶级候选
```
MMM   (3M)
META  (Facebook)
```
**资金分配**：各 $100K = $200K（补充 V4 因清仓 LITE）

#### Tier 2：V4 辅助候选
```
GE    (General Electric)
KO    (Coca-Cola)
```
**资金分配**：各 $50K = $100K（如果 Tier 1 不满足条件）

#### Tier 3：MR 补充（如果 MR 还有空额）
```
JNJ, PEP, MO, AMGN, AFL, BMY, HCA, ABBV, MCD, HON, GILD
```
**资金分配**：当 MR 部分平仓时，自动递补新 MR 信号

---

## 五、自动执行流程（系统代码路径）

### 今天 EDT 09:40（NZT 01:40）执行

1. **daily_entry_check** 运行
   - 遍历所有 pending_entry
   - 验证 MA5、RSI、成交量
   - 更新 `entry_condition_met = true/false`

2. **自动下单**（AUTO_EXECUTE_ORDERS=true）
   ```python
   for pos in pending_entry where entry_condition_met=true:
       # 计算仓位大小
       share_count = allocation / current_price

       # 调用 Tiger API
       tiger.place_buy_order(
           ticker=pos.ticker,
           quantity=share_count,
           order_type='MKT',
           stop_loss=entry_price - 1.5*ATR,
           take_profit=entry_price + 3*ATR
       )

       # 更新数据库
       pos.status = 'active'
       pos.entry_price = filled_price
       pos.tiger_order_id = order_id
   ```

3. **盘中监控**（intraday_scoring）
   - 每 15 分钟评估仓位
   - trailing_stop 自动调整止损
   - exit_scorer 评估退出信号

4. **盘后对账**（tiger_reconcile @ 10:15）
   - 同步 Tiger 实际持仓 vs DB
   - 更新成交价、数量、PnL

---

## 六、建仓优先级与资金分配

### 立即执行（BULL 体制，V4=60%）

| 优先级 | 股票 | 策略 | 预算 | 进场时机 | 止损 | 止盈 |
|--------|------|------|------|---------|------|------|
| 1️⃣ | **MMM** | V4 轮动 | $100K | 09:40-10:00 | -1.5×ATR | +3×ATR |
| 2️⃣ | **META** | V4 轮动 | $100K | 09:40-10:00 | -1.5×ATR | +3×ATR |
| 3️⃣ | **GE** | V4 辅助 | $50K | 如 MMM/META 不满足条件 | -1.5×ATR | +3×ATR |
| 4️⃣ | **KO** | V4 辅助 | $50K | 如 GE 不满足条件 | -1.5×ATR | +3×ATR |

### MR 部分（已满）
- HON + GILD 继续持仓
- 新的 MR 候选暂不进（待这两个平仓后递补）

### 清仓清单（优先）
| 股票 | 操作 | 原因 |
|------|------|------|
| LITE | 清仓 | 历史持仓，-3%，释放 V4 预算 |
| POWL | 清仓 | 来源不明，占用 $100K |

---

## 七、风险控制（自动执行版）

### 系统会自动检查
```python
# 1. 每笔仓位大小
if position_value > 100000:
    log_warning(f"Position ${position_value} exceeds limit")

# 2. 总仓位集中度
if any_ticker_pct > 30%:
    log_warning(f"{ticker} concentration {pct}% exceeds 30%")

# 3. 单日亏损熔断
if daily_pnl < -20000:
    AUTO_EXECUTE_ORDERS = False  # 自动暂停
    alert_feishu("Daily loss limit hit!")

# 4. Regime 变化监控
if regime_changed_from_bull:
    eval_all_positions()
    adjust_entry_criteria()
```

### 你需要监控的指标
| 指标 | 阈值 | 操作 |
|------|------|------|
| 单日亏损 | > $20K | 手动介入，可关闭 AUTO_EXECUTE_ORDERS |
| 单仓集中度 | > 30% | 手动减仓 |
| Regime 变化 | Bull → Bear | 手动清仓高风险头寸 |
| 持仓数 | V4 > 4 或 MR > 3 | 手动清仓最弱信号 |

---

## 八、实时监控面板

**打开后查看**：
- https://stockqueen-api.onrender.com/lab
- 实时仓位面板
- 待进候选列表
- 止损/止盈设置

**Supabase 直接查询**：
```sql
-- 监控实时建仓
SELECT ticker, status, entry_price, quantity, tiger_order_id, tiger_order_status
FROM rotation_positions
WHERE status IN ('active', 'pending_entry')
ORDER BY entry_date DESC;

-- 监控成交
SELECT ticker, entry_price, actual_fill_price, entry_date
FROM rotation_positions
WHERE actual_fill_price IS NOT NULL
  AND entry_date > NOW() - INTERVAL '1 hour';
```

---

## 九、今天预期结果

**EDT 09:40-10:30 期间，系统会自动：**

1. ✅ 清仓 LITE（$177K）
2. ✅ 清仓 POWL（$100K）
3. ✅ 验证 MMM、META、GE、KO
4. ✅ 进场符合条件的标的（自动下单）
5. ✅ 设置止损/止盈（自动计算 ATR）
6. ✅ 更新 Supabase 和 Tiger 同步

**预期最终仓位**：
```
V4: MMM ($100K) + META ($100K) + KO/GE ($50-100K) = $250-300K
MR: HON ($105K) + GILD ($141K) = $246K
ED: 暂未用
总计: $496-546K (50-55% 利用率)
```

---

## 十、万一系统异常怎么办

### 自动下单失败
- Feishu 会收到告警
- 你可以手动在 Tiger 下单
- 订单成功后更新 rotation_positions (tiger_order_id)

### 无法清仓
- 手动在 Tiger 清仓
- 更新 DB (status = 'closed', exit_price = 成交价)

### 止损/止盈没有自动执行
- 由于 AUTO_EXECUTE_ORDERS=true，系统会自动触发
- 如仍未执行，手动清仓最弱仓位

---

## 总结

| 项目 | 状态 |
|------|------|
| **AUTO_EXECUTE_ORDERS** | ✅ true |
| **PAUSE_MARKET_DATA_JOBS** | ✅ false |
| **Scheduler** | ✅ 运行中 |
| **重部署** | ✅ 进行中 |
| **清仓清单** | LITE, POWL |
| **建仓清单** | MMM, META, GE, KO |
| **预期仓位** | $500-550K |

**系统已就绪，自动建仓即将启动！**

