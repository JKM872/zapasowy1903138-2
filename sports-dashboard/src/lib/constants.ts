// ============================================================================
// Constants – sport registry, market labels, filter presets
// ============================================================================
import type { Sport } from './types'

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || ''

// ---------------------------------------------------------------------------
// Sport registry
// ---------------------------------------------------------------------------

export interface SportConfig {
  id: Sport | string
  /** Polish label shown in the sidebar and filters. */
  name: string
  /** Material Symbols Rounded glyph name, rendered by <SportIcon>. */
  glyph: string
  /** Accent used for the icon in the sport tree. */
  color: string
  /** Whether the sport has a draw, i.e. a three-way 1-X-2 market. */
  hasDraw: boolean
  /** Sidebar ordering; lower comes first. */
  order: number
}

/** Glyph used for any sport the registry does not recognise. */
const UNKNOWN_SPORT_GLYPH = 'sports'

/**
 * Material Symbols has no dedicated table tennis glyph, so it borrows the
 * tennis racket. Everything else maps one to one.
 */
export const SPORTS: SportConfig[] = [
  { id: 'football',     name: 'Piłka nożna',    glyph: 'sports_soccer',     color: 'text-emerald-400', hasDraw: true,  order: 1 },
  { id: 'tennis',       name: 'Tenis',          glyph: 'sports_tennis',     color: 'text-violet-400',  hasDraw: false, order: 2 },
  { id: 'basketball',   name: 'Koszykówka',     glyph: 'sports_basketball', color: 'text-amber-400',   hasDraw: false, order: 3 },
  { id: 'handball',     name: 'Piłka ręczna',   glyph: 'sports_handball',   color: 'text-teal-400',    hasDraw: true,  order: 4 },
  { id: 'hockey',       name: 'Hokej',          glyph: 'sports_hockey',     color: 'text-sky-400',     hasDraw: true,  order: 5 },
  { id: 'volleyball',   name: 'Siatkówka',      glyph: 'sports_volleyball', color: 'text-pink-400',    hasDraw: false, order: 6 },
  { id: 'baseball',     name: 'Baseball',       glyph: 'sports_baseball',   color: 'text-orange-400',  hasDraw: false, order: 7 },
  { id: 'table_tennis', name: 'Tenis stołowy',  glyph: 'sports_tennis',     color: 'text-lime-400',    hasDraw: false, order: 8 },
]

const SPORT_BY_ID = new Map(SPORTS.map(s => [s.id, s]))

/**
 * Google Fonts URL for exactly the glyphs the registry uses.
 *
 * Derived from SPORTS rather than hardcoded, so adding a sport cannot leave its
 * icon rendering as the literal glyph name. `display=block` hides the text until
 * the font is ready instead of flashing "sports_soccer" on screen.
 */
export const MATERIAL_SYMBOLS_HREF = (() => {
  const glyphs = Array.from(
    new Set([...SPORTS.map(s => s.glyph), UNKNOWN_SPORT_GLYPH]),
  ).sort()
  const axes = 'opsz,wght,FILL,GRAD@24,400,1,0'
  return (
    'https://fonts.googleapis.com/css2' +
    `?family=Material+Symbols+Rounded:${axes}` +
    `&icon_names=${glyphs.join(',')}` +
    '&display=block'
  )
})()

/** Shown for any sport key the registry does not recognise. */
export const UNKNOWN_SPORT: SportConfig = {
  id: 'unknown',
  name: 'Inne',
  glyph: UNKNOWN_SPORT_GLYPH,
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
  { label: 'Z głosami kibiców', action: { hasSofascore: true }                      },
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
