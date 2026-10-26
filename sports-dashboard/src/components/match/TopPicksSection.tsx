// ============================================================================
// TopPicksSection – Horizontal scroll hero for AI HIGH picks (SofaScore style)
// ============================================================================
'use client'

import { Flame, Sparkles, Zap } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { PREDICTION_COLORS } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { formatMatchTime, formatOdds } from '@/lib/format'
import { SideAvatar } from '@/components/match/SideAvatar'
import { RadialProgress } from '@/components/charts/RadialProgress'
import { StakeChip } from '@/components/top/StakeChip'
import type { Match } from '@/lib/types'
import { topStatus, type TopPick } from '@/lib/api'

const SOURCE: Record<string, string> = {
  pinnacle: 'Pinnacle',
  oddssafari: 'OddsSafari',
  livesport: 'Livesport',
}

function sourceName(s?: string | null) {
  return s ? SOURCE[s] ?? s : 'unknown source'
}

/** Line-ups label (R3.3b): only when a pre-kick-off check ran or was missed. */
function lineupsLabel(p: TopPick): string | null {
  if ((p.availStatus === 'ok' || p.availStatus === 'block') && typeof p.availMinsToKick === 'number') {
    return `Line-ups checked ${p.availMinsToKick} min before kick-off`
  }
  if (p.finalCheckMissed || p.availStatus === 'unknown' || p.availStatus === 'stale') return 'Line-ups unverified'
  return null
}

/**
 * Detail line of a TOP pick on /top: suggested stake, best price, the minimum
 * profitable price, closing price + CLV, line-up check and the hockey OT note.
 * Every field is optional – picks published before these fields existed simply
 * show fewer items.
 */
export function TopPickDetails({ pick: p }: { pick: TopPick }) {
  const status = topStatus(p)
  if (status === 'withdrawn') {
    return (
      <div className="basis-full pl-7 text-xs text-muted-foreground">
        Withdrawn: {p.withdrawReason ?? p.result?.reason ?? 'reason not recorded'}
      </div>
    )
  }
  const lineups = lineupsLabel(p)
  const showTwoWay = p.oddsMarket === '2way_equiv' && typeof p.odds2 === 'number' && p.odds2 !== p.odds
  return (
    <div className="flex basis-full flex-wrap items-center gap-x-3 gap-y-1 pl-7 text-xs text-muted-foreground">
      <StakeChip stakePct={p.stakePct} />
      {showTwoWay && <span className="tabular-nums">2-way price {formatOdds(p.odds2)}</span>}
      {typeof p.bestOdds === 'number' && (
        <span className="tabular-nums">
          Best price <b className="text-foreground">{formatOdds(p.bestOdds)}</b> ({sourceName(p.bestOddsSource)}
          {p.booksCount && p.booksCount > 1 ? `, ${p.booksCount} books` : ''})
        </span>
      )}
      {typeof p.floorOdds === 'number' && p.floorOdds > 1 && (
        <span className="tabular-nums">Don&apos;t bet below <b className="text-foreground">{formatOdds(p.floorOdds)}</b></span>
      )}
      {typeof p.closingOdds === 'number' && (
        <span className="tabular-nums">
          Closing {formatOdds(p.closingOdds)} ({sourceName(p.closingSource)}{p.closingApprox ? ', approx.' : ''})
          {typeof p.clvPct === 'number' && (
            <> · CLV <b className={cn(
              p.clvPct > 0 && 'text-emerald-600 dark:text-emerald-400',
              p.clvPct < 0 && 'text-red-600 dark:text-red-400',
            )}>{p.clvPct > 0 ? '+' : ''}{p.clvPct.toFixed(1)}%</b></>
          )}
        </span>
      )}
      {lineups && <span>{lineups}</span>}
      {p.sport === 'hockey' && <span>Price includes overtime</span>}
    </div>
  )
}

interface Props {
  matches: Match[]
  onSelect?: (match: Match) => void
  isLoading?: boolean
}

