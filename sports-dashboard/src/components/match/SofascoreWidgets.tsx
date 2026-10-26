// ============================================================================
// SofascoreWidgets – official SofaScore embeds (widgets.sofascore.com)
// Source: https://corporate.sofascore.com/widgets (free, copy-paste iframe embeds)
// ============================================================================
'use client'

import { ExternalLink, Radio } from 'lucide-react'
import type { Sport } from '@/lib/types'

const WIDGET_HOST = 'https://widgets.sofascore.com/embed'

/** Widgets SofaScore offers per event, by sport. Football has the richest set. */
const WIDGETS: Record<string, { key: string; label: string; height: number }[]> = {
  football: [
    { key: 'attackMomentum', label: 'Attack momentum', height: 286 },
    { key: 'lineups', label: 'Lineups', height: 786 },
  ],
}

interface Props {
  eventId?: number | null
  sport: Sport | string
  homeTeam: string
  awayTeam: string
}

export function SofascoreWidgets({ eventId, sport, homeTeam, awayTeam }: Props) {
  if (!eventId) {
    return (
      <p className="text-sm text-muted-foreground text-center py-8">
        Live widgets appear once this match is matched on Sofascore.
      </p>
    )
  }

  const sportSlug = String(sport || 'football')
  const matchUrl = `https://www.sofascore.com/${sportSlug}/match/${eventId}`
  const widgets = WIDGETS[sportSlug] ?? []

  return (
    <div className="space-y-4">
      {widgets.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-6">
          Embedded widgets are not available for this sport yet.
        </p>
      )}
      {widgets.map((w) => (
        <section key={w.key} className="rounded-xl border bg-[#1b1d22] p-2 space-y-2" aria-label={w.label}>
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
      ))}
      <p className="text-xs text-muted-foreground text-center">
        Live data by{' '}
        <a
          href={matchUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-0.5 underline underline-offset-2 hover:text-foreground"
        >
          Sofascore <ExternalLink className="h-3 w-3" />
        </a>
      </p>
    </div>
  )
}
