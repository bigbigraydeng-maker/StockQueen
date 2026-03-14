# Resend 邮件服务配置指南

## 📧 邮箱分类

为了区分不同类型的邮件，我们使用不同的发件人邮箱：

| 用途 | 发件人邮箱 | 说明 |
|------|-----------|------|
| **Newsletter** | `newsletter@stockqueen.io` | 周报、订阅邮件 |
| **Contact** | `contact@stockqueen.io` | 联系表单回复 |
| **System** | `noreply@stockqueen.io` | 系统通知、早期访问 |
| **Testing** | `onboarding@resend.dev` | 测试时使用（Resend 默认）|

## 🚀 快速开始

### 1. 注册 Resend 账号

1. 访问 https://resend.com
2. 使用 GitHub 或邮箱注册
3. 验证邮箱地址

### 2. 获取 API Key

1. 登录 Resend 控制台
2. 点击左侧菜单 "API Keys"
3. 点击 "Create API Key"
4. 选择权限：
   - `sending` - 发送邮件（必需）
   - `domains` - 管理域名（可选）
5. 复制生成的 API Key（格式：`re_xxxxxxxx`）

### 3. 配置环境变量

编辑 `.env` 文件：

```bash
# Resend API Key
RESEND_API_KEY=re_你的实际APIKey

# 发件人邮箱（需要先在 Resend 验证）
NEWSLETTER_FROM=newsletter@stockqueen.io
CONTACT_FROM=contact@stockqueen.io
NOREPLY_FROM=noreply@stockqueen.io

# 收件人邮箱（你的团队邮箱）
CONTACT_TO=your-email@gmail.com
NEWSLETTER_ADMIN=your-email@gmail.com
```

### 4. 验证域名（可选但推荐）

如果你想使用自己的域名（如 `stockqueen.io`）：

1. 在 Resend 控制台点击 "Domains"
2. 点击 "Add Domain"
3. 输入你的域名：`stockqueen.io`
4. 按照提示添加 DNS 记录
5. 等待验证（通常几分钟到几小时）

**测试阶段**：可以直接使用 `onboarding@resend.dev`，无需验证域名。

## 📁 文件说明

| 文件 | 用途 |
|------|------|
| `js/resend-integration.js` | Resend 集成模块，处理所有表单提交 |
| `scripts/send-test-email.py` | 中文周报邮件发送脚本 |
| `scripts/send-test-email-en.py` | 英文周报邮件发送脚本 |
| `.env` | 环境变量配置（包含 API Key）|
| `email-test.html` | 邮件测试页面 |

## 🔧 使用方式

### 方式 1：Python 脚本（推荐用于 Newsletter）

```bash
# 中文周报
python scripts/send-test-email.py

# 英文周报
python scripts/send-test-email-en.py
```

### 方式 2：网页表单（Contact / Early Access）

1. 在 `index.html` 中引入 Resend 模块：

```html
<script src="js/resend-integration.js"></script>
```

2. 表单会自动处理提交并发送邮件

**注意**：生产环境中，API Key 不应该暴露在客户端代码中。应该：
- 使用后端 API 代理请求
- 或使用 serverless 函数（如 Vercel Functions、Cloudflare Workers）

### 方式 3：邮件测试页面

访问：`https://stockqueen-site.onrender.com/weekly-report/email-test.html`

## 📊 邮件配额

Resend 免费版限制：
- 每天最多 100 封邮件
- 每月最多 3,000 封邮件
- 支持最多 10 个域名

付费版：
- $20/月：每天 5,000 封
- $100/月：每天 50,000 封

## 🛡️ 安全注意事项

1. **永远不要提交 API Key 到 Git**
   - `.env` 文件已添加到 `.gitignore`
   - 定期轮换 API Key

2. **生产环境使用后端代理**
   ```
   前端 → 你的后端 API → Resend API
   ```

3. **验证发件人域名**
   - 提高邮件送达率
   - 避免进入垃圾邮件文件夹

4. **监控邮件发送**
   - 在 Resend 控制台查看发送日志
   - 监控退信率和投诉率

## 🔍 故障排除

### 邮件发送失败

1. 检查 API Key 是否正确
2. 检查发件人邮箱是否已验证
3. 检查是否超过每日限额
4. 查看 Resend 控制台的发送日志

### 邮件进入垃圾邮件

1. 验证你的域名
2. 添加 SPF、DKIM、DMARC 记录
3. 使用专业的邮件模板
4. 避免使用垃圾邮件敏感词汇

## 📞 支持

- Resend 文档：https://resend.com/docs
- Resend 支持：support@resend.com
- StockQueen 团队：bigbigraydeng@gmail.com
