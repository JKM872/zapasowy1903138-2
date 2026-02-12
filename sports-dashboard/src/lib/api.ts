// ============================================================================
// SPORTS DASHBOARD - API Client
// ============================================================================
import { API_BASE_URL } from './constants'
import type { Match, StatsData, ApiResponse, LiveScore } from './types'

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    throw new Error(`API Error ${res.status}: ${res.statusText}`)
  }
  return res.json()
}

// ---------------------------------------------------------------------------
// Matches
// ---------------------------------------------------------------------------
export async function getMatches(params: {
  date?: string
  sport?: string
  search?: string
  page?: number
  per_page?: number
}): Promise<ApiResponse<Match[]>> {
  const searchParams = new URLSearchParams()
  if (params.date) searchParams.set('date', params.date)
  if (params.sport && params.sport !== 'all') searchParams.set('sport', params.sport)
  if (params.search) searchParams.set('search', params.search)
  if (params.page) searchParams.set('page', String(params.page))
  if (params.per_page) searchParams.set('per_page', String(params.per_page))

  const qs = searchParams.toString()
  return fetchApi<ApiResponse<Match[]>>(`/api/matches${qs ? '?' + qs : ''}`)
}

export async function getMatch(id: string): Promise<Match> {
  return fetchApi<Match>(`/api/matches/${id}`)
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------
export async function getStats(days?: number): Promise<StatsData> {
  const qs = days ? `?days=${days}` : ''
  return fetchApi<StatsData>(`/api/stats${qs}`)
}

// ---------------------------------------------------------------------------
// Sports & Dates
// ---------------------------------------------------------------------------
export async function getAvailableSports(): Promise<string[]> {
  const res = await fetchApi<{ sports: string[] }>('/api/sports')
  return res.sports
}

export async function getAvailableDates(): Promise<string[]> {
  const res = await fetchApi<{ dates: string[] }>('/api/dates')
  return res.dates
}

// ---------------------------------------------------------------------------
// Live Scores
// ---------------------------------------------------------------------------
export async function getLiveScores(sport: string = 'football'): Promise<LiveScore[]> {
  try {
    const res = await fetchApi<{ scores: LiveScore[] }>(`/api/live-scores?sport=${sport}`)
    return res.scores ?? []
  } catch {
    return []
  }
}
