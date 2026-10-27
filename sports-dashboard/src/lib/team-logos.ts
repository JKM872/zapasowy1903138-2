// ============================================================================
// Team avatar helpers – initials and a stable colour for the fallback circle.
// Logos and photos come from the backend only (homeMedia/awayMedia, filled from
// outputs/media_cache.json); the browser never calls TheSportsDB.
// ============================================================================

/**
 * Generate initials from team name for fallback avatar
 * "Manchester United" → "MU", "FC Barcelona" → "FB"
 */
export function getTeamInitials(name: string): string {
  if (!name) return '??'
  const words = name.replace(/^(FC|AC|AS|US|SS|SC|SK|FK|NK|GNK|TSG|VfB|VfL|RB)\s+/i, '$1 ')
    .split(/\s+/)
    .filter(Boolean)
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}

/**
 * Generate a consistent color from team name for fallback avatar
 */
export function getTeamColor(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  const hue = Math.abs(hash) % 360
  return `hsl(${hue}, 55%, 45%)`
}
