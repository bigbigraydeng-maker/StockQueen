# StockQueen - OpenClaw 接入指南

## 📋 概述

OpenClaw是一个开源的AI工具，支持多种IM平台（飞书、企业微信、钉钉等）的集成。StockQueen可以通过OpenClaw发送交易信号和通知。

## 🎯 接入目标

将StockQueen的交易信号、风险警报和系统通知通过OpenClaw发送到你的IM平台（飞书、企业微信等）。

## 🚀 接入步骤

### 步骤1: 部署OpenClaw

#### 方法1: 使用Docker部署（推荐）

```bash
# 拉取OpenClaw镜像
docker pull openclaw/openclaw:latest

# 运行OpenClaw容器
docker run -d \
  --name openclaw \
  -p 8080:8080 \
  -v openclaw_data:/app/data \
  openclaw/openclaw:latest
```

#### 方法2: 使用阿里云一键部署

1. 访问阿里云市场
2. 搜索"OpenClaw"
3. 选择"OpenClaw一键部署镜像"
4. 按照向导完成部署

#### 方法3: 本地部署

```bash
# 克隆OpenClaw仓库
git clone https://github.com/openclaw/openclaw.git
cd openclaw

# 安装依赖
npm install

# 配置环境变量
cp .env.example .env
# 编辑.env文件

# 启动服务
npm start
```

### 步骤2: 配置IM平台

#### 飞书接入

1. 登录OpenClaw管理后台（通常是 http://localhost:8080）
2. 进入 **平台管理** > **飞书**
3. 点击 **添加飞书应用**
4. 填写配置：
   - **应用名称**: StockQueen Bot
   - **应用ID**: `cli_a92adfa4a478dbc2`
   - **应用密钥**: `qMRcayluxSTqYxyuSQT9tbB6DGUsVRWp`
   - **事件订阅**: 启用
   - **长连接**: 启用
5. 点击 **保存**

#### 企业微信接入

1. 进入 **平台管理** > **企业微信**
2. 点击 **添加企业微信应用**
3. 填写企业微信应用配置
4. 点击 **保存**

#### 钉钉接入

1. 进入 **平台管理** > **钉钉**
2. 点击 **添加钉钉应用**
3. 填写钉钉应用配置
4. 点击 **保存**

### 步骤3: 创建Webhook

1. 进入 **Webhook管理**
2. 点击 **创建Webhook**
3. 填写配置：
   - **名称**: StockQueen Notifications
   - **描述**: 接收StockQueen的交易信号和通知
   - **目标平台**: 选择你的IM平台（飞书/企业微信/钉钉）
   - **目标群组**: 选择接收通知的群组
   - **消息格式**: JSON
4. 点击 **创建**
5. 复制生成的Webhook URL

**Webhook URL格式示例：**
```
http://localhost:8080/api/webhook/{webhook-id}
```

### 步骤4: 配置StockQueen

1. 编辑StockQueen的 `.env` 文件
2. 添加或修改以下配置：

```env
# OpenClaw Webhook URL
OPENCLAW_WEBHOOK_URL=http://localhost:8080/api/webhook/{your-webhook-id}

# 或者使用公网URL（如果OpenClaw部署在服务器上）
# OPENCLAW_WEBHOOK_URL=https://your-domain.com/api/webhook/{your-webhook-id}
```

3. 重启StockQueen服务

```bash
# Windows
# 停止当前服务，然后重新启动
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 步骤5: 测试连接

1. 在StockQueen中发送测试通知

```bash
# 使用curl测试
curl -X POST http://localhost:8000/api/test/notification \
  -H "Content-Type: application/json" \
  -d '{"message": "Test notification from StockQueen"}'
```

2. 检查OpenClaw日志
3. 检查IM平台是否收到消息

## 📊 消息格式

StockQueen发送到OpenClaw的消息格式：

### 交易信号通知

```json
{
  "type": "signal",
  "title": "StockQueen - New Trading Signal",
  "ticker": "MRNA",
  "direction": "long",
  "entry_price": 120.50,
  "stop_loss": 115.00,
  "target_price": 140.00,
  "reason": "FDA approval announcement",
  "timestamp": "2026-02-27T12:00:00Z"
}
```

### 风险警报

```json
{
  "type": "risk_alert",
  "title": "StockQueen - Risk Alert",
  "alert_type": "max_drawdown",
  "details": "Maximum drawdown limit reached: 15.2%",
  "timestamp": "2026-02-27T12:00:00Z"
}
```

### 交易确认

```json
{
  "type": "trade_confirmation",
  "title": "StockQueen - Trade Executed",
  "ticker": "MRNA",
  "direction": "long",
  "entry_price": 120.50,
  "order_id": "ORDER123456",
  "timestamp": "2026-02-27T12:00:00Z"
}
```

## 🔧 代码修改

如果需要修改StockQueen以支持OpenClaw，可以参考以下代码：

### 1. 添加OpenClaw客户端

在 `app/services/notification_service.py` 中添加：

```python
class OpenClawClient:
    """OpenClaw webhook client"""
    
    def __init__(self):
        self.webhook_url = settings.openclaw_webhook_url
    
    async def send_notification(self, message_type: str, data: dict) -> bool:
        """Send notification via OpenClaw"""
        if not self.webhook_url:
            logger.warning("OPENCLAW_WEBHOOK_URL not configured")
            return False
        
        payload = {
            "type": message_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                    timeout=10
                )
                response.raise_for_status()
                
                logger.info(f"OpenClaw notification sent: {message_type}")
                return True
                
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenClaw HTTP error: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Error sending OpenClaw notification: {e}")
            return False
