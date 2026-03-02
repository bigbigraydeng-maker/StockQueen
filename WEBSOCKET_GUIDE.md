# StockQueen V1 - WebSocket 长连接配置指南

## 🎯 概述

StockQueen 现在支持 **Tiger Open API WebSocket 长连接**，提供实时行情数据推送功能。相比传统的 HTTP 轮询，WebSocket 长连接具有以下优势：

- ✅ **实时性**: 毫秒级数据推送，无延迟
- ✅ **高效性**: 单向长连接，减少网络开销
- ✅ **稳定性**: 自动重连机制，断线自动恢复
- ✅ **扩展性**: 支持多股票同时订阅

---

## 📡 WebSocket 架构

```
┌─────────────────┐      WebSocket       ┌─────────────────┐
│   StockQueen    │ ◄──────────────────► │  Tiger Open API  │
│                 │   Real-time Stream   │                 │
│ - Subscriptions │                      │ - Market Data    │
│ - Price Cache   │                      │ - Trade Updates  │
│ - Callbacks     │                      │ - Quote Updates  │
└─────────────────┘                      └─────────────────┘
         │
         │ REST API
         ▼
┌─────────────────┐
│   Web UI/App    │
│  /api/websocket │
└─────────────────┘
```

---

## ⚙️ 配置步骤

### 1. 环境变量配置

在 `.env` 文件中添加以下配置（已自动配置）：

```env
# ============================================
# WebSocket Configuration (Real-time Market Data)
# ============================================
# Tiger Open API WebSocket URL
# Sandbox (Development): wss://openapi-sandbox.itiger.com:443/ws
# Production (Live Trading): wss://openapi.itiger.com:443/ws
TIGER_WS_URL=wss://openapi-sandbox.itiger.com:443/ws

# WebSocket Settings
WS_PING_INTERVAL=30
WS_RECONNECT_DELAY=5
WS_MAX_RECONNECT_ATTEMPTS=10
```

**注意事项：**
- 开发环境使用 Sandbox URL
- 生产环境使用 Production URL
- 确保 `TIGER_ACCESS_TOKEN` 和 `TIGER_TIGER_ID` 已正确配置

---

### 2. 安装依赖

```bash
# 安装新的 WebSocket 依赖
pip install websockets==12.0 websocket-client==1.7.0

# 或者使用 requirements.txt
pip install -r requirements.txt
```

---

### 3. 启动 WebSocket 服务

WebSocket 长连接会在应用启动时自动初始化：

```bash
# 启动 StockQueen
python start.bat  # Windows
./start.sh        # Linux/Mac

# 或使用 uvicorn 直接启动
uvicorn app.main:app --reload
```

启动成功后，你会看到日志：
```
✅ WebSocket client started - Real-time market data streaming active
```

---

## 🚀 使用 WebSocket API

### 订阅股票实时行情

```bash
# 订阅 AAPL
curl -X POST http://localhost:8000/api/websocket/subscribe \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL"}'

# 响应
{
  "success": true,
  "message": "Successfully subscribed to AAPL",
  "ticker": "AAPL"
}
```

### 批量订阅

```bash
# 订阅多只股票
curl -X POST http://localhost:8000/api/websocket/watchlist/batch-subscribe \
  -H "Content-Type: application/json" \
  -d '["AAPL", "TSLA", "MSFT", "GOOGL"]'
```

### 取消订阅

```bash
# 取消订阅
curl -X POST http://localhost:8000/api/websocket/unsubscribe \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL"}'
```

### 获取订阅列表

```bash
# 查看当前订阅的所有股票
curl http://localhost:8000/api/websocket/watchlist

# 响应
{
  "tickers": ["AAPL", "TSLA", "MSFT"],
  "count": 3
}
```

### 获取实时价格

```bash
# 获取所有缓存的价格
curl http://localhost:8000/api/websocket/prices

# 获取特定股票的价格
curl http://localhost:8000/api/websocket/prices/AAPL

# 响应
{
  "ticker": "AAPL",
  "price": 185.92,
  "change": 2.15,
  "change_percent": 1.17,
  "volume": 52436891,
  "timestamp": "2026-02-27T16:45:30.123456"
}
```

### 查看 WebSocket 连接状态

