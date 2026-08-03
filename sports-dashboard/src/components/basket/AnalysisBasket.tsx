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
        <h2 className="text-sm font-semibold">Koszyk analityczny</h2>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          Kliknij kurs przy zdarzeniu, aby dodać je do koszyka. Policzymy łączny
          kurs, łączne prawdopodobieństwo według modelu i wartość oczekiwaną.
        </p>
        <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground/80">
          Koszyk służy wyłącznie do analizy. Nie przyjmujemy zakładów.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <h2 className="text-sm font-semibold">Koszyk analityczny</h2>
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
          Wyczyść
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
                <SportIcon sport={item.sport} colored className="mt-0.5 text-[14px]" />
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
                  aria-label={`Usuń ${item.label}`}
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
                      {implied != null && ` · rynek ${formatFractionPct(implied)}`}
                    </>
                  ) : (
                    'model: brak danych'
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
                  Wartość oczekiwana: {singleEv > 0 ? '+' : ''}
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
          <span className="text-muted-foreground">Łączny kurs</span>
          <span className="font-mono text-sm font-bold tabular-nums">
            {totalOdds.toFixed(2)}
          </span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Łączne prawdopodobieństwo</span>
          <span className="font-mono tabular-nums">
            {totalProbability != null ? formatFractionPct(totalProbability, 1) : '—'}
          </span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Wartość oczekiwana</span>
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
              ? 'Model nie ma prawdopodobieństwa dla żadnego z wybranych zdarzeń, więc nie da się policzyć wartości oczekiwanej.'
              : `Brak prawdopodobieństwa modelu dla ${items.length - known.length} z ${items.length} zdarzeń — łączny wynik byłby zaniżony, dlatego go nie pokazujemy.`}
          </p>
        )}

        {items.length > 1 && (
          <p className="flex gap-1.5 pt-1 text-[10px] leading-relaxed text-muted-foreground">
            <TriangleAlert className="mt-px h-3 w-3 shrink-0" />
            Prawdopodobieństwa mnożymy, zakładając niezależność zdarzeń. Przy
            meczach z tej samej ligi lub rozgrywanych w tym samym czasie wynik
            może być zawyżony.
          </p>
        )}

        <p className="pt-1 text-[10px] leading-relaxed text-muted-foreground/80">
          Wyłącznie analiza. Nie przyjmujemy zakładów i nie wypłacamy wygranych.
        </p>
      </div>
    </div>
  )
}
