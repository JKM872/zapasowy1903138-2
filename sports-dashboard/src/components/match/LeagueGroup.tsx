// ============================================================================
// LeagueGroup – collapsible league section with market column headers
// ============================================================================
'use client'

import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'
import { SportIcon } from '@/components/shared/SportIcon'
import { marketLayout } from './marketGrid'

interface Props {
  league: string
  country?: string | null
  /** Sport of this league; decides two-way versus three-way market columns. */
  sport?: string | null
  matchCount: number
  hasLive?: boolean
  defaultOpen?: boolean
  children: React.ReactNode
}

export function LeagueGroup({
  league,
  country,
  sport,
  matchCount,
  hasLive = false,
  defaultOpen = true,
  children,
}: Props) {
  const [open, setOpen] = useState(defaultOpen)
  const { gridClass, columns } = marketLayout(sport)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button
          className={cn(
            'w-full items-center border-b border-border/40 bg-panel text-left transition-colors hover:bg-panel-hover',
            // Same template as the rows, so the 1-X-2 labels sit exactly above
            // their odds buttons.
            gridClass,
            hasLive && 'bg-red-500/5',
          )}
        >
          {/* Sport glyph, in the time column */}
          <span className="flex items-center justify-center py-1.5">
            <SportIcon sport={sport} colored className="text-[16px]" />
          </span>

          {/* League name */}
          <span className="flex min-w-0 items-center gap-1.5 px-2 py-1.5">
            {hasLive && (
              <span className="relative flex h-1.5 w-1.5 shrink-0">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-500 opacity-75" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-red-500" />
              </span>
            )}
            {country && (
              <>
                <span className="shrink-0 text-[10px] uppercase text-muted-foreground/70">
                  {country}
                </span>
                <span className="text-muted-foreground/30">·</span>
              </>
            )}
            <span className="truncate text-[11px] font-semibold uppercase tracking-wide text-foreground/90">
              {league}
            </span>
            <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
              {matchCount}
            </span>
            <ChevronDown
              className={cn(
                'ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-transform duration-200',
                open && 'rotate-180',
              )}
            />
          </span>

          {/* Market column headers */}
          {columns.map(outcome => (
            <span
              key={outcome}
              className="hidden items-center justify-center py-1.5 text-[10px] font-semibold text-muted-foreground lg:flex"
            >
              {outcome}
            </span>
          ))}

          {/* Confidence column */}
          <span className="hidden items-center justify-end pr-2 text-[10px] font-semibold text-muted-foreground lg:flex">
            %
          </span>
        </button>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="bg-card">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  )
}