```bash
# 检查连接状态
curl http://localhost:8000/api/websocket/status

# 响应
{
  "connected": true,
  "running": true,
  "reconnect_attempts": 0,
  "subscribed_tickers": ["AAPL", "TSLA"],
  "watchlist_count": 2,
  "cached_prices_count": 2,
  "websocket_url": "wss://openapi-sandbox.itiger.com:443/ws"
}
```

---

## 🧪 测试 WebSocket 连接

运行测试脚本验证长连接是否正常工作：

```bash
python test_websocket.py
```

测试内容包括：
1. ✅ WebSocket 连接建立
2. ✅ 股票订阅功能
3. ✅ 实时数据接收
4. ✅ 自动重连机制

---

## 📊 WebSocket 与 HTTP 对比

| 特性 | HTTP 轮询 | WebSocket 长连接 |
|------|-----------|------------------|
| 延迟 | 1-5 秒 | <100 毫秒 |
| 网络开销 | 高（频繁请求） | 低（单次连接） |
| 实时性 | 较差 | 极佳 |
| 服务器负载 | 高 | 低 |
| 复杂度 | 简单 | 中等 |
| 适用场景 | 低频数据 | 高频实时数据 |

---

## 🔧 高级配置

### 自定义重连策略

编辑 `app/services/websocket_service.py` 中的 `WebSocketConfig`：

```python
@dataclass
class WebSocketConfig:
    PING_INTERVAL = 30       # 心跳间隔（秒）
    RECONNECT_DELAY = 5      # 重连延迟（秒）
    MAX_RECONNECT_ATTEMPTS = 10  # 最大重连次数
    CONNECTION_TIMEOUT = 30  # 连接超时（秒）
```

### 自定义回调函数

```python
from app.services.websocket_service import get_realtime_service

async def my_callback(data):
    ticker = data.get("ticker")
    price = data.get("price")
    print(f"{ticker}: ${price}")

service = get_realtime_service()
service.on_price_change("AAPL", my_callback)
```

---

## ⚠️ 故障排除

### 问题 1: 连接失败

**症状**: WebSocket 无法连接

**解决方案**:
1. 检查网络连接
2. 验证 `TIGER_ACCESS_TOKEN` 是否有效
3. 确认 Tiger API 服务状态
4. 检查防火墙设置（端口 443）

### 问题 2: 数据不更新

**症状**: 订阅成功但收不到数据

**解决方案**:
1. 确认股票代码正确（大写）
2. 检查是否是交易时间
3. 查看日志中的错误信息
4. 尝试重新订阅

### 问题 3: 频繁断线

**症状**: 连接不稳定，频繁重连

**解决方案**:
1. 检查网络稳定性
2. 调整 `WS_PING_INTERVAL`（缩短心跳间隔）
3. 增加 `WS_MAX_RECONNECT_ATTEMPTS`
4. 联系 Tiger API 技术支持

---

## 📈 性能优化建议

1. **合理订阅数量**: 建议同时订阅不超过 50 只股票
2. **使用缓存**: 通过 `/api/websocket/prices` 获取缓存数据，减少重复查询
3. **批量操作**: 使用批量订阅接口一次性订阅多只股票
4. **监控连接**: 定期检查 `/api/websocket/status` 确保连接正常

---

## 🔗 API 参考

完整 API 文档启动后访问：
```
http://localhost:8000/docs
```

WebSocket 相关端点：
- `POST /api/websocket/subscribe` - 订阅股票
- `POST /api/websocket/unsubscribe` - 取消订阅
- `GET /api/websocket/watchlist` - 获取订阅列表
- `GET /api/websocket/prices` - 获取所有价格
- `GET /api/websocket/prices/{ticker}` - 获取特定股票价格
- `GET /api/websocket/status` - 获取连接状态
- `POST /api/websocket/watchlist/batch-subscribe` - 批量订阅
- `DELETE /api/websocket/watchlist/clear` - 清空订阅列表

---

## ✅ 配置完成！

WebSocket 长连接配置完成！你现在可以：

1. 启动 StockQueen 服务
2. 通过 API 订阅感兴趣的股票
3. 接收毫秒级实时行情推送
4. 享受更高效的市场数据服务

**下一步**: 运行 `python test_websocket.py` 验证配置！