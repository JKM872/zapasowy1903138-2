// ============================================================================
// SportTabs – horizontal sport navigation (mobile; desktop uses the sidebar)
// ============================================================================
'use client'

import { cn } from '@/lib/utils'
import { sportsFromCounts } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { useFilterStore } from '@/store/filterStore'
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area'
import type { Sport } from '@/lib/types'

interface Props {
  sportCounts?: Record<string, number>
  className?: string
}

export function SportTabs({ sportCounts = {}, className }: Props) {
  const { sport: activeSport, setSport } = useFilterStore()

  // Built from the counts the API returned, so the per-sport numbers always add
  // up to the total. A hardcoded list is what left baseball out of the tabs.
  const sports = sportsFromCounts(sportCounts)
  const allCount = Object.values(sportCounts).reduce((a, b) => a + b, 0)

  return (
    <div className={cn('w-full border-b border-border bg-card', className)}>
      <ScrollArea className="w-full">
        <div className="flex items-center gap-1 px-2 py-1.5">
          <button
            onClick={() => setSport('all')}
            className={cn(
              'flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
              activeSport === 'all'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent hover:text-foreground',
            )}
          >
            Wszystkie
            <span className="text-[10px] tabular-nums opacity-70">{allCount}</span>
          </button>

          {sports.map(({ config, count }) => {
            const isActive = activeSport === config.id
            return (
              <button
                key={config.id}
                onClick={() => setSport(config.id as Sport)}
                className={cn(
                  'flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                )}
              >
                <SportIcon
                  sport={config.id}
                  className={cn('h-[18px] w-[18px]', !isActive && config.color)}
                />
                <span>{config.name}</span>
                <span className="text-[10px] tabular-nums opacity-70">{count}</span>
              </button>
            )
          })}
        </div>
        <ScrollBar orientation="horizontal" className="h-1.5" />
      </ScrollArea>
    </div>
  )
}
