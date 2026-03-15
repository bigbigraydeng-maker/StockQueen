# StockQueen CMS 使用文档

## 快速启动

```bash
# 1. 进入 CMS 目录
cd cms

# 2. 安装依赖（首次使用）
npm install

# 3. 启动开发服务器
npm run dev
```

启动后访问 **http://localhost:3000** 即可进入 CMS 管理后台。

---

## 功能概览

### 文章管理
| 操作 | 说明 |
|------|------|
| **新建文章** | 点击右上角「新建文章」按钮 |
| **编辑文章** | 左侧列表点击任意文章 |
| **保存** | 编辑后点击「保存」，文件写入 `site/blog/{slug}.html` |
| **发布** | 草稿状态下点击「发布」 |
| **删除** | 点击「删除」并确认 |

### 编辑器
- **富文本模式**：所见即所得，支持加粗、斜体、标题、引用、列表、图片、链接
- **HTML 模式**：直接编辑 HTML 源码

切换方式：编辑区顶部的「富文本 / HTML」按钮。

### 语言筛选
左侧文章列表支持按语言筛选：
- **全部**：显示所有文章
- **中文**：slug 含 `-zh` 的文章
- **英文**：其余文章

### Git 同步
| 按钮 | 操作 |
|------|------|
| **拉取** | `git pull origin main` — 获取远程最新内容 |
| **同步** | `git add . && git commit && git push` — 推送本地修改 |

头部会显示当前 Git 分支和同步状态。

### 性能数据
顶部展示 4 张数据卡片（年化收益、夏普比率、胜率、最大回撤），数据读取自 `site/data/live-metrics.json`。

---

## API 接口

CMS 通过以下 API 路由与后端通信（Next.js API Routes）：

| 方法 | 路由 | 说明 |
|------|------|------|
| GET | `/api/blog` | 获取所有文章 |
| POST | `/api/blog` | 创建新文章 |
| PUT | `/api/blog` | 更新已有文章 |
| DELETE | `/api/blog` | 删除文章（需传 `slug`） |
| GET | `/api/git` | 获取 Git 状态 |
| POST | `/api/git` | Git 操作（`action: "sync"` 或 `"pull"`） |
| GET | `/api/performance` | 获取性能数据 |

---

## 目录结构

```
cms/
├── src/
│   ├── app/
│   │   ├── api/
│   │   │   ├── blog/route.ts        # 文章 CRUD API
│   │   │   ├── git/route.ts         # Git 操作 API
│   │   │   └── performance/route.ts # 性能数据 API
│   │   ├── page.tsx                 # CMS 主页面
│   │   ├── layout.tsx               # 根布局
│   │   └── globals.css              # 全局样式
│   ├── components/
│   │   ├── Editor.tsx               # TipTap 富文本编辑器
│   │   ├── DataCard.tsx             # 数据卡片组件
│   │   └── ui/                      # shadcn/ui 基础组件
│   └── lib/
│       ├── fileService.ts           # 文件读写（含安全校验）
│       ├── gitService.ts            # Git 操作（防注入）
│       ├── performanceService.ts    # 性能数据读取
│       └── utils.ts                 # 工具函数
├── package.json
├── next.config.ts
└── tsconfig.json
```

---

## 文件存储

CMS 直接操作 `site/blog/` 下的 HTML 文件：

```
site/blog/
├── index.html                  # 英文博客首页（自动更新）
├── index-zh.html               # 中文博客首页
├── {slug}.html                 # 英文文章
└── {slug}-zh.html              # 中文文章
```

保存文章时会自动生成完整 HTML（含 head/body/footer），同时更新 `index.html` 中的文章列表。

---

## 安全机制

- **路径遍历防护**：slug 经过白名单过滤（仅允许 `a-z0-9-`），且用 `path.resolve()` 二次验证
- **命令注入防护**：Git 操作使用 `execFileSync` 参数化调用，不经过 shell
- **HTML 转义**：标题嵌入模板前自动转义特殊字符
- **输入验证**：所有 API 路由校验必填字段和类型

---

## 常用命令

```bash
# 开发模式（热重载）
npm run dev

# 生产构建
npm run build

# 启动生产服务
npm run start

# 代码检查
npm run lint
```

---

## 注意事项

1. CMS 必须在项目根目录的 `cms/` 子目录下运行，因为文件路径使用 `../site/blog` 相对定位
2. Git 同步功能会执行 `git push origin main`，确保你有推送权限
3. 目前 CMS 无登录认证，仅限本地开发使用，不要部署到公网
