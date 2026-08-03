// ============================================================================
// AccuracyChart – accuracy per sport, or prediction coverage when unavailable
// ============================================================================
'use client'

import {
  ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { getSportConfig } from '@/lib/constants'
import type { SportStat } from '@/lib/types'

interface AccuracyChartProps {
  sportStats: SportStat[]
}

/** Chart colours have to be plain values, so they cannot reuse the Tailwind classes. */
const SPORT_COLORS: Record<string, string> = {
  football: '#10b981',
  tennis: '#8b5cf6',
  basketball: '#f59e0b',
  handball: '#14b8a6',
  hockey: '#0ea5e9',
  volleyball: '#ec4899',
  baseball: '#f97316',
  table_tennis: '#84cc16',
}

function sportColor(sportId: string) {
  return SPORT_COLORS[sportId] ?? '#64748b'
}

export function AccuracyChart({ sportStats }: AccuracyChartProps) {
  const rated = sportStats.filter(s => s.accuracy != null)

  /**
   * Accuracy is not computed by the backend yet. Plotting `accuracy ?? 0` drew a
   * flat chart at zero, which reads as "nothing ever hit". When accuracy is
   * missing the chart falls back to prediction coverage, which is real data.
   */
  const showAccuracy = rated.length > 0

  const data = (showAccuracy ? rated : sportStats).map(s => ({
    id: s.sport,
    sport: getSportConfig(s.sport).name,
    value: showAccuracy
      ? Number(((s.accuracy as number) * 100).toFixed(1))
      : s.total > 0
        ? Number(((s.with_predictions / s.total) * 100).toFixed(1))
        : 0,
    total: s.total,
    withPredictions: s.with_predictions,
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {showAccuracy ? 'Skuteczność według dyscypliny' : 'Pokrycie predykcjami'}
        </CardTitle>
        <CardDescription>
          {showAccuracy
            ? 'Na podstawie rozstrzygniętych zdarzeń'
            : 'Skuteczność nie jest jeszcze liczona, dlatego pokazujemy udział zdarzeń z predykcją'}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Brak danych.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="sport" tick={{ fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={56} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} unit="%" />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null
                  const d = payload[0].payload
                  return (
                    <div className="rounded-md border bg-popover px-3 py-2 text-sm text-popover-foreground shadow-lg">
                      <p className="font-semibold">{d.sport}</p>
                      <p>
                        {showAccuracy ? 'Skuteczność' : 'Pokrycie'}:{' '}
                        <span className="font-mono">{d.value}%</span>
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {d.withPredictions} z {d.total} zdarzeń
                      </p>
                    </div>
                  )
                }}
              />
              <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={48}>
                {data.map(entry => (
                  <Cell key={entry.id} fill={sportColor(entry.id)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}
