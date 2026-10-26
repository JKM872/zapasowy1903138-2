// ============================================================================
// TeamHistoryPanel – stored results per team (/api/teams): last games, form,
// home/away record and our Top Picks record on that team.
// Mounted only when its tab is open, so nothing is fetched until then.
// ============================================================================
'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { History, Loader2, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import { FormTimeline } from '@/components/charts/FormTimeline'
import { getTeamHistory, teamHref, type TeamHistory, type TeamRecord } from '@/lib/api'

const RESULT_CLS: Record<string, string> = {
  W: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  D: 'bg-zinc-500/15 text-zinc-500',
  L: 'bg-rose-500/15 text-rose-600 dark:text-rose-400',
}

const STATUS_LABEL: Record<string, string> = {
  won: 'Won', lost: 'Lost', draw: 'Draw (lost)', withdrawn: 'Withdrawn', pending: 'Pending',
}

function RecordLine({ label, r }: { label: string; r: TeamRecord }) {
  const n = r.w + r.d + r.l
  return (
    <div className="rounded-lg bg-muted/40 p-2.5 text-center">
      <p className="mb-1 text-[10px] text-muted-foreground">{label}</p>
      <p className="text-sm font-bold tabular-nums">
        {r.w}W · {r.d}D · {r.l}L
      </p>
      <p className="text-[10px] text-muted-foreground">
        {n ? `${Math.round((r.w / n) * 100)}% won` : 'No games'}
      </p>
    </div>
  )
}

function HistoryBody({ data, compact }: { data: TeamHistory; compact?: boolean }) {
  const op = data.ourPicks
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{data.team}</p>
          {data.aliases.length > 0 && (
            <p className="truncate text-[11px] text-muted-foreground">Also listed as {data.aliases.slice(0, 3).join(', ')}</p>
          )}
        </div>
        {data.form && (
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground">Form</span>
            {/* API form is newest first; the timeline reads left to right, newest last. */}
            <FormTimeline form={data.form.split('').reverse()} teamName={data.team} maxItems={5} />
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <RecordLine label="At home" r={data.home} />
        <RecordLine label="Away" r={data.away} />
      </div>

      {data.last.length > 0 && (
        <ul className="divide-y rounded-lg border text-xs" aria-label={`Last results of ${data.team}`}>
          {data.last.map((g, i) => (
            <li key={`${g.date}-${i}`} className="flex items-center gap-2 px-2.5 py-1.5">
              <span className="w-[4.5rem] shrink-0 tabular-nums text-muted-foreground">{g.date}</span>
              <span className="w-9 shrink-0 text-[10px] uppercase text-muted-foreground">{g.venue === 'home' ? 'Home' : 'Away'}</span>
              <span className="min-w-0 flex-1 truncate">
                <span className="text-muted-foreground">{g.venue === 'home' ? 'vs' : '@'}</span> {g.opponent}
              </span>
              <span className="tabular-nums font-medium">{g.score}</span>
              <span
                className={cn('w-5 rounded text-center text-[10px] font-bold', RESULT_CLS[g.result])}
                title={g.result === 'W' ? 'Win' : g.result === 'D' ? 'Draw' : 'Loss'}
              >
                {g.result}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="rounded-lg border p-2.5 text-xs">
        <p className="font-medium">Our Top Picks on this team</p>
        {op.picks.length === 0 ? (
          <p className="mt-0.5 text-muted-foreground">No settled Top Picks on this team yet.</p>
        ) : (
          <>
            <p className="mt-0.5 text-muted-foreground">
              {op.won}/{op.n} won
              {op.roi != null && <> · ROI {op.roi > 0 ? '+' : ''}{op.roi.toFixed(1)}% (1-unit stake)</>}
              {' '}· withdrawn picks not counted
            </p>
            {!compact && (
              <ul className="mt-1.5 space-y-0.5">
                {op.picks.map((p, i) => (
                  <li key={`${p.date}-${i}`} className="flex flex-wrap gap-x-2">
                    <span className="tabular-nums text-muted-foreground">{p.date}</span>
                    <span>{p.match}</span>
                    {p.pick ? <span>Pick: <b>{p.pick}</b>{p.odds ? ` @ ${p.odds.toFixed(2)}` : ''}</span>
                      : <span className="text-muted-foreground">Selection hidden until kick-off</span>}
                    <span className="text-muted-foreground">{STATUS_LABEL[p.status] ?? p.status}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      <p className="text-[10px] text-muted-foreground">
        {data.games} stored results · source: {data.sources.join(' + ') || '—'} · score shown with this team first
      </p>
    </div>
  )
}

/** One team's history; used by the match dialog and the /team page. */
export function TeamHistoryCard({ name, sport, limit = 10, compact = false }: {
  name: string
  sport: string
  limit?: number
  compact?: boolean
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['team-history', sport, name, limit],
    queryFn: () => getTeamHistory(name, sport, limit),
    staleTime: 600_000,
    enabled: Boolean(name && sport),
  })

  return (
    <section className="rounded-xl border bg-card p-4" aria-label={`Team history: ${name}`}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-medium">
          <History className="h-4 w-4 text-sky-500" /> {name}
        </span>
        {compact && (
          <Link href={teamHref(name, sport)} className="text-xs text-primary hover:underline">
            Full history
          </Link>
        )}
      </div>
      {isLoading && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading team history…
        </p>
      )}
      {isError && (
        <p className="flex items-center gap-2 text-xs text-red-600" role="alert">
          <TriangleAlert className="h-3.5 w-3.5" /> Couldn’t load team history.
        </p>
      )}
      {data && !data.found && (
        <div className="text-xs text-muted-foreground">
          <p>No stored results for this team yet.</p>
          {data.suggestions.length > 0 && (
            <p className="mt-1">
              Did you mean{' '}
              {data.suggestions.map((s, i) => (
                <span key={s}>
                  {i > 0 && ', '}
                  <Link href={teamHref(s, sport)} className="text-primary hover:underline">{s}</Link>
                </span>
              ))}
              ?
            </p>
          )}
        </div>
      )}
      {data && data.found && <HistoryBody data={data.data} compact={compact} />}
    </section>
  )
}

/** Both teams of a match, side by side on wide screens. */
export function TeamHistoryPanel({ sport, homeTeam, awayTeam }: {
  sport: string
  homeTeam: string
  awayTeam: string
}) {
  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        <TeamHistoryCard name={homeTeam} sport={sport} limit={6} compact />
        <TeamHistoryCard name={awayTeam} sport={sport} limit={6} compact />
      </div>
      <p className="text-[10px] text-muted-foreground">
        Team history from our stored match results (last 400 days). Past results do not predict future results.
      </p>
    </div>
  )
}
