# StockQueen V1 - Feishu 长连接配置指南

## 🎯 概述

Feishu 开放平台应用需要通过 **WebSocket 长连接** 接收事件推送。本指南将帮助你配置 `cli_a92adfa4a478dbc2` 应用的长连接。

---

## 📡 两种连接方式对比

| 方式 | 使用场景 | 实时性 | 配置复杂度 |
|------|----------|--------|------------|
| **WebSocket 长连接** | 自建应用接收事件 | 实时 | 中等 |
| **Webhook 回调地址** | 有公网服务器的应用 | 实时 | 简单 |

StockQueen 使用的是 **WebSocket 长连接** 方式。

---

## ⚙️ 配置步骤

### 步骤 1: 确认应用凭证

你的应用信息（已配置在 `.env` 中）：

```env
FEISHU_APP_ID=cli_a92adfa4a478dbc2
FEISHU_APP_SECRET=qMRcayluxSTqYxyuSQT9tbB6DGUsVRWp
```

**注意**: `cli_a92adfa4a478dbc2` 既是 **Webhook ID** 也是 **App ID**。

---

### 步骤 2: 配置事件订阅

1. 登录 [Feishu 开放平台](https://open.feishu.cn/app)
2. 找到应用 `cli_a92adfa4a478dbc2`
3. 点击左侧菜单 **"事件订阅"**
4. 选择 **"长连接"** 方式

---

### 步骤 3: 启动 StockQueen 服务

```bash
cd C:\Users\Zhong\Documents\trae_projects\StockQueen

# 方式 1: 一键启动
start_websocket.bat

# 方式 2: 直接启动
uvicorn app.main:app --reload
```

启动后，你会看到日志：
```
🔌 Connecting to Feishu Platform: wss://ws.feishu.cn/ws
✅ Feishu Platform WebSocket connected successfully!
✅ Feishu Platform event client started - Event subscription active
```

---

### 步骤 4: 验证连接

1. 在 Feishu 开放平台，刷新 **"事件订阅"** 页面
2. 连接状态应显示为 **"已连接"** ✅
3. 如果仍显示 **"未建立长连接"**，检查：
   - StockQueen 服务是否正常运行
   - `.env` 中的 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 是否正确
   - 网络连接是否正常

---

## 🧪 测试连接

运行测试脚本验证长连接：

```bash
python test_feishu_connection.py
```

测试内容：
1. ✅ 建立 WebSocket 连接
2. ✅ 发送验证挑战（Challenge）
3. ✅ 接收并处理事件
4. ✅ 自动重连机制

---

## 📋 订阅事件

### 常用事件类型

在 Feishu 开放平台的 **"事件订阅"** 页面，订阅以下事件：

| 事件 | 说明 |
|------|------|
| `im.message.receive_v1` | 接收私聊消息 |
| `im.message.group_msg` | 接收群聊消息 |
| `card.action.trigger` | 卡片交互事件 |

### 订阅方法

1. 在 **"事件订阅"** 页面
2. 点击 **"添加事件"**
3. 搜索并选择需要的事件
4. 点击 **"保存"**

---

## 🔧 故障排除

### 问题 1: 显示"应用未建立长连接"

**症状**: Feishu 平台显示未连接

**解决方案**:
1. 确认 StockQueen 服务已启动
2. 检查 `.env` 文件配置：
   ```env
   FEISHU_APP_ID=cli_a92adfa4a478dbc2
   FEISHU_APP_SECRET=qMRcayluxSTqYxyuSQT9tbB6DGUsVRWp
   ```
3. 检查日志输出是否有错误
4. 重启 StockQueen 服务

### 问题 2: 连接后很快断开

**症状**: 连接建立但很快断开

**解决方案**:
1. 检查网络稳定性
2. 查看是否有防火墙阻止 WebSocket 连接
3. 检查 Feishu App Secret 是否过期
4. 确认应用在 Feishu 平台的状态（已发布/测试中）

### 问题 3: 收不到事件

**症状**: 连接正常但收不到消息

**解决方案**:
1. 确认已订阅相关事件
2. 检查事件权限（应用是否有权限接收该事件）
3. 在 Feishu 中给机器人发送消息测试
4. 检查日志中的事件处理错误

---

## 💬 交互命令

连接成功后，可以在 Feishu 中与机器人交互：

| 命令 | 说明 |
|------|------|
| `status` / `状态` | 查看系统状态 |
| `signals` / `信号` | 查看当前交易信号 |
| `watchlist` / `关注` | 查看关注列表 |

---

## 📊 连接架构

```
┌─────────────────┐      WebSocket       ┌─────────────────┐
│   StockQueen    │ ◄──────────────────► │  Feishu Platform │
│                 │   Long Connection    │                 │
│ - Event Client  │                      │ - Message Events │
│ - Auto Reconnect│                      │ - Group Events   │
│ - Heartbeat     │                      │ - Card Actions   │
└─────────────────┘                      └─────────────────┘
         │
         │ Process
         ▼
┌─────────────────┐
│  Signal Engine  │
│  Trading Logic  │
└─────────────────┘
```

---

## 🎨 高级配置

### 自定义事件处理器

编辑 `app/services/feishu_event_service.py`：

```python
async def _handle_message(self, event: dict):
    """自定义消息处理逻辑"""
    # 获取消息内容
    message = event.get("event", {}).get("message", {})
    content = json.loads(message.get("content", "{}"))
    text = content.get("text", "")
    
    # 自定义响应逻辑
    if text == "我的策略":
        await self._send_user_strategy(user_id)
    elif text == "市场行情":
        await self._send_market_overview(user_id)
```

### 连接参数调整

编辑 `app/services/feishu_event_service.py`：

```python
class FeishuPlatformConfig:
    PING_INTERVAL = 30        # 心跳间隔（秒）
    RECONNECT_DELAY = 5       # 重连延迟（秒）
    MAX_RECONNECT_ATTEMPTS = 10  # 最大重连次数
```

---

## ✅ 配置完成检查清单

- [x] `.env` 文件配置正确
- [x] StockQueen 服务已启动
- [x] Feishu 平台显示"已连接"
- [x] 已订阅需要的事件
- [x] 测试脚本运行成功
- [x] 可以与机器人交互

---

## 📚 相关文档

| 文档 | 路径 |
|------|------|
| Feishu 开放平台 | https://open.feishu.cn |
| WebSocket 配置 | `WEBSOCKET_GUIDE.md` |
| 项目主文档 | `README.md` |
| 测试脚本 | `test_feishu_connection.py` |

---

## ✅ 配置完成！

Feishu 长连接配置完成！你的应用 `cli_a92adfa4a478dbc2` 现在可以：

1. 📡 通过 WebSocket 长连接接收 Feishu 事件
2. 💬 实时响应用户消息
3. 🔄 自动重连保障稳定性
4. 🎛️ 自定义事件处理逻辑

**立即测试**: 在 Feishu 中给机器人发送消息 "status"，查看响应！

---

配置时间: 2026-02-27
应用 ID: cli_a92adfa4a478dbc2