function TopPickCard({ match, onSelect }: { match: Match; onSelect?: (m: Match) => void }) {
  const geminiConf = match.gemini?.confidence ?? match.forebet?.probability ?? 0

  return (
    <Card
      className={cn(
        'relative overflow-hidden cursor-pointer transition-all duration-200',
        'hover:shadow-2xl hover:-translate-y-1',
        'min-w-[260px] max-w-[300px] shrink-0',
        'border-red-500/20 bg-gradient-to-br from-background via-background to-red-500/5',
      )}
      onClick={() => onSelect?.(match)}
    >
      {/* Accent gradient top */}
      <div className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-red-500 via-orange-500 to-amber-500" />

      <CardContent className="p-3.5 space-y-3">
        {/* Header: sport + time */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <SportIcon sport={match.sport} colored className="h-3.5 w-3.5" />
            <span className="text-[10px] text-muted-foreground truncate max-w-[120px]">
              {match.league ?? match.sport}
            </span>
          </div>
          <span className="text-[10px] text-muted-foreground tabular-nums">
            {formatMatchTime(match.time)}
          </span>
        </div>

        {/* Teams vs layout */}
        <div className="flex items-center gap-3">
          <div className="flex-1 space-y-2 min-w-0">
            <div className="flex items-center gap-2">
              <SideAvatar match={match} side="home" size="sm" />
              <span className="font-bold text-sm truncate">{match.homeTeam}</span>
            </div>
            <div className="flex items-center gap-2">
              <SideAvatar match={match} side="away" size="sm" />
              <span className="font-bold text-sm truncate">{match.awayTeam}</span>
            </div>
          </div>
          <RadialProgress value={geminiConf} size={44} strokeWidth={3} color="#ef4444" />
        </div>

        {/* Bottom row: prediction + odds */}
        <div className="flex items-center justify-between pt-1.5 border-t border-border/30">
          <div className="flex items-center gap-1.5">
            {match.forebet?.prediction && (
              <Badge className={cn('text-[9px] px-1 py-0', PREDICTION_COLORS[match.forebet.prediction] ?? '')}>
                {match.forebet.prediction}
              </Badge>
            )}
            {match.forebet?.probability != null && (
              <span className="text-[10px] font-medium">{match.forebet.probability}%</span>
            )}
          </div>
          {match.odds && (
            <span className="text-[10px] font-mono text-muted-foreground tabular-nums">
              {formatOdds(match.odds.home)} / {match.odds.draw != null ? `${formatOdds(match.odds.draw)} / ` : ''}{formatOdds(match.odds.away)}
            </span>
          )}
        </div>

        {/* Gemini reasoning */}
        {match.gemini?.reasoning && (
          <p className="text-[10px] text-muted-foreground line-clamp-2 leading-relaxed">
            {match.gemini.reasoning}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export function TopPicksSection({ matches, onSelect, isLoading }: Props) {
  const topPicks = matches
    .filter((m) => m.gemini?.recommendation === 'HIGH')
    .sort((a, b) => (b.gemini?.confidence ?? 0) - (a.gemini?.confidence ?? 0))
    .slice(0, 6)

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Flame className="h-5 w-5 text-red-500" />
          <h2 className="text-lg font-bold">AI Top Picks</h2>
        </div>
        <div className="flex gap-3 overflow-hidden">
          {[1, 2, 3].map((i) => (
            <div key={i} className="min-w-[260px] h-40 rounded-xl animate-pulse bg-muted shrink-0" />
          ))}
        </div>
      </div>
    )
  }

  if (topPicks.length === 0) {
    return (
      <Card className="border-dashed border border-muted-foreground/15 bg-muted/30">
        <CardContent className="flex items-center gap-3 py-5 px-4">
          <Sparkles className="h-6 w-6 text-muted-foreground/40 shrink-0" />
          <div>
            <p className="text-sm font-medium text-muted-foreground">
              No top AI picks available
            </p>
            <p className="text-xs text-muted-foreground/60 mt-0.5">
              Gemini AI highlights the best opportunities when data is ready.
            </p>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-red-500/10">
            <Zap className="h-4 w-4 text-red-500" />
          </div>
          <h2 className="text-lg font-bold">AI Top Picks</h2>
          <Badge className="bg-red-500 text-white text-[10px] font-bold">{topPicks.length}</Badge>
        </div>
        <span className="text-[11px] text-muted-foreground flex items-center gap-1">
          Powered by Gemini AI
        </span>
      </div>

      {/* Horizontal scroll container */}
      <div className="flex gap-3 overflow-x-auto pb-2 snap-x snap-mandatory scrollbar-thin scrollbar-track-transparent scrollbar-thumb-muted-foreground/20">
        {topPicks.map((m) => (
          <div key={m.id} className="snap-start">
            <TopPickCard match={m} onSelect={onSelect} />
          </div>
        ))}
      </div>
    </div>
  )
}
