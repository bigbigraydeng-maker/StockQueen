# StockQueen Render 部署配置指南

## 🎯 架构概览

```
stockqueen.tech (自定义域名)
    ├── api.stockqueen.tech → Render Web Service (后端 API)
    └── www.stockqueen.tech → Render Static Site (前端网站)
```

## 📋 前置要求

1. **已购买域名**: `stockqueen.tech`
2. **GitHub 仓库**: 代码已推送到 GitHub
3. **Resend 账号**: 用于邮件服务

---

## 🚀 步骤 1: 部署后端 API (Web Service)

### 1.1 创建 Web Service

1. 登录 [Render Dashboard](https://dashboard.render.com)
2. 点击 **"New +"** → **"Web Service"**
3. 连接你的 GitHub 仓库
4. 配置如下：

| 配置项 | 值 |
|--------|-----|
| **Name** | `stockqueen-api` |
| **Environment** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| **Plan** | Free (或根据需求选择) |

### 1.2 配置环境变量

在 Render Dashboard → 你的服务 → **Environment** 中添加：

```bash
# 数据库
DATABASE_URL=postgresql://username:password@host:port/database

# Resend 邮件
RESEND_API_KEY=re_你的APIKey
FROM_EMAIL=newsletter@stockqueen.tech
CONTACT_EMAIL=contact@stockqueen.tech

# 其他
DEBUG=False
SECRET_KEY=your-secret-key-here
```

### 1.3 自定义域名配置

1. 在 Web Service 页面点击 **"Settings"**
2. 找到 **"Custom Domains"**
3. 点击 **"Add Custom Domain"**
4. 输入: `api.stockqueen.tech`
5. 按照提示添加 DNS 记录（见下方 DNS 配置）

---

## 🌐 步骤 2: 部署前端网站 (Static Site)

### 2.1 创建 Static Site

1. 在 Render Dashboard 点击 **"New +"** → **"Static Site"**
2. 连接同一个 GitHub 仓库
3. 配置如下：

| 配置项 | 值 |
|--------|-----|
| **Name** | `stockqueen-site` |
| **Build Command** | 留空（纯静态文件） |
| **Publish Directory** | `site` |
| **Plan** | Free |

### 2.2 配置环境变量（可选）

如果前端需要环境变量：

```bash
API_BASE_URL=https://api.stockqueen.tech
```

### 2.3 自定义域名配置

1. 在 Static Site 页面点击 **"Settings"**
2. 找到 **"Custom Domains"**
3. 点击 **"Add Custom Domain"**
4. 输入: `www.stockqueen.tech`
5. 按照提示添加 DNS 记录

---

## 🌐 步骤 3: DNS 配置（域名提供商处设置）

在你的域名提供商（如 GoDaddy、Namecheap、Cloudflare）处添加以下 DNS 记录：

### 方案 A: 使用 CNAME（推荐）

| 类型 | 主机记录 | 值 |
|------|---------|-----|
| CNAME | `api` | `stockqueen-api.onrender.com` |
| CNAME | `www` | `stockqueen-site.onrender.com` |

### 方案 B: 根域名重定向

如果你想让 `stockqueen.tech` 直接访问网站：

| 类型 | 主机记录 | 值 |
|------|---------|-----|
| A | `@` | `76.76.21.21` (Render 的 IP) |
| CNAME | `www` | `stockqueen-site.onrender.com` |
| CNAME | `api` | `stockqueen-api.onrender.com` |

**注意**: 根域名 A 记录需要 Render 支持，或者使用 URL 转发将根域名转发到 www。

---

## 📧 步骤 4: Resend 域名验证

为了让邮件正常发送，需要在 Resend 验证你的域名：

### 4.1 添加域名

1. 登录 [Resend Dashboard](https://resend.com)
2. 点击 **"Domains"** → **"Add Domain"**
3. 输入: `stockqueen.tech`
4. 复制 DNS 记录

### 4.2 添加 DNS 记录

在域名提供商处添加 Resend 提供的 DNS 记录：

| 类型 | 主机记录 | 值 |
|------|---------|-----|
| TXT | `_dmarc` | `v=DMARC1; p=none;` |
| TXT | `@` | (Resend 提供的 SPF 记录) |
| CNAME | (Resend 提供的 DKIM) | (Resend 提供的值) |

### 4.3 等待验证

通常几分钟到几小时后，Resend 会显示域名已验证。

---

## ✅ 步骤 5: 验证部署

### 5.1 测试 API

```bash
curl https://api.stockqueen.tech/api/public/signals
```

### 5.2 测试网站

访问: `https://www.stockqueen.tech`

### 5.3 测试邮件

运行测试脚本：

```bash
python scripts/send-test-email.py
```

---

## 🔧 故障排除

### 域名无法访问

1. 检查 DNS 记录是否正确添加
2. 等待 DNS 传播（最长 48 小时）
3. 在 Render 中重新验证域名

### SSL 证书问题

Render 会自动为自定义域名配置 SSL，如果出现问题：
1. 删除自定义域名
2. 重新添加

### 邮件发送失败

1. 检查 Resend 域名是否已验证
2. 检查环境变量中的 API Key 是否正确
3. 检查发件人邮箱域名是否正确

---

## 📚 参考链接

- [Render 自定义域名文档](https://render.com/docs/custom-domains)
- [Resend 域名验证文档](https://resend.com/docs/dashboard/domains/introduction)
- [Cloudflare DNS 设置](https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/)

---

## 🎉 完成！

部署完成后，你的 StockQueen 网站将通过 `stockqueen.tech` 访问：

- **官网**: https://www.stockqueen.tech
- **API**: https://api.stockqueen.tech
- **周报**: https://www.stockqueen.tech/weekly-report/
