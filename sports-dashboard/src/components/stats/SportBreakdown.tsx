// ============================================================================
// SportBreakdown – per-sport table with mini progress bars
// ============================================================================
'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { getSportConfig } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import type { SportStat } from '@/lib/types'

interface SportBreakdownProps {
  sportStats: SportStat[]
}

export function SportBreakdown({ sportStats }: SportBreakdownProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Podział na dyscypliny</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {sportStats.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-4">
            Brak danych.
          </p>
        )}
        {sportStats.map((stat) => {
          const cfg = getSportConfig(stat.sport)
          // The backend does not compute accuracy yet. Rendering 0% would read as
          // "nothing ever hit", so an unknown value is shown as unknown.
          const hasAccuracy = stat.accuracy != null
          const pct = Math.round((stat.accuracy ?? 0) * 100)

          return (
            <div key={stat.sport} className="flex items-center gap-3">
              {/* Icon */}
              <div className="shrink-0 w-8 h-8 rounded-md bg-muted flex items-center justify-center">
                <SportIcon sport={stat.sport} colored className="h-[18px] w-[18px]" />
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium">{cfg.name}</span>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-[10px]">
                      {stat.total} zdarzeń
                    </Badge>
                    <span className="text-sm font-mono font-semibold tabular-nums">
                      {hasAccuracy ? `${pct}%` : '—'}
                    </span>
                  </div>
                </div>
                {hasAccuracy ? (
                  <Progress value={pct} className="h-2" />
                ) : (
                  <p className="text-[10px] text-muted-foreground">
                    Skuteczność jeszcze nieliczona
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
