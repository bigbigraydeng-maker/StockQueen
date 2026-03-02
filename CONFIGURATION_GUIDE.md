# StockQueen V1 - 详细配置指南

## 📝 配置步骤

---

## 1. Supabase 配置

### 步骤 1: 创建 Supabase 项目
1. 访问 https://supabase.com
2. 点击 "Start your project"
3. 登录或创建账户
4. 点击 "New Project"
5. 填写项目信息：
   - **Project Name**: StockQueen
   - **Database Password**: 输入强密码
   - **Region**: 选择 Asia Pacific (Singapore) 或 closest
   - **Plan**: 选择 Free 方案
6. 点击 "Create new project"

### 步骤 2: 获取 API 密钥
1. 项目创建后，等待 2-3 分钟初始化完成
2. 在左侧菜单点击 "Settings"
3. 点击 "API"
4. 复制以下信息到 `.env` 文件：
   - **Project URL**: 复制到 `SUPABASE_URL`
   - **service_role Key**: 复制到 `SUPABASE_SERVICE_KEY`

### 步骤 3: 运行数据库结构
1. 在左侧菜单点击 "SQL Editor"
2. 点击 "New Query"
3. 打开 `database/schema.sql` 文件
4. 复制全部内容到 Supabase SQL 编辑器
5. 点击 "Run"
6. 看到 "Successfully executed" 表示完成

---

## 2. DeepSeek AI 配置

### 步骤 1: 获取 DeepSeek API 密钥
1. 访问 https://platform.deepseek.com
2. 点击 "Sign in" 或 "Sign up"
3. 登录后，在左侧菜单点击 "API Keys"
4. 点击 "Create new key"
5. 输入名称 "StockQueen"
6. 选择适当的权限
7. 点击 "Create"
8. 复制生成的 API 密钥到 `.env` 文件的 `DEEPSEEK_API_KEY`

### 步骤 2: 验证 API 可用性
- 确保选择的模型是 `deepseek-chat`（已在配置中设置）

---

## 3. Tiger 证券 API 配置

### 步骤 1: 开通 API 权限
1. 登录 Tiger 证券官网或 App
2. 进入 "Account Settings" → "API Management"
3. 点击 "Apply for API"
4. 填写申请信息
5. 完成身份验证
6. 等待审核通过（1-2 个工作日）

### 步骤 2: 获取 API 凭证
1. 审核通过后，在 API 管理页面查看
2. 复制以下信息到 `.env` 文件：
   - **Access Token**: 复制到 `TIGER_ACCESS_TOKEN`
   - **Tiger ID**: 复制到 `TIGER_TIGER_ID`
   - **Account Number**: 复制到 `TIGER_ACCOUNT`

### 步骤 3: 配置 API 权限
- 确保 API 有 "Market Data" 和 "Trading" 权限
- 配置适当的 IP 白名单（如果需要）

---

## 4. Twilio 配置

### 步骤 1: 创建 Twilio 账户
1. 访问 https://www.twilio.com
2. 点击 "Sign up"
3. 填写注册信息
4. 验证邮箱和手机

### 步骤 2: 获取账户信息
1. 登录后，在控制台首页查看
2. 复制以下信息到 `.env` 文件：
   - **Account SID**: 复制到 `TWILIO_ACCOUNT_SID`
   - **Auth Token**: 复制到 `TWILIO_AUTH_TOKEN`

### 步骤 3: 获取电话号码
1. 在左侧菜单点击 "Phone Numbers"
2. 点击 "Buy a number"
3. 选择一个美国号码（+1 开头）
4. 完成购买
5. 复制号码到 `.env` 文件的 `TWILIO_PHONE_FROM`
6. 在 `TWILIO_PHONE_TO` 中填写你的手机号码（+64 开头）

---

## 4. OpenClaw 配置

### 步骤 1: 获取 OpenClaw Webhook URL
1. 访问 https://www.openclaw.io
2. 登录或创建账户
3. 在左侧菜单点击 "Webhooks"
4. 点击 "Create New Webhook"
5. 填写配置：
   - **Name**: StockQueen Notifications
   - **Description**: Daily trading signals and alerts
   - **Event Types**: Select all relevant event types
   - **Security**: Set up appropriate security (if needed)
