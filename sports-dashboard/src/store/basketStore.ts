// ============================================================================
// Basket store – selected outcomes for combined analysis
// ============================================================================
import { create } from 'zustand'
import type { Match } from '@/lib/types'
import { outcomeProbability } from '@/lib/probability'

export interface BasketItem {
  matchId: string
  label: string
  league: string | null
  sport: string
  time: string
  outcome: string
  odds: number
  /** Model probability as a 0-1 fraction, or null when no source covers it. */
  probability: number | null
}

interface BasketState {
  items: BasketItem[]
  /**
   * Add an outcome, or replace it when the same event is already in the basket.
   * Two outcomes of one event are mutually exclusive, so combining them would
   * produce a figure that cannot happen.
   */
  toggle: (match: Match, outcome: string, odds: number) => void
  remove: (matchId: string) => void
  clear: () => void
  /** Outcomes selected for one event, so rows can show the active button. */
  outcomesFor: (matchId: string) => string[]
}

export const useBasketStore = create<BasketState>((set, get) => ({
  items: [],

  toggle: (match, outcome, odds) => set(state => {
    const id = String(match.id)
    const existing = state.items.find(i => i.matchId === id)

    // Clicking the same outcome again removes it.
    if (existing?.outcome === outcome) {
      return { items: state.items.filter(i => i.matchId !== id) }
    }

    const item: BasketItem = {
      matchId: id,
      label: `${match.homeTeam} - ${match.awayTeam}`,
      league: match.league,
      sport: match.sport,
      time: match.time,
      outcome,
      odds,
      probability: outcomeProbability(match, outcome),
    }

    return {
      items: existing
        ? state.items.map(i => (i.matchId === id ? item : i))
        : [...state.items, item],
    }
  }),

  remove: matchId => set(state => ({
    items: state.items.filter(i => i.matchId !== matchId),
  })),

  clear: () => set({ items: [] }),

  outcomesFor: matchId => get().items.filter(i => i.matchId === matchId).map(i => i.outcome),
}))
