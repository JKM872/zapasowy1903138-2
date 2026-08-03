// ============================================================================
// StatsOverview  – top-level KPI cards
// ============================================================================
'use client'

import {
  BarChart3, Target, TrendingUp, Trophy, Percent, Clock,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { getSportConfig } from '@/lib/constants'
import type { StatsData } from '@/lib/types'

interface StatCardProps {
  label: string
  value: string | number
  subtitle?: string
  icon: React.ElementType
  trend?: number // positive = green, negative = red, undefined = neutral
}

function StatCard({ label, value, subtitle, icon: Icon, trend }: StatCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold tabular-nums">{value}</div>
        {subtitle && (
          <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
            {trend !== undefined && (
              <span className={trend >= 0 ? 'text-emerald-500' : 'text-red-500'}>
                {trend >= 0 ? '+' : ''}{trend}%
              </span>
            )}
            {subtitle}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

interface StatsOverviewProps {
  data: StatsData
}

export function StatsOverview({ data }: StatsOverviewProps) {
  /**
   * The backend does not compute accuracy or ROI yet, so both arrive as null.
   * Rendering "0.0%" claimed nothing ever hit, and picking the best sport with
   * `accuracy ?? 0` always returned the first entry, labelling it "najwyższa
   * skuteczność" on no evidence. Unknown values are shown as unknown.
   */
  const rated = data.sport_breakdown?.filter(s => s.accuracy != null) ?? []
  const bestSport = rated.length
    ? rated.reduce((best, cur) => ((cur.accuracy ?? 0) > (best.accuracy ?? 0) ? cur : best))
    : null

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
      <StatCard
        icon={BarChart3}
        label="Zdarzenia"
        value={data.total_matches.toLocaleString('pl-PL')}
        subtitle="zebrane łącznie"
      />
      <StatCard
        icon={Target}
        label="Z predykcją"
        value={data.matches_with_predictions.toLocaleString('pl-PL')}
        subtitle="z Forebet"
      />
      <StatCard
        icon={Percent}
        label="Skuteczność (30 dni)"
        value={data.accuracy_30d != null ? `${data.accuracy_30d.toFixed(1)}%` : '—'}
        subtitle={data.accuracy_30d != null ? 'trafione typy' : 'jeszcze nieliczona'}
        trend={
          data.accuracy_30d != null
            ? +(data.accuracy_30d - 50).toFixed(1)
            : undefined
        }
      />
      <StatCard
        icon={Trophy}
        label="Najlepsza dyscyplina"
        value={bestSport ? getSportConfig(bestSport.sport).name : '—'}
        subtitle={bestSport ? 'najwyższa skuteczność' : 'brak danych o skuteczności'}
      />
      <StatCard
        icon={TrendingUp}
        label="Z kursami"
        value={(data.matches_with_odds ?? 0).toLocaleString('pl-PL')}
        subtitle="kursy bukmacherskie"
      />
      <StatCard
        icon={Clock}
        label="ROI (30 dni)"
        value={data.roi_30d != null ? `${data.roi_30d.toFixed(1)}%` : '—'}
        subtitle={data.roi_30d != null ? 'zwrot z inwestycji' : 'jeszcze nieliczony'}
      />
    </div>
  )
}
