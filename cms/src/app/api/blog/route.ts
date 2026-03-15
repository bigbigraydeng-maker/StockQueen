import { loadBlogPosts, saveBlogPost, updateBlogPost, deleteBlogPost } from '@/lib/fileService';
import { NextResponse } from 'next/server';

// ── GET /api/blog — list all posts ──
export async function GET() {
  try {
    const posts = await loadBlogPosts();
    return NextResponse.json(posts);
  } catch (error) {
    console.error('Error loading blog posts:', error);
    return NextResponse.json({ error: 'Failed to load blog posts' }, { status: 500 });
  }
}

// ── POST /api/blog — create a new post ──
export async function POST(request: Request) {
  try {
    const body = await request.json();

    // Validate required fields
    if (!body.title || typeof body.title !== 'string' || !body.title.trim()) {
      return NextResponse.json({ error: 'title is required' }, { status: 400 });
    }
    if (!body.content || typeof body.content !== 'string') {
      return NextResponse.json({ error: 'content is required' }, { status: 400 });
    }

    const post = {
      title: body.title.trim(),
      content: body.content,
      date: body.date || new Date().toISOString().split('T')[0],
      slug: body.slug || '',
      isPublished: !!body.isPublished,
    };

    const savedPost = await saveBlogPost(post);
    return NextResponse.json(savedPost, { status: 201 });
  } catch (error) {
    console.error('Error saving blog post:', error);
    return NextResponse.json({ error: 'Failed to save blog post' }, { status: 500 });
  }
}

// ── PUT /api/blog — update an existing post ──
export async function PUT(request: Request) {
  try {
    const body = await request.json();

    if (!body.slug || typeof body.slug !== 'string') {
      return NextResponse.json({ error: 'slug is required' }, { status: 400 });
    }
    if (!body.title || typeof body.title !== 'string' || !body.title.trim()) {
      return NextResponse.json({ error: 'title is required' }, { status: 400 });
    }

    const updatedPost = await updateBlogPost({
      id: body.id || body.slug,
      title: body.title.trim(),
      content: body.content || '',
      date: body.date || new Date().toISOString().split('T')[0],
      slug: body.slug,
      isPublished: !!body.isPublished,
    });

    return NextResponse.json(updatedPost);
  } catch (error) {
    console.error('Error updating blog post:', error);
    return NextResponse.json({ error: 'Failed to update blog post' }, { status: 500 });
  }
}

// ── DELETE /api/blog — delete a post by slug ──
export async function DELETE(request: Request) {
  try {
    const body = await request.json();

    if (!body.slug || typeof body.slug !== 'string') {
      return NextResponse.json({ error: 'slug is required' }, { status: 400 });
    }

    await deleteBlogPost(body.slug);
    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Error deleting blog post:', error);
    return NextResponse.json({ error: 'Failed to delete blog post' }, { status: 500 });
  }
}
