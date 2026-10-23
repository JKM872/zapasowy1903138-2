// ============================================================================
// RadialProgress – SVG ring for confidence display (SofaScore style)
// ============================================================================
'use client'

import { cn } from '@/lib/utils'

interface Props {
  value: number // 0-100
  size?: number // px
  strokeWidth?: number
  className?: string
  label?: string
  color?: string
  showValue?: boolean
}

export function RadialProgress({
  value,
  size = 52,
  strokeWidth = 4,
  className,
  label,
  color,
  showValue = true,
}: Props) {
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (Math.min(value, 100) / 100) * circumference

  // Auto color based on value
  const autoColor =
    value >= 85
      ? '#10b981' // emerald-500
      : value >= 70
        ? '#3b82f6' // blue-500
        : value >= 55
          ? '#f59e0b' // amber-500
          : '#71717a' // zinc-500

  const strokeColor = color || autoColor

  return (
    <div className={cn('relative inline-flex items-center justify-center', className)}>
      <svg width={size} height={size} className="-rotate-90">
        {/* Background ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-secondary"
        />
        {/* Progress ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={strokeColor}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-[stroke-dashoffset] duration-700 ease-out"
        />
      </svg>
      {showValue && (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-bold leading-none tabular-nums" style={{ color: strokeColor, fontSize: Math.max(8, Math.round(size * 0.28)) }}>
            {Math.round(value)}%
          </span>
          {label && (
            <span className="text-[8px] text-muted-foreground leading-none mt-0.5">
              {label}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
