# StockQueen CMS 开发交接文档

## 📋 项目概述

StockQueen CMS 是一个基于 Next.js 14 构建的内容管理系统，用于管理 StockQueen 网站的博客文章和性能数据。

### 技术栈
- **框架**: Next.js 14 (App Router)
- **语言**: TypeScript
- **样式**: Tailwind CSS
- **UI组件**: shadcn/ui
- **编辑器**: TipTap (富文本编辑器)
- **文件系统**: Node.js fs 模块
- **版本控制**: Git 集成

---

## 🏗️ 项目结构

```
cms/
├── src/
│   ├── app/
│   │   ├── api/
│   │   │   └── blog/
│   │   │       └── route.ts          # API路由 - 文章CRUD
│   │   ├── page.tsx                   # 主CMS页面
│   │   ├── layout.tsx                 # 根布局
│   │   └── globals.css                # 全局样式
│   ├── components/
│   │   ├── Editor.tsx                 # TipTap富文本编辑器
│   │   └── DataCard.tsx               # 数据卡片组件
│   └── lib/
│       ├── fileService.ts             # 文件操作服务
│       ├── gitService.ts              # Git操作服务
│       ├── performanceService.ts      # 性能数据服务
│       └── utils.ts                   # 工具函数
├── package.json
└── next.config.js
```

---

## 🔧 核心功能模块

### 1. 文章管理 (fileService.ts)

#### 数据结构
```typescript
interface BlogPost {
  id: string;           // 文章唯一标识 (slug)
  title: string;        // 文章标题
  content: string;      // 文章内容 (HTML)
  date: string;         // 发布日期 (YYYY-MM-DD)
  slug: string;         // URL友好的标识
  isPublished: boolean; // 发布状态
  filePath?: string;    // 文件路径
}
```

#### 主要函数
- `loadBlogPosts()`: 加载所有博客文章
  - 从 `../site/blog/` 目录读取 HTML 文件
  - 提取标题、日期、内容
  - 返回 BlogPost 数组

- `saveBlogPost(post)`: 保存新文章
  - 生成 slug: `title.toLowerCase().replace(/[^a-z0-9]+/g, '-')`
  - 创建完整 HTML 文件
  - 自动更新索引页面

- `updateBlogPost(post)`: 更新现有文章
  - 覆盖原有文件
  - 更新索引页面

- `deleteBlogPost(slug)`: 删除文章
  - 删除 HTML 文件
  - 更新索引页面

- `updateBlogIndexPage()`: 更新博客索引页面
  - 读取所有文章
  - 按日期排序
  - 生成新的 index.html

### 2. API路由 (app/api/blog/route.ts)

#### GET /api/blog
- 返回所有博客文章
- 调用 `loadBlogPosts()`

#### POST /api/blog
- 创建新文章
- 接收 JSON 数据
- 调用 `saveBlogPost()`

**待完善**:
- PUT /api/blog - 更新文章
- DELETE /api/blog - 删除文章

### 3. Git 集成 (gitService.ts)

#### 主要函数
- `getGitStatus()`: 获取 Git 状态
- `gitSync(message)`: 提交并推送更改
- `gitPull()`: 拉取远程更新

### 4. 性能数据 (performanceService.ts)

#### 主要函数
- `getPerformanceData()`: 获取性能指标
  - 年化收益
  - 夏普比率
  - 胜率
  - 最大回撤

- `getWeeklyReports()`: 获取周报列表

---

## 🎨 前端界面

### 主页面 (page.tsx)

#### 状态管理
```typescript
const [posts, setPosts] = useState<BlogPost[]>([]);
const [filteredPosts, setFilteredPosts] = useState<BlogPost[]>([]);
const [currentPost, setCurrentPost] = useState<BlogPost | null>(null);
const [languageFilter, setLanguageFilter] = useState<'all' | 'zh' | 'en'>('all');
const [editorMode, setEditorMode] = useState<'rich' | 'html'>('rich');
```

#### 功能区域
1. **头部**: Logo, Git状态, 操作按钮
2. **性能数据**: 4个数据卡片
3. **文章列表**: 
   - 语言筛选 (全部/中文/英文)
   - 文章列表
   - 前台链接
4. **编辑区域**:
   - 标题输入
   - 编辑器模式切换 (富文本/HTML)
   - 内容编辑
   - 操作按钮 (保存/发布/删除)

