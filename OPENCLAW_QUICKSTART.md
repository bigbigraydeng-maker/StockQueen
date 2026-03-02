# StockQueen - OpenClaw 快速接入指南

## 🎯 目标

将StockQueen的交易信号和通知通过OpenClaw发送到你的IM平台（飞书、企业微信、钉钉等）。

## 📋 前置条件

- ✅ StockQueen已部署并运行
- ✅ OpenClaw已部署（或准备部署）
- ✅ 有一个IM平台账号（飞书/企业微信/钉钉）

## 🚀 快速开始（5分钟）

### 步骤1: 部署OpenClaw（如果还没有）

#### 使用Docker（推荐）

```bash
# 拉取镜像
docker pull openclaw/openclaw:latest

# 运行容器
docker run -d \
  --name openclaw \
  -p 8080:8080 \
  -v openclaw_data:/app/data \
  openclaw/openclaw:latest
```

#### 使用阿里云一键部署

1. 访问阿里云市场
2. 搜索"OpenClaw"
3. 选择"OpenClaw一键部署镜像"
4. 按照向导完成部署

### 步骤2: 配置IM平台

1. 访问OpenClaw管理后台（通常是 http://localhost:8080）
2. 进入 **平台管理**
3. 选择你的IM平台（飞书/企业微信/钉钉）
4. 按照向导完成配置

**飞书配置示例：**
- 应用名称: StockQueen Bot
- 应用ID: `cli_a92adfa4a478dbc2`
- 应用密钥: `qMRcayluxSTqYxyuSQT9tbB6DGUsVRWp`

### 步骤3: 创建Webhook

1. 进入OpenClaw的 **Webhook管理**
2. 点击 **创建Webhook**
3. 填写配置：
   - 名称: StockQueen Notifications
   - 目标平台: 选择你的IM平台
   - 目标群组: 选择接收通知的群组
4. 点击 **创建**
5. **复制生成的Webhook URL**

**Webhook URL示例：**
```
http://localhost:8080/api/webhook/abc123def456
```

### 步骤4: 配置StockQueen

1. 编辑StockQueen的 `.env` 文件
2. 添加以下配置：

```env
# OpenClaw Webhook URL
OPENCLAW_WEBHOOK_URL=http://localhost:8080/api/webhook/{你的webhook-id}
```

3. 重启StockQueen服务

```bash
# 停止当前服务（Ctrl+C）
# 重新启动
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 步骤5: 测试连接

运行测试脚本：

```bash
python test_openclaw.py
```

如果看到"✅ OpenClaw连接成功"，说明配置正确！

## 📊 验证

### 1. 检查StockQueen日志

```bash
# 查看最新日志
Get-Content "c:\Users\Zhong\.openclaw\StockQueen\StockQueen\stockqueen.log" -Tail 50
```

查找以下日志：
```
OpenClaw notification sent: signal_summary
OpenClaw notification sent: trade_confirmation
```

### 2. 检查OpenClaw日志

```bash
# 如果使用Docker
docker logs openclaw

# 如果使用本地部署
# 查看OpenClaw管理后台的日志
```

### 3. 检查IM平台

在飞书/企业微信/钉钉中查看是否收到测试消息。

## 🎉 完成！

现在StockQueen会自动通过OpenClaw发送以下通知：

- 📊 每日信号摘要
- ✅ 交易确认
- 🚨 风险警报
- ⚠️ 止损触发
- 📢 波动性警报

## 📚 更多信息

- 详细配置指南: [OPENCLAW_INTEGRATION_GUIDE.md](./OPENCLAW_INTEGRATION_GUIDE.md)
- OpenClaw官方文档: https://github.com/openclaw/openclaw
- StockQueen文档: [README.md](./README.md)

## 🔧 故障排查

### 问题1: 连接失败

**检查项：**
1. OpenClaw是否运行
2. Webhook URL是否正确
3. 网络连接是否正常

**解决方法：**
```bash
# 测试OpenClaw连接
curl http://localhost:8080/health

# 检查OpenClaw日志
docker logs openclaw
```

### 问题2: 没有收到消息

**检查项：**
1. IM平台配置是否正确
2. 目标群组是否正确
3. 机器人是否在群组中

**解决方法：**
1. 检查OpenClaw管理后台的日志
2. 确认机器人已添加到目标群组
3. 检查机器人权限

### 问题3: StockQueen发送失败

**检查项：**
1. OPENCLAW_WEBHOOK_URL是否配置
2. StockQueen服务是否运行
3. 网络连接是否正常

**解决方法：**
```bash
# 检查StockQueen日志
Get-Content "c:\Users\Zhong\.openclaw\StockQueen\StockQueen\stockqueen.log" -Tail 100

# 测试StockQueen API
curl http://localhost:8000/health
```

## 🆘 获取帮助

如果遇到问题：
1. 查看详细配置指南: [OPENCLAW_INTEGRATION_GUIDE.md](./OPENCLAW_INTEGRATION_GUIDE.md)
2. 查看故障排查部分
3. 检查日志文件
4. 联系OpenClaw社区支持

## 📞 联系方式

- OpenClaw GitHub: https://github.com/openclaw/openclaw
- OpenClaw文档: https://openclaw.io/docs
- StockQueen文档: [README.md](./README.md)
