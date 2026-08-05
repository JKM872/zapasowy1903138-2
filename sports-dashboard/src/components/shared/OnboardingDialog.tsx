// ============================================================================
// OnboardingDialog – asks a new reader which sports and leagues they follow
// ============================================================================
'use client'

import { useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { sportsFromCounts } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { usePreferences } from '@/hooks/usePreferences'
import type { Match } from '@/lib/types'

interface Props {
  /** Per-sport totals, so only sports with events today are offered. */
  sportCounts?: Record<string, number>
  /** Current page of events, used to offer the busiest leagues. */
  matches?: Match[]
}

const MAX_LEAGUE_CHOICES = 12

/**
 * Shown once, right after a reader signs in for the first time. The answers
 * decide what the board leads with — without them a newcomer meets 670 events in
 * time order, which tells them nothing about what is worth their attention.
 */
export function OnboardingDialog({ sportCounts = {}, matches = [] }: Props) {
  const { needsOnboarding, save } = usePreferences()
  const [dismissed, setDismissed] = useState(false)
  const [sports, setSports] = useState<string[]>([])
  const [leagues, setLeagues] = useState<string[]>([])

  const sportOptions = sportsFromCounts(sportCounts)

  // Leagues of the chosen sports, busiest first. Offering every league would be
  // a list of hundreds; the busiest dozen covers most of what a reader follows.
  const leagueOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const m of matches) {
      if (!m.league) continue
      if (sports.length > 0 && !sports.includes(m.sport)) continue
      counts.set(m.league, (counts.get(m.league) ?? 0) + 1)
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'pl'))
      .slice(0, MAX_LEAGUE_CHOICES)
  }, [matches, sports])

  function toggle(list: string[], value: string, set: (v: string[]) => void) {
    set(list.includes(value) ? list.filter(v => v !== value) : [...list, value])
  }

  const open = needsOnboarding && !dismissed

  function finish(selectedSports: string[], selectedLeagues: string[]) {
    // Saved even when empty: that records "asked and answered", so the
    // questionnaire does not reappear for someone who chose to skip it.
    save.mutate(
      { sports: selectedSports, leagues: selectedLeagues },
      { onSettled: () => setDismissed(true) },
    )
  }

  return (
    <Dialog open={open} onOpenChange={o => !o && finish([], [])}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Co Cię interesuje?</DialogTitle>
          <DialogDescription>
            Zaznacz dyscypliny i ligi, które śledzisz. Będziemy pokazywać je
            najwyżej. Zmienisz to później w każdej chwili.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Dyscypliny
            </p>
            <div className="flex flex-wrap gap-1.5">
              {sportOptions.map(({ config, count }) => {
                const active = sports.includes(String(config.id))
                return (
                  <button
                    key={config.id}
                    onClick={() => toggle(sports, String(config.id), setSports)}
                    aria-pressed={active}
                    className={cn(
                      'flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-sm transition-colors',
                      active
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'border-border hover:bg-accent',
                    )}
                  >
                    <SportIcon
                      sport={config.id}
                      className={cn('h-4 w-4', !active && config.color)}
                    />
                    {config.name}
                    <span className="text-[10px] tabular-nums opacity-70">{count}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {leagueOptions.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Ligi {sports.length > 0 && '(z wybranych dyscyplin)'}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {leagueOptions.map(([league, count]) => {
                  const active = leagues.includes(league)
                  return (
                    <button
                      key={league}
                      onClick={() => toggle(leagues, league, setLeagues)}
                      aria-pressed={active}
                      title={league}
                      className={cn(
                        'max-w-[220px] truncate rounded-md border px-2 py-1 text-xs transition-colors',
                        active
                          ? 'border-primary bg-primary text-primary-foreground'
                          : 'border-border hover:bg-accent',
                      )}
                    >
                      {league}
                      <span className="ml-1 tabular-nums opacity-70">{count}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 pt-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => finish([], [])}
            disabled={save.isPending}
          >
            Pomiń
          </Button>
          <Button
            size="sm"
            className="ml-auto"
            onClick={() => finish(sports, leagues)}
            disabled={save.isPending}
          >
            {save.isPending && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
            Zapisz
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
