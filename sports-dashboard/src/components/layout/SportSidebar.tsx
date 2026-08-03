// ============================================================================
// SportSidebar – bookmaker-style sport tree with nested leagues
// ============================================================================
'use client'

import { useMemo } from 'react'
import { ChevronDown, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { sportsFromCounts } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { useFilterStore } from '@/store/filterStore'
import type { Match, Sport } from '@/lib/types'

interface Props {
  /** Per-sport totals from the API. Drives the list, so counts always tally. */
  sportCounts?: Record<string, number>
  /** Current page of matches, used to list leagues under the selected sport. */
  matches?: Match[]
  /** Called after a selection, so the mobile sheet can close itself. */
  onNavigate?: () => void
  className?: string
}

export function SportSidebar({
  sportCounts = {},
  matches = [],
  onNavigate,
  className,
}: Props) {
  const { sport: activeSport, league: activeLeague, setSport, setLeague } = useFilterStore()

  const sports = sportsFromCounts(sportCounts)
  const total = Object.values(sportCounts).reduce((a, b) => a + b, 0)

  /**
   * Leagues of the selected sport, most events first. Derived from the loaded
   * page rather than a separate endpoint, so it mirrors exactly what the list
   * below can show.
   */
  const leagues = useMemo(() => {
    if (activeSport === 'all') return []
    const counts = new Map<string, number>()
    for (const m of matches) {
      if (m.sport !== activeSport || !m.league) continue
      counts.set(m.league, (counts.get(m.league) ?? 0) + 1)
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'pl'))
  }, [matches, activeSport])

  function selectSport(id: Sport | 'all') {
    setSport(id)
    if (id === 'all') onNavigate?.()
  }

  return (
    <nav className={cn('flex flex-col gap-1 text-sm', className)} aria-label="Dyscypliny">
      <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        Dyscypliny
      </p>

      <button
        onClick={() => selectSport('all')}
        className={cn(
          'flex items-center gap-2 rounded-md px-2 py-2 text-left transition-colors',
          activeSport === 'all'
            ? 'bg-primary text-primary-foreground font-semibold'
            : 'text-foreground/80 hover:bg-panel-hover',
        )}
      >
        <SportIcon sport="unknown" className="text-[18px]" />
        <span className="flex-1">Wszystkie</span>
        <span className="text-xs tabular-nums opacity-70">{total}</span>
      </button>

      {sports.map(({ config, count }) => {
        const isActive = activeSport === config.id
        return (
          <div key={config.id}>
            <button
              onClick={() => selectSport(config.id as Sport)}
              aria-expanded={isActive}
              className={cn(
                'flex w-full items-center gap-2 rounded-md px-2 py-2 text-left transition-colors',
                isActive
                  ? 'bg-primary text-primary-foreground font-semibold'
                  : 'text-foreground/80 hover:bg-panel-hover',
              )}
            >
              <SportIcon
                sport={config.id}
                className={cn('text-[18px]', !isActive && config.color)}
              />
              <span className="flex-1 truncate">{config.name}</span>
              <span className="text-xs tabular-nums opacity-70">{count}</span>
              {isActive && leagues.length > 0 && <ChevronDown className="h-3.5 w-3.5" />}
            </button>

            {/* Leagues of the selected sport */}
            {isActive && leagues.length > 0 && (
              <ul className="mt-0.5 mb-1 space-y-0.5 border-l border-border pl-2 ml-3">
                {activeLeague && (
                  <li>
                    <button
                      onClick={() => { setLeague(null); onNavigate?.() }}
                      className="flex w-full items-center gap-1 rounded px-2 py-1 text-left text-xs text-primary hover:bg-panel-hover"
                    >
                      <X className="h-3 w-3" />
                      Pokaż wszystkie ligi
                    </button>
                  </li>
                )}
                {leagues.map(([league, count]) => (
                  <li key={league}>
                    <button
                      onClick={() => { setLeague(league); onNavigate?.() }}
                      title={league}
                      className={cn(
                        'flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs transition-colors',
                        activeLeague === league
                          ? 'bg-accent text-accent-foreground font-semibold'
                          : 'text-muted-foreground hover:bg-panel-hover hover:text-foreground',
                      )}
                    >
                      <span className="flex-1 truncate">{league}</span>
                      <span className="tabular-nums opacity-70">{count}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )
      })}

      {sports.length === 0 && (
        <p className="px-2 py-4 text-xs text-muted-foreground">
          Brak zdarzeń dla wybranego dnia.
        </p>
      )}
    </nav>
  )
}
