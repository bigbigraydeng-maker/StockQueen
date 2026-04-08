# 铃铛策略（盘中日内交易）启动清单

**启动日期**: 2026-04-08
**账户类型**: Tiger 模拟盘 (leverage)
**交易频率**: 30分钟一轮
**运行时间**: EDT 10:00-16:00 (NZT 3:00-8:00)
**首轮**: 今天 EDT 10:00 或明天如果美股已收盘

---

## ✅ 启动前必做清单

### 1️⃣ Tiger API 模拟账户配置

**检查 `.env` 文件：**
```bash
# 查看配置
grep -E "TIGER_ACCOUNT|TIGER_ID" .env
```

**必须包含这两个账户配置：**
```
# 生产账户（可不用）
TIGER_ACCOUNT=your_live_account
TIGER_ID=your_tiger_id
TIGER_PRIVATE_KEY=...

# 模拟账户（必需）
TIGER_ACCOUNT_2=your_paper_account
TIGER_ID_2=your_paper_tiger_id
TIGER_PRIVATE_KEY_2=...
```

**验证连接（本地运行）：**
```bash
python3 << 'EOF'
import asyncio
from app.services.order_service import TigerTradeClient

async def test():
    trader = TigerTradeClient(account_label="leverage")
    equity = await trader.get_account_equity()
    print(f"Equity: ${equity:,.2f}")
    print("✓ Tiger API connected")

asyncio.run(test())
EOF
```

---

### 2️⃣ 启用自动交易模式

**编辑 `app/config/intraday_config.py`：**

找到第 53-54 行，改为：
```python
AUTO_EXECUTE: bool = True           # 启用自动下单（改为 True）
ACCOUNT_LABEL: str = "leverage"     # 使用模拟账户标签
```

**验证配置：**
```bash
python3 << 'EOF'
from app.config.intraday_config import IntradayConfig as cfg
print(f"Auto Execute: {cfg.AUTO_EXECUTE}")
print(f"Account: {cfg.ACCOUNT_LABEL}")
print(f"TOP_N: {cfg.TOP_N}")
print(f"Max Position: {cfg.MAX_POSITION_SIZE*100}%")
print(f"Max Total Exposure: {cfg.MAX_TOTAL_EXPOSURE*100}%")
EOF
```

---

### 3️⃣ 代码推送到 main

```bash
# 检查修改
git status

# 添加文件
git add app/config/intraday_config.py \
        app/services/intraday_trader.py \
        app/services/intraday_service.py

# 提交
git commit -m "feat(intraday): 启用自动交易，P0风控已集成

- 30分钟交易频率
- 完整的P0风控（维持率、日亏、日冲、自动减仓）
- Tiger模拟账户连接
- 实时风控监控

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"

# 推送
git push origin main
```

**等待 Render 部署（2-5 分钟）**

---

### 4️⃣ 启动 Render 应用

**确保应用已运行：**
```bash
# 检查 Render dashboard
# https://dashboard.render.com/

# 或检查日志
tail -f logs/render.log | grep "intraday\|TRADER"
```

---

## 📊 运行监控

### 实时监控方案

**方案 1: Dashboard 网页（推荐）**
```
打开 http://localhost:8000/dashboard
或 https://your-render-url.com/dashboard

查看：
  - 盘中评分卡片（自动每60秒刷新）
  - 活跃头寸（实时 P&L）
  - 风控指标（维持率、日P&L、日冲计数）
```

**方案 2: 终端实时日志**
```bash
# 本地开发环境
tail -f logs/intraday_trader.log

# 或通过 Render 日志
curl -s https://your-render-url.com/api/logs/intraday
```

**方案 3: 自动报告邮件（可选）**
```
每天 16:00 EDT 发送日报：
  - 日内交易总结
  - P&L 统计
  - 风控检查
  - 明日预告
```

---

## 🔴 实时监控要点（必看！）

每轮评分后（10:00, 10:30, 11:00, ...），检查：

| 指标 | 正常 | 警告 | 危险 | 操作 |
|------|------|------|------|------|
| **维持率** | > 50% | 30-50% | < 30% | 自动减仓 |
| **日 P&L** | 正数 | -0.5% | < -2% | 停止建仓 |
| **日冲计数** | < 2 | 2-3 | >= 3 | 避免同日买卖 |
| **入场滑点** | < 0.5% | 0.5-1% | > 1% | 检查网络 |
| **头寸异常** | 0 | 1 个 | > 1 | 人工审查 |

**如果看到这些，立即关闭自动交易：**
- 🔴 维持率 < 30%
- 🔴 日冲计数 = 3（违反 PDT）
- 🔴 某只票跳空 5% 以上（可能需要强制平仓）
- 🔴 网络延迟 > 2 秒（可能导致滑点）
- 🔴 Tiger API 连接断开

