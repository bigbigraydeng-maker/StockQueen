import { getGitStatus, gitSync, gitPull } from '@/lib/gitService';
import { NextResponse } from 'next/server';

// GET /api/git — get git status
export async function GET() {
  try {
    const status = await getGitStatus();
    return NextResponse.json(status);
  } catch (error) {
    console.error('Error getting git status:', error);
    return NextResponse.json({ error: 'Failed to get git status' }, { status: 500 });
  }
}

// POST /api/git — sync or pull
export async function POST(request: Request) {
  try {
    const body = await request.json();
    const action = body.action as string;

    if (action === 'sync') {
      const message = typeof body.message === 'string' ? body.message : 'Update via CMS';
      const ok = await gitSync(message);
      return NextResponse.json({ success: ok });
    }

    if (action === 'pull') {
      const ok = await gitPull();
      return NextResponse.json({ success: ok });
    }

    return NextResponse.json({ error: 'Invalid action. Use "sync" or "pull".' }, { status: 400 });
  } catch (error) {
    console.error('Error in git action:', error);
    return NextResponse.json({ error: 'Git operation failed' }, { status: 500 });
  }
}
