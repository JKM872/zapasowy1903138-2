// ============================================================================
// GradeBadge – shows a prediction's grade (A-F) with premium styling for A
// ============================================================================
'use client'

import { Crown } from 'lucide-react'
import { cn } from '@/lib/utils'

const GRADE_STYLES: Record<string, string> = {
  A: 'bg-gradient-to-r from-amber-400 to-yellow-500 text-black border-amber-500/50',
  B: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
  C: 'bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/30',
  D: 'bg-zinc-500/15 text-zinc-600 dark:text-zinc-400 border-zinc-500/30',
  F: 'bg-zinc-500/10 text-muted-foreground border-border',
}

interface Props {
  grade?: string | null
  className?: string
  size?: 'sm' | 'md'
}

export function GradeBadge({ grade, className, size = 'sm' }: Props) {
  if (!grade) return null
  const g = grade.trim().toUpperCase()
  const style = GRADE_STYLES[g] ?? GRADE_STYLES.F

  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 rounded border font-bold tabular-nums',
        size === 'sm' ? 'px-1.5 py-0 text-[10px]' : 'px-2 py-0.5 text-xs',
        style,
        className,
      )}
      title={`Grade ${g}`}
    >
      {g === 'A' && <Crown className={size === 'sm' ? 'h-2.5 w-2.5' : 'h-3 w-3'} />}
      {g}
    </span>
  )
}
