'use client';

import { useState, useEffect, useCallback } from 'react';
import { Editor } from '@/components/Editor';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { DataCard } from '@/components/DataCard';

// ── Types ──
interface BlogPost {
  id: string;
  title: string;
  content: string;
  date: string;
  slug: string;
  isPublished: boolean;
  filePath?: string;
  language?: 'zh' | 'en';
}

interface GitStatus {
  isSynced: boolean;
  branch: string;
  status: string;
  lastCommit: string;
}

interface PerformanceData {
  annualReturn?: number;
  sharpeRatio?: number;
  winRate?: number;
  maxDrawdown?: number;
}

// ── API helpers (all through /api routes, never import server libs directly) ──
async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed: ${res.status}`);
  }
  return res.json();
}

const api = {
  loadPosts: () => apiFetch<BlogPost[]>('/api/blog'),

  createPost: (post: Partial<BlogPost>) =>
    apiFetch<BlogPost>('/api/blog', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(post),
    }),

  updatePost: (post: Partial<BlogPost>) =>
    apiFetch<BlogPost>('/api/blog', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(post),
    }),

  deletePost: (slug: string) =>
    apiFetch<{ success: boolean }>('/api/blog', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug }),
    }),

  getGitStatus: () => apiFetch<GitStatus>('/api/git'),

  gitSync: async (message: string): Promise<boolean> => {
    const res = await apiFetch<{ success: boolean }>('/api/git', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'sync', message }),
    });
    return res.success;
  },

  gitPull: async (): Promise<boolean> => {
    const res = await apiFetch<{ success: boolean }>('/api/git', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'pull' }),
    });
    return res.success;
  },

  getPerformanceData: async (): Promise<PerformanceData> => {
    const res = await apiFetch<{ performance: PerformanceData }>('/api/performance');
    return res.performance;
  },
};

// ── Helpers ──
function extractContent(html: string): string {
  // Try <main>, then <article>, then <body>
  const mainMatch = html.match(/<main[^>]*>([\s\S]*?)<\/main>/i);
  if (mainMatch) return mainMatch[1].trim();
  const articleMatch = html.match(/<article[^>]*>([\s\S]*?)<\/article>/i);
  if (articleMatch) return articleMatch[1].trim();
  const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  if (bodyMatch) return bodyMatch[1].trim();
  return html;
}

// ── Component ──
export default function CMS() {
  const [posts, setPosts] = useState<BlogPost[]>([]);
  const [currentPost, setCurrentPost] = useState<BlogPost | null>(null);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [isNewPost, setIsNewPost] = useState(false);
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState<'success' | 'error'>('success');
  const [loading, setLoading] = useState(true);
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null);
  const [gitLoading, setGitLoading] = useState(false);
  const [performanceData, setPerformanceData] = useState<PerformanceData | null>(null);
  const [performanceLoading, setPerformanceLoading] = useState(true);
  const [languageFilter, setLanguageFilter] = useState<'all' | 'zh' | 'en'>('all');
  const [editorMode, setEditorMode] = useState<'rich' | 'html'>('rich');

  // Derived: filtered posts
  const filteredPosts = (() => {
    if (languageFilter === 'all') return posts;
    if (languageFilter === 'zh') return posts.filter((p) => p.slug.endsWith('-zh') || p.slug.includes('-zh-'));
    // 'en' — everything that is NOT Chinese
    return posts.filter((p) => !p.slug.endsWith('-zh') && !p.slug.includes('-zh-'));
  })();

  const showMessage = useCallback((msg: string, type: 'success' | 'error' = 'success') => {
    setMessage(msg);
    setMessageType(type);
    setTimeout(() => setMessage(''), 5000);
  }, []);

  // ── Load posts ──
  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        setPosts(await api.loadPosts());
      } catch (error) {
        console.error('Error loading posts:', error);
        showMessage('加载文章失败', 'error');
      } finally {
        setLoading(false);
      }
    })();
  }, [showMessage]);

  // ── Load git status ──
  useEffect(() => {
    api.getGitStatus().then(setGitStatus).catch(console.error);
  }, []);

  // ── Load performance ──
  useEffect(() => {
    (async () => {
      try {
        setPerformanceLoading(true);
        setPerformanceData(await api.getPerformanceData());
      } catch (error) {
        console.error('Error loading performance data:', error);
      } finally {
        setPerformanceLoading(false);
      }
    })();
  }, []);

  // ── Handlers ──
  const handleGitSync = async () => {
    try {
      setGitLoading(true);
      const ok = await api.gitSync('Update blog posts via CMS');
      showMessage(ok ? 'Git 同步成功！' : 'Git 同步失败', ok ? 'success' : 'error');
      setGitStatus(await api.getGitStatus());
    } catch {
      showMessage('Git 同步失败', 'error');
    } finally {
      setGitLoading(false);
    }
  };

  const handleGitPull = async () => {
    try {
      setGitLoading(true);
      const ok = await api.gitPull();
      if (ok) {
        showMessage('Git 拉取成功！');
        setPosts(await api.loadPosts());
      } else {
        showMessage('Git 拉取失败', 'error');
      }
      setGitStatus(await api.getGitStatus());
    } catch {
      showMessage('Git 拉取失败', 'error');
    } finally {
      setGitLoading(false);
    }
  };

  const handleSelectPost = (post: BlogPost) => {
    setCurrentPost(post);
    setTitle(post.title);
    setContent(extractContent(post.content));
    setIsNewPost(false);
    setMessage('');
  };

  const handleNewPost = () => {
    setCurrentPost(null);
    setTitle('');
    setContent('');
    setIsNewPost(true);
    setMessage('');
  };

  const handleSavePost = async () => {
    if (!title.trim()) {
      showMessage('标题不能为空', 'error');
      return;
    }

    try {
      if (isNewPost) {
        const newPost = await api.createPost({
          title,
          content,
          date: new Date().toISOString().split('T')[0],
          slug: title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, ''),
          isPublished: false,
        });
        setPosts((prev) => [...prev, newPost]);
        setCurrentPost(newPost);
        setIsNewPost(false);
        showMessage('文章创建成功！');
      } else if (currentPost) {
        const updatedPost = await api.updatePost({
          ...currentPost,
          title,
          content,
        });
        setPosts((prev) => prev.map((p) => (p.id === currentPost.id ? updatedPost : p)));
        setCurrentPost(updatedPost);
        showMessage('文章更新成功！');
      }
    } catch (error) {
      console.error('Error saving post:', error);
      showMessage('保存文章失败', 'error');
    }
  };

  const handlePublishPost = async () => {
    if (!currentPost) return;
    try {
      const updatedPost = await api.updatePost({ ...currentPost, isPublished: true });
      setPosts((prev) => prev.map((p) => (p.id === currentPost.id ? updatedPost : p)));
      setCurrentPost(updatedPost);
      showMessage('文章发布成功！');
    } catch (error) {
      console.error('Error publishing post:', error);
      showMessage('发布文章失败', 'error');
    }
  };

  const handleDeletePost = async () => {
    if (!currentPost || !window.confirm('确定要删除这篇文章吗？')) return;
    try {
      await api.deletePost(currentPost.slug);
      setPosts((prev) => prev.filter((p) => p.id !== currentPost.id));
      setCurrentPost(null);
      setTitle('');
      setContent('');
      setIsNewPost(false);
      showMessage('文章删除成功！');
    } catch (error) {
      console.error('Error deleting post:', error);
      showMessage('删除文章失败', 'error');
    }
  };

  const isEditing = currentPost !== null || isNewPost;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-gradient-to-r from-blue-600 to-cyan-500 text-white py-6 px-8">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
          <div>
            <h1 className="text-2xl font-bold">StockQueen CMS</h1>
            {gitStatus && (
              <p className="text-sm text-blue-100 mt-1">
                Git: {gitStatus.branch} - {gitStatus.status}
              </p>
            )}
          </div>
          <div className="flex space-x-2">
            <Button onClick={handleGitPull} className="bg-blue-800 hover:bg-blue-900 text-white" disabled={gitLoading}>
              {gitLoading ? '拉取中...' : '拉取'}
            </Button>
            <Button onClick={handleGitSync} className="bg-blue-800 hover:bg-blue-900 text-white" disabled={gitLoading}>
              {gitLoading ? '同步中...' : '同步'}
            </Button>
            <Button onClick={handleNewPost} className="bg-white text-blue-600 hover:bg-blue-50">
              新建文章
            </Button>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto p-6">
        {/* Message */}
        {message && (
          <Alert className={`mb-6 ${messageType === 'error' ? 'border-red-300 bg-red-50' : 'border-green-300 bg-green-50'}`}>
            <AlertTitle>{messageType === 'error' ? '错误' : '成功'}</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}

        {/* Performance overview */}
        <div className="mb-8">
          <h2 className="text-xl font-semibold mb-4">性能数据概览</h2>
          {performanceLoading ? (
            <div className="flex items-center justify-center h-40">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <DataCard type="performance" title="年化收益" value={`${performanceData?.annualReturn ?? 0}%`} period="年化" />
              <DataCard type="metric" title="夏普比率" value={performanceData?.sharpeRatio ?? 0} />
              <DataCard type="stats" title="胜率" value={`${performanceData?.winRate ?? 0}%`} />
              <DataCard type="performance" title="最大回撤" value={`${performanceData?.maxDrawdown ?? 0}%`} />
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Post list */}
          <div className="lg:col-span-1">
            <Card className="h-full">
              <div className="p-4 border-b border-gray-200">
                <h2 className="text-lg font-semibold">文章列表</h2>
                <div className="mt-3">
                  <h3 className="text-xs font-medium text-gray-500 mb-1">语言筛选</h3>
                  <div className="flex space-x-1">
                    {(['all', 'zh', 'en'] as const).map((lang) => (
                      <Button
                        key={lang}
                        variant={languageFilter === lang ? 'default' : 'ghost'}
                        size="sm"
                        onClick={() => setLanguageFilter(lang)}
                        className={languageFilter === lang ? 'bg-blue-600' : ''}
                      >
                        {lang === 'all' ? '全部' : lang === 'zh' ? '中文' : '英文'}
                      </Button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="p-4 space-y-3 max-h-[600px] overflow-y-auto">
                {loading ? (
                  <div className="flex items-center justify-center h-40">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                  </div>
                ) : filteredPosts.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">暂无文章</div>
                ) : (
                  filteredPosts.map((post) => (
                    <div
                      key={post.id}
                      onClick={() => handleSelectPost(post)}
                      className={`p-3 rounded-lg cursor-pointer transition-colors ${
                        currentPost?.id === post.id ? 'bg-blue-100' : 'hover:bg-gray-100'
                      }`}
                    >
                      <h3 className="font-medium text-sm">{post.title}</h3>
                      <div className="flex items-center justify-between text-xs text-gray-500 mt-1">
                        <span>{post.date}</span>
                        <span
                          className={`px-2 py-1 rounded-full ${
                            post.isPublished ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
                          }`}
                        >
                          {post.isPublished ? '已发布' : '草稿'}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </Card>
          </div>

          {/* Editor area */}
          <div className="lg:col-span-2">
            <Card className="h-full">
              <div className="p-4 border-b border-gray-200">
                <h2 className="text-lg font-semibold">
                  {isNewPost ? '新建文章' : currentPost ? '编辑文章' : '请选择文章'}
                </h2>
                {/* FIX: parentheses around (currentPost || isNewPost) — was a precedence bug */}
                {(currentPost || isNewPost) && (
                  <div className="mt-3 flex items-center justify-between">
                    <div>
                      <h3 className="text-xs font-medium text-gray-500 mb-1">编辑器模式</h3>
                      <div className="flex space-x-1">
                        <Button
                          variant={editorMode === 'rich' ? 'default' : 'ghost'}
                          size="sm"
                          onClick={() => setEditorMode('rich')}
                          className={editorMode === 'rich' ? 'bg-blue-600' : ''}
                        >
                          富文本
                        </Button>
                        <Button
                          variant={editorMode === 'html' ? 'default' : 'ghost'}
                          size="sm"
                          onClick={() => setEditorMode('html')}
                          className={editorMode === 'html' ? 'bg-blue-600' : ''}
                        >
                          HTML
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {isEditing ? (
                <div className="p-4 space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="title">标题</Label>
                    <Input
                      id="title"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="输入文章标题"
                      className="text-lg"
                    />
                  </div>

                  <Separator />

                  <div className="space-y-2">
                    <Label>内容</Label>
                    {editorMode === 'rich' ? (
                      <Editor content={content} onChange={setContent} placeholder="开始编写文章内容..." />
                    ) : (
                      <textarea
                        value={content}
                        onChange={(e) => setContent(e.target.value)}
                        placeholder="输入HTML内容..."
                        className="w-full min-h-[400px] p-4 border border-gray-200 rounded-md bg-white text-sm font-mono"
                      />
                    )}
                  </div>

                  <div className="flex space-x-2 pt-4">
                    <Button onClick={handleSavePost} className="flex-1">
                      保存
                    </Button>
                    {!isNewPost && currentPost && !currentPost.isPublished && (
                      <Button onClick={handlePublishPost} className="bg-green-600 hover:bg-green-700">
                        发布
                      </Button>
                    )}
                    {!isNewPost && currentPost && (
                      <Button onClick={handleDeletePost} className="bg-red-600 hover:bg-red-700">
                        删除
                      </Button>
                    )}
                  </div>
                </div>
              ) : (
                <div className="h-96 flex items-center justify-center text-gray-500">
                  请从左侧选择文章或点击顶部&quot;新建文章&quot;按钮
                </div>
              )}
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
