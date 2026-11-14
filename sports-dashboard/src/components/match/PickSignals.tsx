'use client'

import type { OddsMove, OddsMoveSide, TeamNews, TeamNewsPlayer } from '@/lib/types'
import { cn } from '@/lib/utils'

function arrow(mv: OddsMoveSide): string {
  if (mv.direction === 'flat') return `= ${Math.round(mv.changePct)}%`
  return `${mv.direction === 'down' ? '▼' : '▲'}${Math.abs(Math.round(mv.changePct))}%`
}

/** Small ▲/▼ % chip for the picked side. Green = market agrees, red = against. */
export function OddsMoveBadge({ move, className }: { move?: OddsMove | null; className?: string }) {
  const mv = move?.pick ?? move?.opponent
  if (!move || !mv) return null
  const tone = move.stance === 'with' ? 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10'
    : move.stance === 'against' ? 'text-rose-400 border-rose-500/40 bg-rose-500/10'
      : 'text-muted-foreground border-border'
  return (
    <span
      title={move.line}
      className={cn('inline-flex shrink-0 items-center rounded border px-1 py-0 text-[9px] font-semibold tabular-nums', tone, className)}
    >
      {move.pick ? '' : 'opp '}{arrow(mv)}
    </span>
  )
}

export function OddsMoveLine({ move, className }: { move?: OddsMove | null; className?: string }) {
  if (!move?.line) return null
  const tone = move.stance === 'with' ? 'text-emerald-400' : move.stance === 'against' ? 'text-rose-400' : 'text-muted-foreground'
  return <p className={cn('text-xs', tone, className)}>📈 {move.line}</p>
}

/** "2 stars out" for our side (red) and the opponent (neutral). */
export function TeamNewsBadge({ news, className }: { news?: TeamNews | null; className?: string }) {
  if (!news || (!news.badgePick && !news.badgeOpponent)) return null
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1 text-[9px] font-semibold', className)} title={news.summary || undefined}>
      {news.badgePick && (
        <span className="rounded border border-rose-500/40 bg-rose-500/10 px-1 text-rose-400">Pick: {news.badgePick}</span>
      )}
      {news.badgeOpponent && (
        <span className="rounded border border-sky-500/40 bg-sky-500/10 px-1 text-sky-400">Opp: {news.badgeOpponent}</span>
      )}
    </span>
  )
}

export function TeamNewsLine({ news, className }: { news?: TeamNews | null; className?: string }) {
  const text = news?.summary || (news ? [news.badgePick && `our pick ${news.badgePick}`,
    news.badgeOpponent && `opponent ${news.badgeOpponent}`].filter(Boolean).join('; ') : '')
  return <p className={cn('text-xs text-muted-foreground', className)}>🩹 Team news: {text || 'No confirmed team news yet'}</p>
}

function PlayerList({ title, players }: { title: string; players: TeamNewsPlayer[] }) {
  if (!players.length) return null
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase text-muted-foreground">{title}</p>
      <ul className="mt-1 space-y-0.5 text-sm">
        {players.map((p, i) => (
          <li key={`${p.name}-${i}`} className={cn(p.importance === 'star' && 'font-semibold text-amber-400')}>
            {p.importance === 'star' ? '★ ' : p.importance === 'key' ? '• ' : ''}{p.name}
            {p.reason && <span className="text-xs text-muted-foreground"> — {p.reason}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

function SideNews({ team, players, lineup, ours }: { team: string; players: TeamNewsPlayer[]; lineup?: { name: string; star?: boolean }[] | null; ours: boolean }) {
  const out = players.filter((p) => p.status !== 'doubtful')
  const doubt = players.filter((p) => p.status === 'doubtful')
  return (
    <div className="space-y-2 rounded-lg border p-3">
      <p className="text-sm font-semibold">{team}{ours && <span className="ml-1 text-[10px] text-emerald-400">(our pick)</span>}</p>
      {!players.length && <p className="text-xs text-muted-foreground">No absences reported</p>}
      <PlayerList title="Out" players={out} />
      <PlayerList title="Doubtful" players={doubt} />
      {lineup && lineup.length > 0 && (
        <div>
          <p className="text-[11px] font-semibold uppercase text-muted-foreground">Confirmed XI</p>
          <p className="mt-1 text-xs">
            {lineup.map((p, i) => (
              <span key={`${p.name}-${i}`} className={cn(p.star && 'font-semibold text-amber-400')}>{i ? ', ' : ''}{p.name}</span>
            ))}
          </p>
        </div>
      )}
    </div>
  )
}

export function TeamNewsPanel({ news, home, away }: { news?: TeamNews | null; home: string; away: string }) {
  if (!news) return <p className="py-6 text-center text-sm text-muted-foreground">No confirmed team news yet</p>
  return (
    <div className="space-y-3">
      <p className="text-sm">{news.summary || 'No confirmed team news yet'}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <SideNews team={home} players={news.home} lineup={news.lineup?.home} ours={news.side === 'home'} />
        <SideNews team={away} players={news.away} lineup={news.lineup?.away} ours={news.side === 'away'} />
      </div>
      <p className="text-[10px] text-muted-foreground">
        Source: {news.source}{news.confirmedLineup ? ' · confirmed line-ups' : ' · line-ups not confirmed yet'}
        {news.checkedAt ? ` · checked ${new Date(news.checkedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
      </p>
    </div>
  )
}
