# 飞书长连接配置指南

## 问题分析
虽然测试脚本显示连接成功，但飞书后台显示"应用未建立长连接"，这是因为：

1. **需要在飞书开放平台配置事件订阅**
2. **长连接需要持续运行，不能只是测试**
3. **需要正确的应用权限配置**

## 解决步骤

### 步骤1：在飞书开放平台配置事件订阅

1. 登录飞书开放平台：https://open.feishu.cn/app
2. 找到您的应用（APP_ID: `cli_a92adfa4a478dbc2`）
3. 进入"事件订阅"页面
4. 配置以下事件：
   - **接收消息 v2.0** (im.message.receive_v2)
   - **机器人被添加到群组** (im.chat.member.user.added_v2)
   - **机器人被移出群组** (im.chat.member.user.deleted_v2)

### 步骤2：配置长连接模式

1. 在事件订阅页面，选择"长连接模式"
2. 确保应用有以下权限：
   - `im:message` (发送消息)
   - `im:message:group_at_msg` (群组@消息)
   - `im:chat` (获取群组信息)

### 步骤3：集成到主应用

需要在 `main.py` 中启动飞书长连接：

```python
# 在 lifespan 函数的 startup 部分添加
# Start Feishu long connection
try:
    feishu_success = await start_feishu_long_connection()
    if feishu_success:
        logger.info("✅ Feishu long connection started")
    else:
        logger.warning("⚠️ Feishu long connection failed to start")
except Exception as e:
    logger.error(f"Failed to start Feishu long connection: {e}")

# 在 lifespan 函数的 shutdown 部分添加
# Stop Feishu long connection
try:
    await stop_feishu_long_connection()
    logger.info("Feishu long connection stopped")
except Exception as e:
    logger.error(f"Failed to stop Feishu long connection: {e}")
```

### 步骤4：启动应用并保持运行

```bash
# 启动应用
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**重要**：应用必须持续运行，长连接才能保持活跃。

## 验证步骤

### 1. 检查连接日志
启动应用后，查看日志中是否有：
```
[Lark] connected to wss://msg-frontier.feishu.cn/ws/v2...
```

### 2. 检查飞书后台
- 进入飞书开放平台
- 查看应用的事件订阅状态
- 应该显示"长连接已建立"

### 3. 测试消息接收
- 在飞书中给机器人发送消息
- 检查应用日志中是否收到消息事件

## 常见问题

### Q1: 连接成功但后台显示未建立？
**A**: 需要在飞书开放平台配置事件订阅，选择长连接模式。

### Q2: 如何保持长连接持续运行？
**A**: 应用必须持续运行，建议使用进程管理工具如 `supervisor` 或 `systemd`。

### Q3: 长连接断开怎么办？
**A**: 飞书SDK会自动重连，但需要应用保持运行状态。

## 配置文件位置

需要更新的文件：
- `c:\Users\Zhong\.openclaw\StockQueen\StockQueen\app\main.py`
- `c:\Users\Zhong\.openclaw\StockQueen\StockQueen\.env`

## 环境变量确认

确保 `.env` 文件包含：
```
FEISHU_APP_ID=cli_a92adfa4a478dbc2
FEISHU_APP_SECRET=qMRcayluxSTqYxyuSQT9tbB6DGUsVRWp
```

## 下一步

1. 在飞书开放平台配置事件订阅
2. 更新 `main.py` 集成飞书长连接
3. 启动应用并保持运行
4. 验证飞书后台显示长连接状态