6. 点击 "Create"
7. 复制生成的 Webhook URL 到 `.env` 文件的 `OPENCLAW_WEBHOOK_URL`

### 步骤 2: 验证 Webhook 格式
- **正确格式**: `https://api.openclaw.io/v1/webhook/{your-webhook-id}`
- **示例**: `https://api.openclaw.io/v1/webhook/abc123def456`

---

## 5. 启动系统

### 步骤 1: 安装依赖
```bash
# Windows
.tart.bat

# Linux/Mac
chmod +x start.sh
./start.sh
```

### 步骤 2: 验证启动
- 访问 http://localhost:8000
- 看到 StockQueen 欢迎页面表示成功

### 步骤 3: 测试系统
```bash
# 测试 API 端点
python scripts/test_api.py

# 测试新闻抓取
python scripts/test_news_fetch.py

# 测试 AI 分类
python scripts/test_ai_classification.py
```

---

## 6. 常见问题

### 问题 1: 数据库连接失败
**解决方案**:
- 检查 `SUPABASE_URL` 和 `SUPABASE_SERVICE_KEY` 是否正确
- 确保 Supabase 项目状态为 "Active"
- 检查网络连接

### 问题 2: DeepSeek API 错误
**解决方案**:
- 检查 `DEEPSEEK_API_KEY` 是否正确
- 访问 https://platform.deepseek.com 检查 API 配额
- 确保网络可以访问 DeepSeek API

### 问题 3: Tiger API 错误
**解决方案**:
- 检查 `TIGER_ACCESS_TOKEN` 和 `TIGER_TIGER_ID` 是否正确
- 确保 API 权限已开通
- 检查 Tiger API 文档中的正确端点

### 问题 4: Twilio SMS 发送失败
**解决方案**:
- 检查 `TWILIO_ACCOUNT_SID` 和 `TWILIO_AUTH_TOKEN` 是否正确
- 确保电话号码已验证
- 检查 Twilio 账户余额

---

## 7. 快速参考

### 关键配置项

| 配置项 | 格式 | 示例 |
|---------|---------|---------|
| `SUPABASE_URL` | `https://<project>.supabase.co` | `https://abc123.supabase.co` |
| `SUPABASE_SERVICE_KEY` | `****************************************************************************************************************************************************************************************************************************************************************************` | 长字符串 |
| `DEEPSEEK_API_KEY` | `sk-****************************************************************************************************************************************************************************************************************************************************************************` | 以 `sk-` 开头 |
| `TIGER_ACCESS_TOKEN` | `****************************************************************************************************************************************************************************************************************************************************************************` | 长字符串 |
| `TIGER_TIGER_ID` | `Tiger********` | 以 `Tiger` 开头 |
| `TIGER_ACCOUNT` | `********` | 数字 |
| `TWILIO_ACCOUNT_SID` | `AC********************************` | 以 `AC` 开头 |
| `TWILIO_AUTH_TOKEN` | `********************************` | 长字符串 |
| `TWILIO_PHONE_FROM` | `+1234567890` | 以 `+1` 开头 |
| `TWILIO_PHONE_TO` | `+6491234567` | 以 `+64` 开头 |
| `OPENCLAW_WEBHOOK_URL` | `https://api.openclaw.io/v1/webhook/{id}` | 以 `https://api.openclaw.io` 开头 |

### 重要链接

| 服务 | 网址 |
|---------|---------|
| Supabase | https://supabase.com |
| DeepSeek | https://platform.deepseek.com |
| Tiger 证券 | https://www.itiger.com |
| Twilio | https://www.twilio.com |
| Render (部署) | https://render.com |

---

## 🎯 配置完成！

完成以上配置后，StockQueen 系统就可以正常运行了。

### 下一步
1. 运行测试脚本验证所有功能
2. 开始使用模拟盘测试系统
3. 根据表现调整参数
4. 逐步过渡到实盘

---

**祝你交易顺利！🚀**