### 编辑器组件 (Editor.tsx)

#### TipTap 配置
- **扩展**: StarterKit + 各种格式扩展
- **功能**: 粗体、斜体、下划线、删除线、标题、引用、代码、列表、图片、链接
- **模式**: 所见即所得编辑

---

## 📁 文件存储结构

### 博客文章
```
site/blog/
├── index.html                    # 博客首页 (自动生成)
├── index-zh.html                 # 中文博客首页
├── {slug}.html                   # 英文文章
└── {slug}-zh.html                # 中文文章
```

### HTML 文件格式
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <link rel="stylesheet" href="../css/style.css">
  <meta name="date" content="{date}">
</head>
<body>
  <header class="blog-header">
    <h1>{title}</h1>
    <p class="post-meta">发布时间: {date}</p>
  </header>
  <main class="container">
    {content}
  </main>
  <footer class="blog-footer">
    <p>&copy; 2026 StockQueen. All rights reserved.</p>
  </footer>
</body>
</html>
```

---

## 🔍 语言识别逻辑

### 规则
- **中文文章**: slug 包含 `-zh` 或不包含 `-en`
- **英文文章**: slug 包含 `-en`
- **全部**: 显示所有文章

### 实现
```typescript
if (languageFilter === 'zh') {
  posts.filter(post => post.slug.includes('-zh') || !post.slug.includes('-en'))
} else if (languageFilter === 'en') {
  posts.filter(post => post.slug.includes('-en'))
}
```

---

## 🚀 开发任务清单

### 高优先级

#### 1. 完善 API 路由
**文件**: `src/app/api/blog/route.ts`

```typescript
// 添加 PUT 方法 - 更新文章
export async function PUT(request: Request) {
  const { updateBlogPost } = await import('@/lib/fileService');
  const post = await request.json();
  const updatedPost = await updateBlogPost(post);
  return Response.json(updatedPost);
}

// 添加 DELETE 方法 - 删除文章
export async function DELETE(request: Request) {
  const { deleteBlogPost } = await import('@/lib/fileService');
  const { slug } = await request.json();
  await deleteBlogPost(slug);
  return Response.json({ success: true });
}
```

#### 2. 统一 API 调用
**文件**: `src/app/page.tsx`

将 `updateBlogPost` 和 `deleteBlogPost` 改为 API 调用：
```typescript
const updateBlogPost = async (post: any) => {
  const response = await fetch('/api/blog', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(post),
  });
  return response.json();
};

const deleteBlogPost = async (slug: string) => {
  const response = await fetch('/api/blog', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug }),
  });
  return response.json();
};
```

#### 3. 修复编辑器内容提取
**文件**: `src/app/page.tsx`

当前内容提取逻辑可能无法正确处理所有 HTML 结构：
```typescript
const handleSelectPost = (post: BlogPost) => {
  setCurrentPost(post);
  setTitle(post.title);
  
  // 改进内容提取逻辑
  const extractContent = (html: string): string => {
    // 尝试提取 main 内容
    const mainMatch = html.match(/<main[^>]*>([\s\S]*?)<\/main>/i);
    if (mainMatch) return mainMatch[1].trim();
    
    // 尝试提取 body 内容
    const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
    if (bodyMatch) return bodyMatch[1].trim();
    
    // 尝试提取 article 内容
    const articleMatch = html.match(/<article[^>]*>([\s\S]*?)<\/article>/i);
    if (articleMatch) return articleMatch[1].trim();
    
    // 返回原始内容
    return html;
  };
  
  setContent(extractContent(post.content));
};
```

### 中优先级

#### 4. 添加图片上传功能
**文件**: `src/components/Editor.tsx`

添加图片上传按钮和逻辑：
```typescript
// 添加图片上传扩展
import { Image as TipTapImage } from '@tiptap/extension-image';

// 添加图片上传按钮
<Button
  onClick={() => {
    const url = window.prompt('输入图片URL');
    if (url) {
      editor?.chain().focus().setImage({ src: url }).run();
    }
  }}
>
  图片