---

## 🛑 紧急停止流程

**如果需要紧急停止自动交易：**

1️⃣ **立即停止建仓：**
```bash
# 编辑 intraday_config.py
AUTO_EXECUTE = False
```

2️⃣ **平仓所有头寸：**
```bash
# Tiger 账户页面手动平仓
# 或运行脚本
python3 scripts/close_all_intraday_positions.py
```

3️⃣ **检查账户：**
```bash
# 查看最终持仓和 P&L
curl -s http://localhost:8000/api/account-status
```

---

## 📈 预期表现（基于回测）

| 指标 | 目标 | 意义 |
|------|------|------|
| **日均 P&L** | +0.5% - +2% | 日收益 |
| **月度 Sharpe** | > 2.0 | 风险调整收益 |
| **最大单日亏损** | < -2% | 风控上限 |
| **胜率** | > 50% | 赢家多于输家 |
| **平均入场滑点** | < 0.3% | 执行质量 |

**前 3 天预期：**
- 🟢 正常: Sharpe 1.5-2.5，日均 +0.5%-1%
- 🟡 需观察: Sharpe 1.0-1.5，日均 -0.5%-0.5%
- 🔴 需改进: Sharpe < 1.0，日均 < -0.5%

**如果 3 天后 Sharpe < 1.0，检查：**
1. 市场环境（熊市 vs 牛市）
2. 融资成本（是否过高）
3. 入场信号（是否有延迟）
4. 因子权重（是否需要调整）

---

## 📝 日志和文件位置

```
日志文件:
  logs/intraday_trader.log          # 交易执行日志
  logs/intraday_scorer.log          # 评分日志
  logs/intraday_service.log         # 调度日志

数据库:
  Supabase.intraday_scores          # 所有评分记录
  Supabase.order_audit_log          # 所有订单记录
  Supabase.position_audit_log       # 头寸变化记录

配置:
  app/config/intraday_config.py     # 策略参数
  .env                              # Tiger API 凭证

结果:
  scripts/backtest_intraday_results.json  # 回测结果
```

---

## 🎯 后续优化（运行 1 周后）

**基于实际表现，可调整：**

1. **因子权重**（如果某个因子效果特别差）
   ```python
   FACTOR_WEIGHTS: dict = {
       "intraday_momentum": 0.30,  # 提高动量权重
       "vwap_deviation": 0.20,
       ...
   }
   ```

2. **止盈止损倍数**（如果频繁虚假止损）
   ```python
   TAKE_PROFIT_ATR_MULT: float = 4.0    # 提高止盈
   STOP_LOSS_ATR_MULT: float = 2.0      # 提高止损
   ```

3. **头寸大小**（如果维持率波动太大）
   ```python
   MAX_POSITION_SIZE: float = 0.10      # 降低到 10%
   MAX_TOTAL_EXPOSURE: float = 1.20     # 降低到 120%
   ```

4. **交易池**（如果某些股票表现特别差）
   ```python
   UNIVERSE: list = [...]  # 移除表现差的
   ```

---

## ✅ 最终检查清单

启动前请确认：

- [ ] Tiger API 模拟账户已验证连接
- [ ] `.env` 中 TIGER_ACCOUNT_2 配置正确
- [ ] `intraday_config.py` 已设 `AUTO_EXECUTE=True`
- [ ] 代码已 push 到 main
- [ ] Render 已部署（检查部署状态）
- [ ] Dashboard 可访问
- [ ] 你已理解所有风控阈值
- [ ] 已准备好监控脚本
- [ ] 已准备好紧急停止流程
- [ ] 账户有足够的现金（建议最少 $5K）
- [ ] 网络连接稳定

---

## 🚀 启动时刻表

**今天（EDT 时间）:**
- ⏰ 09:55 - 打开 Dashboard，准备监控
- ⏰ 10:00 - 首轮评分 + 自动下单（如果信号强）
- ⏰ 每 30 分钟 - 新一轮评分 + 止盈止损检查
- ⏰ 16:00 - 最后一轮，准备平仓
- ⏰ 16:05 - 对账，检查今日 P&L

**记录：**
- 记下今日的日 P&L、维持率、交易次数
- 如果一切正常，明天继续
- 3 天后根据 Sharpe 判断是否需要调整

---

**准备好了吗？**

我现在可以：
1. ✅ 帮你验证 Tiger API 连接
2. ✅ 生成启动日志文件
3. ✅ 准备监控脚本
4. ✅ 设置应急告警

说一声 "GO"，就启动！