```

### 2. 更新NotificationService

```python
class NotificationService:
    """Main notification service"""
    
    def __init__(self):
        self.twilio = TwilioClient()
        self.feishu = FeishuClient()
        self.openclaw = OpenClawClient()  # 添加OpenClaw客户端
    
    async def send_signal_summary(self, signals: List[Signal]) -> bool:
        """Send daily signal summary via OpenClaw"""
        if not signals:
            data = {
                "title": "StockQueen Daily Report",
                "content": "No signals generated today."
            }
        else:
            data = {
                "title": "StockQueen Daily Report",
                "signals_count": len(signals),
                "signals": [
                    {
                        "ticker": s.ticker,
                        "direction": s.direction,
                        "entry": s.entry_price,
                        "stop": s.stop_loss,
                        "target": s.target_price
                    }
                    for s in signals
                ]
            }
        
        return await self.openclaw.send_notification("signal_summary", data)
```

## 🧪 测试

### 测试1: 发送测试消息

```python
# test_openclaw.py
import asyncio
import httpx

async def test_openclaw():
    webhook_url = "http://localhost:8080/api/webhook/{your-webhook-id}"
    
    payload = {
        "type": "test",
        "message": "Test notification from StockQueen",
        "timestamp": "2026-02-27T12:00:00Z"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(webhook_url, json=payload)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")

asyncio.run(test_openclaw())
```

### 测试2: 测试信号通知

```python
# test_signal_notification.py
import asyncio
from app.services.notification_service import NotificationService
from app.models import Signal

async def test_signal_notification():
    service = NotificationService()
    
    # 创建测试信号
    signal = Signal(
        ticker="MRNA",
        direction="long",
        entry_price=120.50,
        stop_loss=115.00,
        target_price=140.00,
        reason="FDA approval announcement"
    )
    
    # 发送信号通知
    result = await service.send_trade_confirmation(signal, "ORDER123456")
    print(f"Notification sent: {result}")

asyncio.run(test_signal_notification())
```

## 📝 配置检查清单

- [ ] OpenClaw已部署并运行
- [ ] IM平台已配置（飞书/企业微信/钉钉）
- [ ] Webhook已创建并复制URL
- [ ] StockQueen的.env文件已配置OPENCLAW_WEBHOOK_URL
- [ ] StockQueen服务已重启
- [ ] 测试消息已发送并成功接收

## 🔍 故障排查

### 问题1: OpenClaw无法接收消息

**检查项：**
1. OpenClaw服务是否运行
2. Webhook URL是否正确
3. 网络连接是否正常
4. StockQueen日志中是否有错误

**解决方法：**
```bash
# 检查OpenClaw日志
docker logs openclaw

# 测试Webhook连接
curl -X POST http://localhost:8080/api/webhook/{webhook-id} \
  -H "Content-Type: application/json" \
  -d '{"test": "message"}'
```

### 问题2: IM平台没有收到消息

**检查项：**
1. IM平台配置是否正确
2. 目标群组是否正确
3. 消息格式是否正确

**解决方法：**
1. 检查OpenClaw管理后台的日志
2. 检查IM平台的机器人权限
3. 确认机器人已添加到目标群组

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

## 📚 参考资源

- OpenClaw官方文档: https://github.com/openclaw/openclaw
- OpenClaw部署指南: https://openclaw.io/docs/deployment
- StockQueen项目文档: ./README.md

## 🆘 获取帮助

如果遇到问题：
1. 查看OpenClaw日志
2. 查看StockQueen日志
3. 参考故障排查部分
4. 联系OpenClaw社区支持

## 🎉 完成

完成以上步骤后，StockQueen将能够通过OpenClaw向你的IM平台发送交易信号和通知！