</Button>
```

#### 5. 添加文章分类/标签
**文件**: `src/lib/fileService.ts`

扩展 BlogPost 接口：
```typescript
interface BlogPost {
  // ... 原有字段
  category?: string;    // 分类
  tags?: string[];      // 标签
  language: 'zh' | 'en'; // 语言
}
```

#### 6. 添加草稿自动保存
**文件**: `src/app/page.tsx`

实现自动保存到 localStorage：
```typescript
useEffect(() => {
  const timer = setTimeout(() => {
    if (currentPost || isNewPost) {
      localStorage.setItem('draft', JSON.stringify({ title, content }));
    }
  }, 3000);
  return () => clearTimeout(timer);
}, [title, content]);
```

### 低优先级

#### 7. 添加文章预览功能
在编辑区域添加预览标签页：
```typescript
const [activeTab, setActiveTab] = useState<'edit' | 'preview'>('edit');

// 预览内容
{activeTab === 'preview' && (
  <div dangerouslySetInnerHTML={{ __html: content }} />
)}
```

#### 8. 添加搜索功能
在文章列表添加搜索框：
```typescript
const [searchQuery, setSearchQuery] = useState('');

const filteredPosts = posts.filter(post => 
  post.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
  post.content.toLowerCase().includes(searchQuery.toLowerCase())
);
```

#### 9. 添加批量操作
支持批量删除、批量发布：
```typescript
const [selectedPosts, setSelectedPosts] = useState<string[]>([]);

const handleBatchDelete = async () => {
  for (const slug of selectedPosts) {
    await deleteBlogPost(slug);
  }
};
```

#### 10. 优化移动端体验
添加响应式布局优化：
```typescript
// 使用 Tailwind 响应式类
<div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
  {/* 移动端单列，桌面端三列 */}
</div>
```

---

## 🐛 已知问题

### 1. 编辑器 SSR 警告
**问题**: TipTap 在服务端渲染时出现警告
**状态**: 已修复 (移除 immediatelyRender 属性)
**文件**: `src/components/Editor.tsx`

### 2. 路径计算
**问题**: 文件路径在不同环境下可能不正确
**状态**: 已修复
**当前路径**: `path.join(process.cwd(), '../site/blog')`

### 3. 内容提取
**问题**: 某些 HTML 结构的内容提取不完整
**状态**: 待优化
**建议**: 改进正则表达式或使用 DOM 解析器

---

## 📚 依赖列表

```json
{
  "dependencies": {
    "next": "^14.x",
    "react": "^18.x",
    "@tiptap/react": "^2.x",
    "@tiptap/starter-kit": "^2.x",
    "@tiptap/extension-bold": "^2.x",
    "@tiptap/extension-italic": "^2.x",
    "@tiptap/extension-underline": "^2.x",
    "@tiptap/extension-strike": "^2.x",
    "@tiptap/extension-heading": "^2.x",
    "@tiptap/extension-blockquote": "^2.x",
    "@tiptap/extension-code": "^2.x",
    "@tiptap/extension-code-block": "^2.x",
    "@tiptap/extension-list-item": "^2.x",
    "@tiptap/extension-ordered-list": "^2.x",
    "@tiptap/extension-bullet-list": "^2.x",
    "@tiptap/extension-horizontal-rule": "^2.x",
    "@tiptap/extension-image": "^2.x",
    "@tiptap/extension-link": "^2.x",
    "tailwindcss": "^3.x",
    "class-variance-authority": "^0.x",
    "clsx": "^2.x",
    "tailwind-merge": "^2.x"
  }
}
```

---

## 🎯 开发规范

### 代码风格
- 使用 TypeScript 严格模式
- 组件使用函数式组件 + Hooks
- 使用 async/await 处理异步
- 错误处理使用 try/catch

### 文件命名
- 组件: PascalCase (Editor.tsx)
- 服务: camelCase (fileService.ts)
- 页面: page.tsx, layout.tsx

### 状态管理
- 使用 React useState/useEffect
- 复杂状态考虑使用 useReducer
- 全局状态考虑 Context API

---

## 🔐 安全注意事项

1. **文件路径**: 使用 path.join 避免路径遍历攻击
2. **用户输入**: 验证和清理所有用户输入
3. **Git 操作**: 确保在安全环境下执行
4. **文件权限**: 限制文件系统访问权限

---

## 📞 联系方式

如有问题，请联系开发团队。

---

**文档版本**: 1.0  
**最后更新**: 2026-03-15  
**项目路径**: `c:\Users\Zhong\Documents\trae_projects\StockQueen\cms`
