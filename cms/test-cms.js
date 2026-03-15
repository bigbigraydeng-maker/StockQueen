// 测试脚本 - 验证 CMS 系统功能
const { saveBlogPost, loadBlogPosts, deleteBlogPost } = require('./src/lib/fileService');

async function testCMS() {
  console.log('=== 测试 CMS 系统 ===');
  
  try {
    // 测试 1: 加载现有文章
    console.log('\n1. 加载现有文章:');
    const existingPosts = await loadBlogPosts();
    console.log(`现有文章数量: ${existingPosts.length}`);
    existingPosts.forEach(post => {
      console.log(`- ${post.title} (${post.date})`);
    });
    
    // 测试 2: 创建新文章
    console.log('\n2. 创建新测试文章:');
    const newPost = await saveBlogPost({
      title: '测试文章：CMS系统同步功能',
      content: '<h1>测试文章</h1><p>这是一篇测试文章，用于验证CMS系统与前台的同步功能。</p>',
      date: '2026-03-15',
      isPublished: true
    });
    console.log(`创建成功: ${newPost.title}`);
    
    // 测试 3: 验证文章已保存
    console.log('\n3. 验证文章已保存:');
    const postsAfterSave = await loadBlogPosts();
    console.log(`保存后文章数量: ${postsAfterSave.length}`);
    
    // 测试 4: 验证索引页面已更新
    console.log('\n4. 验证索引页面已更新:');
    const fs = require('fs');
    const path = require('path');
    const indexPath = path.join(__dirname, '../../site/blog/index.html');
    
    if (fs.existsSync(indexPath)) {
      const indexContent = fs.readFileSync(indexPath, 'utf8');
      if (indexContent.includes('测试文章：CMS系统同步功能')) {
        console.log('✓ 索引页面已包含新文章');
      } else {
        console.log('✗ 索引页面未包含新文章');
      }
    } else {
      console.log('✗ 索引页面不存在');
    }
    
    console.log('\n=== 测试完成 ===');
    
  } catch (error) {
    console.error('测试失败:', error);
  }
}

testCMS();