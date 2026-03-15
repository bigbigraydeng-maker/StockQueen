import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface DataCardProps {
  type: 'performance' | 'metric' | 'stats';
  title: string;
  value: string | number;
  change?: number;
  period?: string;
  icon?: React.ReactNode;
  className?: string;
}

export function DataCard({ type, title, value, change, period, icon, className }: DataCardProps) {
  const getCardClass = () => {
    switch (type) {
      case 'performance':
        return 'border-green-200 bg-green-50';
      case 'metric':
        return 'border-blue-200 bg-blue-50';
      case 'stats':
        return 'border-purple-200 bg-purple-50';
      default:
        return '';
    }
  };

  return (
    <Card className={cn('p-4 border', getCardClass(), className)}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-gray-500">{title}</p>
          <div className="mt-1 flex items-baseline">
            <span className="text-2xl font-bold">{value}</span>
            {period && (
              <span className="ml-2 text-xs text-gray-500">{period}</span>
            )}
          </div>
          {change !== undefined && (
            <div className="mt-2 flex items-center">
              <span className={cn(
                'text-sm font-medium',
                change >= 0 ? 'text-green-600' : 'text-red-600'
              )}>
                {change >= 0 ? '↑' : '↓'} {Math.abs(change)}%
              </span>
              <span className="ml-1 text-xs text-gray-500">vs previous period</span>
            </div>
          )}
        </div>
        {icon && (
          <div className="flex-shrink-0 p-2 bg-white rounded-full shadow-sm">
            {icon}
          </div>
        )}
      </div>
    </Card>
  );
}
