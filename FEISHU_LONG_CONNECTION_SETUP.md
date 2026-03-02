# 飞书长连接配置详细步骤 - 方案B

## 📋 配置清单

### 1. 飞书开放平台配置

#### 步骤1：登录飞书开放平台
1. 打开浏览器，访问：https://open.feishu.cn/app
2. 使用您的飞书账号登录

#### 步骤2：找到应用
1. 在应用列表中找到应用ID：`cli_a92adfa4a478dbc2`
2. 点击进入应用详情页面

#### 步骤3：配置事件订阅
1. 在左侧菜单中找到"事件订阅"
2. 点击"配置事件订阅"
3. 选择"长连接模式"
4. 订阅以下事件：
   - ✅ `im.message.receive_v2`（接收消息 v2.0）
   - ✅ `im.chat.member.user.added_v2`（机器人被添加到群组）
   - ✅ `im.chat.member.user.deleted_v2`（机器人被移出群组）

#### 步骤4：配置应用权限
1. 在左侧菜单中找到"权限管理"
2. 添加以下权限：
   - ✅ `im:message`（发送消息）
   - ✅ `im:message:group_at_msg`（群组@消息）
   - ✅ `im:chat`（获取群组信息）
3. 点击"申请权限"并等待审核通过

#### 步骤5：发布应用
1. 在应用详情页面，点击"发布应用"
2. 选择"企业自建应用"
3. 填写应用信息并提交审核

### 2. 本地配置验证

#### 步骤1：检查环境变量
确保 `.env` 文件包含以下配置：
```
FEISHU_APP_ID=cli_a92adfa4a478dbc2
FEISHU_APP_SECRET=qMRcayluxSTqYxyuSQT9tbB6DGUsVRWp
```

#### 步骤2：测试长连接
运行测试脚本：
```bash
python test_feishu_long_connection.py
```

预期输出：
```
============================================================
Feishu Long Connection Test
============================================================
Starting Feishu long connection...
✅ Long connection started successfully
Connection status: True

Keeping connection alive for 30 seconds...
Check Feishu backend for long connection events
[Lark] connected to wss://msg-frontier.feishu.cn/ws/v2...
Connection active for 30 seconds...
```

#### 步骤3：启动应用
启动StockQueen应用并保持运行：
```bash
cd c:\Users\Zhong\.openclaw\StockQueen\StockQueen
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 3. 验证长连接状态

#### 步骤1：检查应用日志
启动应用后，查看日志中是否有：
```
[Lark] connected to wss://msg-frontier.feishu.cn/ws/v2...
```

#### 步骤2：检查飞书后台
1. 登录飞书开放平台
2. 进入应用详情页面
3. 查看"事件订阅"状态
4. 应该显示"长连接已建立"

#### 步骤3：测试消息接收
1. 在飞书中给机器人发送消息
2. 检查应用日志中是否收到消息事件
3. 验证消息处理是否正常

### 4. 保持长连接运行

#### 重要提示
- **应用必须持续运行**：长连接需要应用保持运行状态
- **自动重连机制**：飞书SDK会自动重连，但应用不能停止
- **建议使用进程管理工具**：
  - Windows: 使用 `nssm` 或 `winsw`
  - Linux: 使用 `systemd` 或 `supervisor`

#### Windows服务配置示例（可选）
使用 `nssm` 将应用注册为Windows服务：
```bash
nssm install StockQueen "C:\Python\python.exe" "C:\Users\Zhong\.openclaw\StockQueen\StockQueen\main.py"
nssm set StockQueen AppDirectory "C:\Users\Zhong\.openclaw\StockQueen\StockQueen"
nssm set StockQueen DisplayName "StockQueen Trading System"
nssm set StockQueen Description "AI-driven investment signal system"
nssm start StockQueen
```

### 5. 故障排除

#### 问题1：长连接无法建立
**解决方案**：
1. 检查网络连接
2. 确认APP_ID和APP_SECRET正确
3. 检查飞书开放平台的事件订阅配置
4. 查看应用日志中的错误信息

#### 问题2：长连接频繁断开
**解决方案**：
1. 检查网络稳定性
2. 确认应用持续运行
3. 检查防火墙设置
4. 查看飞书SDK的重连日志

#### 问题3：飞书后台显示未建立长连接
**解决方案**：
1. 确认在飞书开放平台配置了事件订阅
2. 确认选择了"长连接模式"
3. 确认应用正在运行
4. 检查应用日志中是否有连接成功的日志

### 6. 配置完成检查清单

- [ ] 飞书开放平台配置了事件订阅
- [ ] 选择了"长连接模式"
- [ ] 订阅了相关事件（im.message.receive_v2等）
- [ ] 配置了应用权限（im:message等）
- [ ] 应用已发布
- [ ] 环境变量配置正确（FEISHU_APP_ID和FEISHU_APP_SECRET）
- [ ] 测试长连接成功
- [ ] 应用持续运行
- [ ] 飞书后台显示长连接已建立
- [ ] 消息接收测试通过

## 🎯 配置完成后的功能

配置完成后，StockQueen系统将能够：
- ✅ 通过飞书长连接接收消息
- ✅ 实时处理飞书事件
- ✅ 发送投资信号通知
- ✅ 发送交易执行确认
- ✅ 发送风险警报

## 📞 技术支持

如果在配置过程中遇到问题，请提供：
1. 飞书开放平台的配置截图
2. 应用日志文件内容
3. 错误信息详情

我会帮您诊断并解决问题。
