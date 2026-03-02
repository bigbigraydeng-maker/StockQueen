# StockQueen 飞书无响应问题诊断报告

## 📊 问题诊断结果

### ✅ 排查1完成：还原通知服务

**状态**：✅ 已完成

**操作**：
- 注释掉了OpenClaw优先逻辑
- 恢复为直接走飞书webhook
- 修复了`openclaw_webhook_url`字段验证错误

**结果**：通知服务已还原为原始状态

---

### ❌ 排查2：飞书webhook连通性测试

**状态**：❌ 失败

**测试结果**：
```
状态码: 200
响应: {"code":19001,"data":{},"msg":"param invalid: incoming webhook access token invalid"}
```

**问题原因**：
- `cli_a92adfa4a478dbc2` 是**企业自建应用ID**
- 不是**webhook ID**
- 企业自建应用不能使用webhook URL发送消息

**飞书机器人类型**：
1. **自定义机器人**：使用webhook URL发送消息
   - Webhook URL格式：`https://open.feishu.cn/open-apis/bot/v2/hook/{webhook_id}`
   - 只能发送消息，不能接收消息

2. **企业自建应用**：使用API发送消息，通过长连接接收消息
   - App ID：`cli_a92adfa4a478dbc2`
   - 可以发送和接收消息
   - 需要配置事件订阅

**结论**：你的机器人是企业自建应用，需要使用飞书API发送消息。

---

### ✅ 排查3：飞书API测试

**状态**：✅ 成功

**测试结果**：
```
✅ 访问令牌获取成功: t-g1042r7RGUTUBJP3MK...
✅ 机器人名称: Stock Queen
✅ 机器人ID: ou_915d3acc198a98a7a6246cb3f5ee0e65
```

**结论**：飞书API凭证配置正确，可以正常获取访问令牌。

---

### ✅ 排查4：手动触发完整链路

**状态**：✅ 完成

**测试结果**：
```
News fetch result: {'total_fetched': 75, 'total_filtered': 0, 'total_stored': 0, 'errors': []}
Signal generation result: 0 signals generated
```

**第一层问题确认**：
- ✅ 新闻抓取成功：75条
- ❌ ticker提取失败：0条有效事件
- ❌ 信号生成：0个信号

**结论**：ticker提取失败导致没有信号生成，这是根本原因。

---

## 🔧 解决方案

### 问题1：ticker提取失败

**原因**：
- FDA新闻源不包含股票代码
- 需要使用预设股票池+新闻匹配

**解决方案**：
- ✅ 已实现pharma watchlist配置
- ✅ 已更新ticker提取逻辑
- ✅ 已修复RSS feed URL

**状态**：已实现，需要测试

### 问题2：飞书通知发送

**原因**：
- 企业自建应用不能使用webhook URL
- 需要使用飞书API发送消息

**解决方案**：
- ✅ 已实现飞书API客户端
- ✅ 已更新FeishuClient支持API和webhook两种模式
- ✅ 已添加`FEISHU_RECEIVE_ID`配置选项

**状态**：已实现，需要配置接收者ID

---

## 📋 下一步操作

### 1. 配置飞书接收者ID

**方法1：通过长连接获取**

1. 确保StockQueen正在运行
2. 在飞书中给机器人发送一条消息
3. 查看StockQueen日志，找到消息事件
4. 从日志中提取`sender_id`或`chat_id`

**方法2：通过飞书开放平台获取**

1. 登录飞书开放平台
2. 进入应用管理
3. 查看机器人信息
4. 获取机器人ID或测试群组ID

**配置示例**：
```env
# 在.env文件中添加
FEISHU_RECEIVE_ID=ou_your_user_id_or_oc_your_chat_id
```

### 2. 测试飞书通知

运行测试脚本：
```bash
python test_notification.py
```

### 3. 测试完整链路

运行数据抓取测试：
```bash
python manual_data_fetch.py
```

### 4. 配置飞书事件订阅（可选）

如果需要机器人接收消息：

1. 登录飞书开放平台
2. 进入事件与回调 > 事件配置
3. 配置事件订阅
4. 添加`im.message.receive_v1`事件
5. 发布应用

详细步骤参考：[FEISHU_EVENT_SUBSCRIPTION_GUIDE.md](./FEISHU_EVENT_SUBSCRIPTION_GUIDE.md)

---

## 🎯 预期结果

### 成功标志

1. ✅ 飞书收到测试消息
2. ✅ ticker提取成功
3. ✅ 信号生成成功
4. ✅ 飞书收到信号通知

### 日志示例

**成功的ticker提取**：
```
[NewsService] Found ticker via keyword 'Moderna': MRNA
[NewsService] Found ticker via company name 'Pfizer': PFE
```

**成功的信号生成**：
```
[SignalService] Generated LONG signal for MRNA at $120.50
[SignalService] Generated SHORT signal for PFE at $45.00
```

**成功的飞书通知**：
```
[FeishuClient] Feishu API notification sent: StockQueen - Trade Executed: MRNA
```

---

## 📚 参考文档

- [FEISHU_EVENT_SUBSCRIPTION_GUIDE.md](./FEISHU_EVENT_SUBSCRIPTION_GUIDE.md) - 飞书事件订阅配置指南
- [FEISHU_TROUBLESHOOTING_CHECKLIST.md](./FEISHU_TROUBLESHOOTING_CHECKLIST.md) - 飞书故障排查清单
- [OPENCLAW_INTEGRATION_GUIDE.md](./OPENCLAW_INTEGRATION_GUIDE.md) - OpenClaw集成指南
- [OPENCLAW_QUICKSTART.md](./OPENCLAW_QUICKSTART.md) - OpenClaw快速开始

---

## 🔍 当前状态总结

| 项目 | 状态 | 说明 |
|------|------|------|
| 飞书长连接 | ✅ 已建立 | WebSocket连接正常 |
| 飞书API凭证 | ✅ 已配置 | 可以获取访问令牌 |
| 飞书接收者ID | ❌ 未配置 | 需要手动配置 |
| ticker提取逻辑 | ✅ 已更新 | 使用预设股票池+新闻匹配 |
| 新闻抓取 | ✅ 正常 | 可以抓取75条新闻 |
| 信号生成 | ❌ 失败 | ticker提取失败导致0个信号 |
| 飞书通知 | ❌ 未测试 | 需要配置接收者ID后测试 |

---

## 🆘 需要帮助？

如果遇到问题：
1. 查看日志文件：`stockqueen.log`
2. 运行测试脚本：`test_notification.py`
3. 参考故障排查文档
4. 检查飞书开放平台配置

---

**报告生成时间**：2026-02-27
**StockQueen版本**：V1
**飞书应用ID**：cli_a92adfa4a478dbc2
