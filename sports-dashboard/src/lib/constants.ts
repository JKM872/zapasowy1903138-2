// ============================================================================
// Constants – sport registry, market labels, filter presets
// ============================================================================
import type { IconType } from 'react-icons'
import {
  MdSportsSoccer,
  MdSportsTennis,
  MdSportsBasketball,
  MdSportsHandball,
  MdSportsHockey,
  MdSportsVolleyball,
  MdSportsBaseball,
  MdSportsScore,
} from 'react-icons/md'
import type { Sport } from './types'

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || ''

// ---------------------------------------------------------------------------
// Sport registry
// ---------------------------------------------------------------------------

export interface SportConfig {
  id: Sport | string
  /** Polish label shown in the sidebar and filters. */
  name: string
  /**
   * Google Material Design icon, as an inline SVG component.
   *
   * The first attempt used the Material Symbols icon font from Google Fonts.
   * When the font failed to load, the browser fell back to text and rendered the
   * literal glyph names ("sports_soccer") across the page. Inline SVG cannot
   * degrade that way, needs no request to Google, and keeps the icons available
   * offline.
   */
  icon: IconType
  /** Accent used for the icon in the sport tree. */
  color: string
  /** Whether the sport has a draw, i.e. a three-way 1-X-2 market. */
  hasDraw: boolean
  /** Sidebar ordering; lower comes first. */
  order: number
}

/**
 * Material Design has no dedicated table tennis icon, so it borrows the tennis
 * racket. Everything else maps one to one.
 */
export const SPORTS: SportConfig[] = [
  { id: 'football',     name: 'Piłka nożna',   icon: MdSportsSoccer,     color: 'text-emerald-500', hasDraw: true,  order: 1 },
  { id: 'tennis',       name: 'Tenis',         icon: MdSportsTennis,     color: 'text-violet-500',  hasDraw: false, order: 2 },
  { id: 'basketball',   name: 'Koszykówka',    icon: MdSportsBasketball, color: 'text-amber-500',   hasDraw: false, order: 3 },
  { id: 'handball',     name: 'Piłka ręczna',  icon: MdSportsHandball,   color: 'text-teal-500',    hasDraw: true,  order: 4 },
  { id: 'hockey',       name: 'Hokej',         icon: MdSportsHockey,     color: 'text-sky-500',     hasDraw: true,  order: 5 },
  { id: 'volleyball',   name: 'Siatkówka',     icon: MdSportsVolleyball, color: 'text-pink-500',    hasDraw: false, order: 6 },
  { id: 'baseball',     name: 'Baseball',      icon: MdSportsBaseball,   color: 'text-orange-500',  hasDraw: false, order: 7 },
  { id: 'table_tennis', name: 'Tenis stołowy', icon: MdSportsTennis,     color: 'text-lime-500',    hasDraw: false, order: 8 },
]

const SPORT_BY_ID = new Map(SPORTS.map(s => [s.id, s]))

/** Shown for any sport key the registry does not recognise. */
export const UNKNOWN_SPORT: SportConfig = {
  id: 'unknown',
  name: 'Inne',
  icon: MdSportsScore,
  color: 'text-zinc-400',
  hasDraw: false,
  order: 99,
}

/**
 * Config for a raw sport key. Always returns something, so an unexpected key
 * from the backend shows up as "Inne" instead of vanishing from the counts.
 */
export function getSportConfig(id: string | null | undefined): SportConfig {
  if (!id) return UNKNOWN_SPORT
  return SPORT_BY_ID.get(id) ?? { ...UNKNOWN_SPORT, id, name: humaniseSportKey(id) }
}

/** `table_tennis` → `Table tennis`, used only for keys missing from the registry. */
function humaniseSportKey(id: string): string {
  const spaced = id.replace(/[_-]+/g, ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/**
 * Sports to list in the sidebar, built from the counts the API actually
 * returned. Known sports keep the curated order; anything unrecognised is
 * appended so the per-sport numbers always add up to the total.
 */
export function sportsFromCounts(
  counts: Record<string, number>,
): { config: SportConfig; count: number }[] {
  return Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([id, count]) => ({ config: getSportConfig(id), count }))
    .sort((a, b) => a.config.order - b.config.order || b.count - a.count)
}

// ---------------------------------------------------------------------------
// Market labels
// ---------------------------------------------------------------------------
export const PREDICTION_LABELS: Record<string, string> = {
  '1': 'Gospodarz',
  'X': 'Remis',
  '2': 'Gość',
  '1X': 'Gospodarz lub remis',
  'X2': 'Remis lub gość',
  '12': 'Bez remisu',
}

export const PREDICTION_COLORS: Record<string, string> = {
  '1':  'bg-emerald-500 text-white',
  'X':  'bg-amber-500 text-white',
  '2':  'bg-rose-500 text-white',
  '1X': 'bg-emerald-400 text-white',
  'X2': 'bg-amber-400 text-white',
  '12': 'bg-violet-500 text-white',
}

/**
 * Whether the SofaScore fan vote is shown per match.
 *
 * Hidden on request: the crowd's split is an input to the model, not a verdict
 * for the reader, and showing it next to our own pick invited comparing the two
 * as if they were competing tips. The data still reaches the scoring engine and
 * is still listed on the data-sources page, so nothing is hidden about where the
 * numbers come from — only the per-match widget is gone. Flip to `true` to bring
 * it back.
 */
export const SHOW_FAN_VOTE = false

/** Column headers above the odds buttons. */
export const MARKET_COLUMNS_3WAY = ['1', 'X', '2'] as const
export const MARKET_COLUMNS_2WAY = ['1', '2'] as const

// ---------------------------------------------------------------------------
// Confidence tiers
// ---------------------------------------------------------------------------
export function getConfidenceTier(confidence: number) {
  if (confidence >= 85) return { label: 'Bardzo wysoka', color: 'text-emerald-400', bg: 'bg-emerald-500' }
  if (confidence >= 70) return { label: 'Wysoka',        color: 'text-sky-400',     bg: 'bg-sky-500'     }
  if (confidence >= 55) return { label: 'Średnia',       color: 'text-amber-400',   bg: 'bg-amber-500'   }
  return { label: 'Niska', color: 'text-zinc-400', bg: 'bg-zinc-500' }
}

// ---------------------------------------------------------------------------
// Quick filter presets
// ---------------------------------------------------------------------------
export const QUICK_FILTERS = [
  { label: 'Najwyższa pewność', action: { minConfidence: 85, hasPredictions: true } },
  { label: 'Z kursami',         action: { hasOdds: true, hasPredictions: true }     },
  { label: 'Dziś',              action: { date: 'today' as const }                  },
  { label: 'Jutro',             action: { date: 'tomorrow' as const }               },
]

// ---------------------------------------------------------------------------
// Default filter state
// ---------------------------------------------------------------------------
export const DEFAULT_FILTERS = {
  sport: 'all' as const,
  league: null,
  date: null,
  minConfidence: 0,
  hasOdds: false,
  hasPredictions: false,
  hasSofascore: false,
  search: '',
  sortBy: 'time' as const,
  sortOrder: 'asc' as const,
  geminiRecommendation: 'all' as const,
}
