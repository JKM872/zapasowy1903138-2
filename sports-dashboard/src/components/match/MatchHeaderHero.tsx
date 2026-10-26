// ============================================================================
// MatchHeaderHero – dialog header: big logos/photos, kick-off, league, our pick, odds
// ============================================================================
'use client'
import Link from 'next/link'
import { Lock } from 'lucide-react'
import { PREDICTION_LABELS } from '@/lib/constants'
import { formatMatchDate, formatMatchTime, formatOdds } from '@/lib/format'
import { SideAvatar } from './SideAvatar'
import { RecommendationBadge } from './RecommendationBadge'
import { RadialProgress } from '@/components/charts/RadialProgress'
import { FormTimeline } from '@/components/charts/FormTimeline'
import type { Match } from '@/lib/types'

/** Same pick source as the board row, so the dialog never disagrees with it. */
function ourPick(match: Match): string | null {
  const sH = match.sofascore?.home ?? 0
  const sD = match.sofascore?.draw ?? 0
  const sA = match.sofascore?.away ?? 0
  const sMax = Math.max(sH, sD, sA)
  const sofa = sMax > 0 ? (sMax === sH ? '1' : sMax === sD ? 'X' : '2') : null
  return match.scoring?.pick ?? match.forebet?.prediction ?? sofa ?? null
}

function pickOdds(match: Match, pick: string | null): number | null {
  if (!pick || !match.odds) return null
  if (pick === '1') return match.odds.home ?? null
  if (pick === 'X') return match.odds.draw ?? null
  if (pick === '2') return match.odds.away ?? null
  return null
}

export function MatchHeaderHero({ match, conf }: { match: Match; conf: number }) {
  const pick = match.locked ? null : ourPick(match)
  const odds = pickOdds(match, pick)
  const pickName =
    pick === '1' ? match.homeTeam : pick === '2' ? match.awayTeam : null
  const leagueLine = [match.league, match.country].filter(Boolean).join(' · ')

  const side = (s: 'home' | 'away') => {
    const name = s === 'home' ? match.homeTeam : match.awayTeam
    const form = s === 'home' ? match.homeForm : match.awayForm
    return (
      <div className="flex min-w-0 flex-1 flex-col items-center gap-2">
        <SideAvatar match={match} side={s} size="xl" />
        <span className="text-center text-sm font-bold leading-tight">{name}</span>
        {form?.length > 0 && <FormTimeline form={form} teamName={name} maxItems={5} />}
      </div>
    )
  }

  return (
    <div className="py-3">
      <div className="flex items-start justify-between gap-2">
        {side('home')}
        <div className="flex shrink-0 flex-col items-center gap-1 px-2">
          <span className="text-2xl font-bold tabular-nums leading-none">
            {formatMatchTime(match.time)}
          </span>
          {match.date && (
            <span className="text-[11px] text-muted-foreground">{formatMatchDate(match.date)}</span>
          )}
          <RadialProgress value={conf} size={56} strokeWidth={4} label="conf" />
          <RecommendationBadge recommendation={match.gemini?.recommendation} size="sm" />
        </div>
        {side('away')}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-center gap-x-3 gap-y-1.5 text-xs">
        {leagueLine && <span className="text-muted-foreground">{leagueLine}</span>}
        {match.locked ? (
          <Link
            href="/pricing"
            className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 font-semibold text-amber-400 hover:bg-amber-500/20"
          >
            <Lock className="h-3 w-3" /> Pick locked – Premium
          </Link>
        ) : pick ? (
          <span className="inline-flex items-center gap-1.5 rounded border border-primary/40 bg-primary/10 px-2 py-0.5">
            <span className="text-muted-foreground">Our pick:</span>
            <span className="font-semibold text-foreground">
              {PREDICTION_LABELS[pick] ?? pick}
              {pickName ? ` (${pickName})` : ''}
            </span>
            {odds != null && (
              <span className="font-bold tabular-nums text-primary">@ {formatOdds(odds)}</span>
            )}
          </span>
        ) : null}
      </div>
    </div>
  )
}
