// ============================================================================
// SofascoreWidgets – "Match Centre": official SofaScore embeds (widgets.sofascore.com)
// Source: https://corporate.sofascore.com/widgets (free, copy-paste iframe embeds)
// Only widgets verified by screenshot are listed here; see sofascore-widgets.md
// (tested 2026-10-26: upcoming 16363904 Chelsea–Man Utd, finished 16483703
// Rizespor–Trabzonspor, live 16685244 Walsall–Salford).
// ============================================================================
'use client'
import { CalendarClock, ExternalLink, Radio } from 'lucide-react'
import type { Sport, LiveScore } from '@/lib/types'

const WIDGET_HOST = 'https://widgets.sofascore.com/embed'

interface Widget {
  key: string
  label: string
  height: number
  /** 'pre' = shown before kick-off, 'live' = shown only once the match is live/finished */
  phase: 'pre' | 'live'
  sports: string[]
}

const WIDGETS: Widget[] = [
  // Before kick-off this renders the fixture card (teams + kick-off time); it fills
  // with the momentum graph once the match starts.
  { key: 'attackMomentum', label: 'Match overview', height: 286, phase: 'pre', sports: ['football'] },
  // Lineups render blank until SofaScore has lineups, so they are live/finished only.
  { key: 'lineups', label: 'Lineups & player ratings', height: 760, phase: 'live', sports: ['football'] },
]

interface Props {
  eventId?: number | null
  sport: Sport | string
  homeTeam: string
  awayTeam: string
  status?: LiveScore['status']
  /** Match date (YYYY-MM-DD) and kick-off time (HH:MM), used when no live status is known. */
  date?: string
  time?: string
}

/** Live section is shown when the match is live/finished, or (no status) kick-off has passed. */
function hasStarted(status?: LiveScore['status'], date?: string, time?: string): boolean {
  if (status) return status !== 'scheduled'
  if (!time) return false
  // Rows without a date belong to the board's current day.
  const day = date || new Date().toLocaleDateString('en-CA')
  const kickoff = new Date(`${day}T${time}`)
  return !Number.isNaN(kickoff.getTime()) && kickoff.getTime() <= Date.now()
}

function WidgetFrame({ w, eventId, homeTeam, awayTeam }: { w: Widget; eventId: number; homeTeam: string; awayTeam: string }) {
  return (
    <section className="rounded-xl border bg-[#1b1d22] p-2 space-y-2" aria-label={w.label}>
      <div className="flex items-center gap-2 px-2 pt-1 text-sm font-medium">
        <Radio className="h-4 w-4 text-emerald-500" /> {w.label}
      </div>
      <iframe
        src={`${WIDGET_HOST}/${w.key}?id=${eventId}&widgetTheme=dark`}
        title={`Sofascore ${w.label.toLowerCase()}: ${homeTeam} vs ${awayTeam}`}
        loading="lazy"
        className="block w-full rounded-lg border-0"
        style={{ height: w.height }}
        referrerPolicy="no-referrer-when-downgrade"
        sandbox="allow-scripts allow-same-origin allow-popups"
      />
    </section>
  )
}

export function SofascoreWidgets({ eventId, sport, homeTeam, awayTeam, status, date, time }: Props) {
  if (!eventId) {
    return (
      <p className="text-sm text-muted-foreground text-center py-8">
        Match Centre widgets appear once this match is matched on Sofascore.
      </p>
    )
  }
  const sportSlug = String(sport || 'football')
  const matchUrl = `https://www.sofascore.com/${sportSlug}/match/${eventId}`
  const widgets = WIDGETS.filter((w) => w.sports.includes(sportSlug))
  const pre = widgets.filter((w) => w.phase === 'pre')
  const live = widgets.filter((w) => w.phase === 'live')
  const started = hasStarted(status, date, time)

  return (
    <div className="space-y-5">
      {widgets.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-6">
          Embedded widgets are not available for this sport yet.
        </p>
      ) : (
        <>
          <div className="space-y-3">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <CalendarClock className="h-4 w-4 text-sky-500" /> Before the match
            </h3>
            {pre.map((w) => (
              <WidgetFrame key={w.key} w={w} eventId={eventId} homeTeam={homeTeam} awayTeam={awayTeam} />
            ))}
          </div>
          {live.length > 0 && (
            <div className="space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Radio className="h-4 w-4 text-red-500" /> Live
              </h3>
              {started ? (
                live.map((w) => (
                  <WidgetFrame key={w.key} w={w} eventId={eventId} homeTeam={homeTeam} awayTeam={awayTeam} />
                ))
              ) : (
                <p className="text-sm text-muted-foreground rounded-xl border px-3 py-4 text-center">
                  Lineups and player ratings appear here once the match kicks off.
                </p>
              )}
            </div>
          )}
        </>
      )}
      <p className="text-xs text-muted-foreground text-center">
        Data by{' '}
        <a
          href={matchUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-0.5 underline underline-offset-2 hover:text-foreground"
        >
          Sofascore <ExternalLink className="h-3 w-3" />
        </a>
        {' '}· preview, H2H and form on Sofascore
      </p>
    </div>
  )
}
