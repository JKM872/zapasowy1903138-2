// ============================================================================
// Team Logo Service – TheSportsDB free API with localStorage cache
// ============================================================================

const SPORTSDB_BASE = 'https://www.thesportsdb.com/api/v1/json/3'
const CACHE_KEY = 'pickly_team_logos'
const CACHE_TTL = 7 * 24 * 60 * 60 * 1000 // 7 days

interface LogoCache {
  [teamName: string]: { url: string | null; ts: number }
}

function getCache(): LogoCache {
  if (typeof window === 'undefined') return {}
  try {
    return JSON.parse(localStorage.getItem(CACHE_KEY) || '{}')
  } catch {
    return {}
  }
}

function setCache(cache: LogoCache) {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(cache))
  } catch {
    // storage full – evict oldest entries
    const entries = Object.entries(cache).sort((a, b) => a[1].ts - b[1].ts)
    const trimmed = Object.fromEntries(entries.slice(Math.floor(entries.length / 2)))
    localStorage.setItem(CACHE_KEY, JSON.stringify(trimmed))
  }
}

/**
 * Fetch team badge URL from TheSportsDB. Returns null if not found.
 * Results are cached in localStorage for 7 days.
 */
export async function getTeamLogoUrl(teamName: string): Promise<string | null> {
  if (!teamName) return null

  const normalized = teamName.trim().toLowerCase()
  const cache = getCache()
  const cached = cache[normalized]

  if (cached && Date.now() - cached.ts < CACHE_TTL) {
    return cached.url
  }

  try {
    const res = await fetch(
      `${SPORTSDB_BASE}/searchteams.php?t=${encodeURIComponent(teamName)}`,
      { signal: AbortSignal.timeout(4000) }
    )
    if (!res.ok) throw new Error('Network error')

    const data = await res.json()
    const team = data?.teams?.[0]
    const url: string | null = team?.strBadge || team?.strLogo || null

    // Cache result (even null to avoid re-fetching)
    cache[normalized] = { url, ts: Date.now() }
    setCache(cache)

    return url
  } catch {
    // On error, cache null for a short period (1 hour)
    cache[normalized] = { url: null, ts: Date.now() - CACHE_TTL + 3600_000 }
    setCache(cache)
    return null
  }
}

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
