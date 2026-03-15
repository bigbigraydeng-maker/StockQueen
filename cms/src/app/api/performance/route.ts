import { getPerformanceData, getWeeklyReports } from '@/lib/performanceService';
import { NextResponse } from 'next/server';

// GET /api/performance — get performance data
export async function GET() {
  try {
    const [performance, weeklyReports] = await Promise.all([
      getPerformanceData(),
      getWeeklyReports(),
    ]);
    return NextResponse.json({ performance, weeklyReports });
  } catch (error) {
    console.error('Error loading performance data:', error);
    return NextResponse.json({ error: 'Failed to load performance data' }, { status: 500 });
  }
}
