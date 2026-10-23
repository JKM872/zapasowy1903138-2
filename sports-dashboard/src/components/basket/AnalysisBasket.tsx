// ============================================================================
// AnalysisBasket – combined analysis of the selected outcomes
// ============================================================================
'use client'

import { Trash2, X, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { PREDICTION_LABELS } from '@/lib/constants'
import { formatOdds, formatFractionPct } from '@/lib/format'
import { expectedValue, impliedProbability } from '@/lib/probability'
import { SportIcon } from '@/components/shared/SportIcon'
import { useBasketStore } from '@/store/basketStore'

/**
 * The bookmaker equivalent of a bet slip, except nothing is staked here: it adds
 * up the model's view of the selected outcomes so the combined price can be
 * compared against the combined probability.
 */
export function AnalysisBasket() {
  const { items, remove, clear } = useBasketStore()

  const totalOdds = items.reduce((acc, i) => acc * i.odds, 1)
  const known = items.filter(i => i.probability != null)
  const allKnown = items.length > 0 && known.length === items.length
  const totalProbability = allKnown
    ? items.reduce((acc, i) => acc * (i.probability as number), 1)
    : null
  const ev = totalProbability != null ? expectedValue(totalProbability, totalOdds) : null

  if (items.length === 0) {
    return (
      <div className="p-4">
        <h2 className="text-sm font-semibold">Analysis slip</h2>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          Click the odds on an event to add it to the slip. We’ll calculate the
          combined odds, the model’s combined probability and the expected value.
        </p>
        <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground/80">
          The slip is for analysis only. We do not accept bets.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <h2 className="text-sm font-semibold">Analysis slip</h2>
        <span className="rounded-full bg-primary px-1.5 text-[10px] font-bold text-primary-foreground tabular-nums">
          {items.length}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={clear}
          className="ml-auto h-7 gap-1 px-2 text-xs text-muted-foreground"
        >
          <Trash2 className="h-3 w-3" />
          Clear
        </Button>
      </div>

      {/* Selections */}
      <ul className="divide-y divide-border/60">
        {items.map(item => {
          const implied = impliedProbability(item.odds)
          const singleEv =
            item.probability != null ? expectedValue(item.probability, item.odds) : null
          return (
            <li key={item.matchId} className="px-3 py-2">
              <div className="flex items-start gap-2">
                <SportIcon sport={item.sport} colored className="mt-0.5 h-3.5 w-3.5" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium" title={item.label}>
                    {item.label}
                  </p>
                  <p className="truncate text-[10px] text-muted-foreground">
                    {item.time}
                    {item.league ? ` · ${item.league}` : ''}
                  </p>
                </div>
                <button
                  onClick={() => remove(item.matchId)}
                  aria-label={`Remove ${item.label}`}
                  className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>

              <div className="mt-1.5 flex items-center gap-2 text-[11px]">
                <span className="rounded border border-primary/50 px-1.5 py-0.5 font-semibold text-primary">
                  {PREDICTION_LABELS[item.outcome] ?? item.outcome}
                </span>
                <span className="font-mono font-semibold tabular-nums">
                  {formatOdds(item.odds)}
                </span>
                <span className="ml-auto text-muted-foreground tabular-nums">
                  {item.probability != null ? (
                    <>
                      model {formatFractionPct(item.probability)}
                      {implied != null && ` · market ${formatFractionPct(implied)}`}
                    </>
                  ) : (
                    'model: no data'
                  )}
                </span>
              </div>

              {singleEv != null && (
                <p
                  className={cn(
                    'mt-0.5 text-[10px] tabular-nums',
                    singleEv > 0 ? 'text-primary' : 'text-muted-foreground',
                  )}
                >
                  Expected value: {singleEv > 0 ? '+' : ''}
                  {(singleEv * 100).toFixed(1)}%
                </p>
              )}
            </li>
          )
        })}
      </ul>

      {/* Totals */}
      <div className="space-y-1.5 border-t border-border px-3 py-3 text-xs">
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Combined odds</span>
          <span className="font-mono text-sm font-bold tabular-nums">
            {totalOdds.toFixed(2)}
          </span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Combined probability</span>
          <span className="font-mono tabular-nums">
            {totalProbability != null ? formatFractionPct(totalProbability, 1) : '—'}
          </span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Expected value</span>
          <span
            className={cn(
              'font-mono font-bold tabular-nums',
              ev == null ? '' : ev > 0 ? 'text-primary' : 'text-destructive',
            )}
          >
            {ev == null ? '—' : `${ev > 0 ? '+' : ''}${(ev * 100).toFixed(1)}%`}
          </span>
        </div>

        {/* Being explicit beats a number that looks more certain than it is. */}
        {!allKnown && (
          <p className="flex gap-1.5 pt-1 text-[10px] leading-relaxed text-amber-400">
            <TriangleAlert className="mt-px h-3 w-3 shrink-0" />
            {known.length === 0
              ? 'The model has no probability for any of the selected events, so expected value cannot be calculated.'
              : `No model probability for ${items.length - known.length} of ${items.length} events. The combined figure would be understated, so we don’t show it.`}
          </p>
        )}

        {items.length > 1 && (
          <p className="flex gap-1.5 pt-1 text-[10px] leading-relaxed text-muted-foreground">
            <TriangleAlert className="mt-px h-3 w-3 shrink-0" />
            Probabilities are multiplied, assuming the events are independent. For
            matches from the same league or played at the same time, the result
            may be overstated.
          </p>
        )}

        <p className="pt-1 text-[10px] leading-relaxed text-muted-foreground/80">
          Analysis only. We do not accept bets or pay out winnings.
        </p>
      </div>
    </div>
  )
}
