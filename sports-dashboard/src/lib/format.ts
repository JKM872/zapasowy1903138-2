// ============================================================================
// SPORTS DASHBOARD - Format Helpers
// ============================================================================
import { format, isToday, isTomorrow, parseISO } from 'date-fns'

/**
 * Friendly date string: "Today", "Tomorrow", or "Mon, 12 Feb 2026"
 */
export function formatMatchDate(dateStr: string): string {
  try {
    const d = parseISO(dateStr)
    if (isToday(d)) return 'Today'
    if (isTomorrow(d)) return 'Tomorrow'
    return format(d, 'EEE, d MMM yyyy')
  } catch {
    return dateStr
  }
}

/**
 * Extract readable hour from various formats. Returns "HH:mm"
 */
export function formatMatchTime(timeStr: string): string {
  if (!timeStr) return '--:--'
  // Already HH:mm
  const hhmm = timeStr.match(/(\d{1,2}:\d{2})/)
  if (hhmm) return hhmm[1]
  // ISO timestamp
  try {
    return format(parseISO(timeStr), 'HH:mm')
  } catch {
    return timeStr.slice(0, 5)
  }
}

/**
 * Format large vote counts: 1234567 → "1.2M", 12345 → "12.3k"
 */
export function formatVotes(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

/**
 * Format odds value: 1.5 → "1.50"
 */
export function formatOdds(v: number | null | undefined): string {
  if (v == null) return '-'
  return v.toFixed(2)
}

/**
 * Derive a single "best prediction" label from available sources
 */
export function derivePrediction(
  forebet: { prediction: string | null; probability: number | null } | null,
  sofascore: { home: number | null; draw: number | null; away: number | null } | null,
): { label: string; source: string; confidence: number } | null {
  if (forebet?.prediction && forebet.probability) {
    return { label: forebet.prediction, source: 'Forebet', confidence: forebet.probability }
  }
  if (sofascore?.home != null) {
    const h = sofascore.home ?? 0
    const d = sofascore.draw ?? 0
    const a = sofascore.away ?? 0
    const max = Math.max(h, d, a)
    const label = max === h ? '1' : max === d ? 'X' : '2'
    return { label, source: 'SofaScore', confidence: max }
  }
  return null
}
