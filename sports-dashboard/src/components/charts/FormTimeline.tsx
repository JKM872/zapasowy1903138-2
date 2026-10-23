// ============================================================================
// FormTimeline – recent results as small coloured boxes (Z / R / P)
// ============================================================================
'use client'

import { cn } from '@/lib/utils'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

interface Props {
  form: string[] // e.g. ["W", "D", "L", "W", "W"]
  teamName?: string
  maxItems?: number
  className?: string
}

const FORM_CONFIG: Record<string, { color: string; label: string; short: string }> = {
  W: { color: 'bg-emerald-500', label: 'Win', short: 'W' },
  D: { color: 'bg-zinc-500', label: 'Draw', short: 'D' },
  L: { color: 'bg-rose-500', label: 'Loss', short: 'L' },
}

export function FormTimeline({ form, teamName, maxItems = 5, className }: Props) {
  // Scrapers send brackets and dashes as separate entries ("[", "-", "]");
  // rendering them produced empty orange boxes. Keep only real results.
  const clean = (form ?? []).join('').toUpperCase().replace(/[^WDL]/g, '').split('').filter(Boolean)
  if (clean.length === 0) return null
  const items = clean.slice(-maxItems)

  return (
    <TooltipProvider>
      <div className={cn('flex items-center gap-0.5', className)}>
        {items.map((result, i) => {
          const cfg = FORM_CONFIG[result]
          return (
            <Tooltip key={i}>
              <TooltipTrigger asChild>
                <div
                  className={cn(
                    'flex h-4 w-4 items-center justify-center rounded-sm text-[8px] font-bold leading-none text-white',
                    cfg.color,
                  )}
                >
                  {cfg.short}
                </div>
              </TooltipTrigger>
              <TooltipContent side="top" className="text-xs">
                {teamName ? `${teamName}: ${cfg.label}` : cfg.label}
              </TooltipContent>
            </Tooltip>
          )
        })}
      </div>
    </TooltipProvider>
  )
}
