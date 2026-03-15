// 测试索引页面更新功能
const fs = require('fs');
const path = require('path');

// 模拟文章数据
const testPosts = [
  {
    id: 'test-post-1',
    title: '测试文章：CMS系统同步功能',
    content: '<h1>测试文章</h1><p>这是一篇测试文章，用于验证CMS系统与前台的同步功能。</p>',
    date: '2026-03-15',
    slug: 'test-post-1',
    isPublished: true
  },
  {
    id: 'bear-market-defense-strategy-2025',
    title: '美股熊市防御指南：量化策略如何在暴跌中保护你的资产',
    content: '<h1>美股熊市防御指南</h1><p>2026年3月12日，美股市场遭遇了一次大规模的抛售...</p>',
    date: '2026-03-12',
    slug: 'bear-market-defense-strategy-2025',
    isPublished: true
  }
];

// 生成文章卡片 HTML
function generateArticlesHtml(posts) {
  // 按日期排序（最新的在前面）
  const sortedPosts = posts.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
  
  let articlesHtml = '';
  
  // 第一个文章作为 featured
  if (sortedPosts.length > 0) {
    const featuredPost = sortedPosts[0];
    articlesHtml += `                <!-- Featured Article -->
                <article class="glass-card" style="grid-column: 1 / -1; padding: 2rem;">
                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem;">
                        <span style="padding: 0.25rem 0.75rem; background: rgba(16, 185, 129, 0.2); color: #34d399; border-radius: 9999px; font-size: 0.75rem; font-weight: 500;">Featured</span>
                        <span style="color: #6b7280; font-size: 0.875rem;">${featuredPost.date}</span>
                    </div>
                    <h2 style="font-size: 1.5rem; font-weight: 700; margin-bottom: 1rem;">
                        <a href="./${featuredPost.slug}.html" style="color: white;">
                            ${featuredPost.title}
                        </a>
                    </h2>
                    <p style="color: #9ca3af; margin-bottom: 1.5rem;">
                        ${featuredPost.content.replace(/<[^>]*>/g, '').substring(0, 150)}...
                    </p>
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        <div style="display: flex; gap: 0.5rem;">
                            <span style="padding: 0.25rem 0.75rem; background: #1f2937; border-radius: 9999px; font-size: 0.75rem; color: #22d3ee;">Blog</span>
                        </div>
                        <a href="./${featuredPost.slug}.html" style="color: #22d3ee; font-weight: 500;">
                            Read More →
                        </a>
                    </div>
                </article>`;
  }

  // 生成其他文章
  for (let i = 1; i < sortedPosts.length; i++) {
    const post = sortedPosts[i];
    articlesHtml += `
                <!-- Article ${i+1} -->
                <article class="glass-card" style="padding: 1.5rem;">
                    <div style="color: #6b7280; font-size: 0.875rem; margin-bottom: 0.75rem;">${post.date}</div>
                    <h3 style="font-size: 1.25rem; font-weight: 600; margin-bottom: 0.75rem; color: white;">
                        <a href="./${post.slug}.html" style="color: white;">${post.title}</a>
                    </h3>
                    <p style="color: #9ca3af; font-size: 0.875rem; margin-bottom: 1rem;">
                        ${post.content.replace(/<[^>]*>/g, '').substring(0, 100)}...
                    </p>
                    <div style="display: flex; gap: 0.5rem;">
                        <span style="padding: 0.25rem 0.5rem; background: #1f2937; border-radius: 0.25rem; font-size: 0.75rem; color: #22d3ee;">Blog</span>
                        <a href="./${post.slug}.html" style="color: #22d3ee; font-size: 0.75rem;">Read More →</a>
                    </div>
                </article>`;
  }
  
  return articlesHtml;
}

// 更新索引页面
async function updateIndexPage() {
  console.log('更新博客索引页面...');
  
  try {
    // 读取原始索引页面
    const indexPath = path.join(__dirname, '../site/blog/index.html');
    console.log('索引页面路径:', indexPath);
    console.log('当前工作目录:', process.cwd());
    
    let originalContent = '';
    
    if (fs.existsSync(indexPath)) {
      originalContent = fs.readFileSync(indexPath, 'utf8');
      console.log('读取原始索引页面成功，文件大小:', originalContent.length);
    } else {
      console.log('索引页面不存在，使用默认模板');
      // 检查目录是否存在
      const blogDir = path.join(__dirname, '../site/blog');
      console.log('博客目录是否存在:', fs.existsSync(blogDir));
      if (fs.existsSync(blogDir)) {
        console.log('博客目录内容:', fs.readdirSync(blogDir));
      }
      return;
    }

    // 生成文章HTML
    const articlesHtml = generateArticlesHtml(testPosts);
    console.log('生成文章HTML成功');

    // 替换文章部分
    const newContent = originalContent.replace('{{ARTICLES}}', articlesHtml);

    // 写入更新后的索引页面
    fs.writeFileSync(indexPath, newContent);
    console.log('索引页面更新成功！');
    
  } catch (error) {
    console.error('更新索引页面失败:', error);
  }
}

// 运行测试
updateIndexPage();