// ============================================================================
// SPORTS DASHBOARD - API Client
// ============================================================================
import { API_BASE_URL } from './constants'
import type { Match, StatsData, ApiResponse, LiveScore, WeatherData } from './types'

/** Get auth token from zustand store (lazy import to avoid circular deps) */
function getAuthToken(): string {
  try {
    // Access zustand store outside React
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { useAuthStore } = require('@/store/authStore')
    return useAuthStore.getState().getToken()
  } catch {
    return ''
  }
}

async function fetchApi<T>(endpoint: string, options?: RequestInit & { auth?: boolean }): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options?.headers as Record<string, string> ?? {}),
  }

  // Attach auth token when available (unless explicitly disabled).
  // Needed on GET /api/matches too, so the server can unlock Grade A for
  // active subscribers via the paywall.
  if (options?.auth !== false && !headers['Authorization']) {
    const token = getAuthToken()
    if (token) headers['Authorization'] = token
  }

  const res = await fetch(url, { ...options, headers })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`API Error ${res.status}: ${res.statusText}${body ? ` — ${body}` : ''}`)
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
  } catch (err) {
    console.warn('[LiveScores] Fetch failed:', err instanceof Error ? err.message : err)
    return []
  }
}

// ---------------------------------------------------------------------------
// User Bets (backed by Heroku API → Supabase)
// ---------------------------------------------------------------------------

export interface ApiBet {
  id: number
  home_team: string
  away_team: string
  match_date: string
  match_time?: string
  sport: string
  league?: string
  bet_selection: string
  odds_at_bet: number
  stake: number
  status: string          // pending | won | lost | void
  actual_result?: string
  home_score?: number
  away_score?: number
  notes?: string
  created_at: string
}

export interface ApiBetStats {
  total_bets: number
  won: number
  lost: number
  pending: number
  void_count: number
  win_rate: number | null
  total_staked: number
  total_profit: number
  roi: number | null
}

export async function getBets(params?: {
  status?: string
  days?: number
  limit?: number
}): Promise<{ bets: ApiBet[]; count: number }> {
  const sp = new URLSearchParams()
  if (params?.status) sp.set('status', params.status)
  if (params?.days) sp.set('days', String(params.days))
  if (params?.limit) sp.set('limit', String(params.limit))
  const qs = sp.toString()
  return fetchApi(`/api/bets${qs ? '?' + qs : ''}`)
}

export async function createBet(data: {
  home_team: string
  away_team: string
  match_date: string
  match_time?: string
  bet_selection: '1' | 'X' | '2'
  odds_at_bet: number
  stake?: number
  sport?: string
  league?: string
  notes?: string
}): Promise<{ success: boolean; bet_id: number; message: string }> {
  return fetchApi('/api/bets', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function settleBet(betId: number, data: {
  actual_result: string
  home_score: number
  away_score: number
}): Promise<{ success: boolean }> {
  return fetchApi(`/api/bets/${betId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deleteBet(betId: number): Promise<{ success: boolean }> {
  return fetchApi(`/api/bets/${betId}`, { method: 'DELETE' })
}

export async function getBetStats(): Promise<ApiBetStats> {
  return fetchApi('/api/bets/stats')
}

// ---------------------------------------------------------------------------
// Weather (Open-Meteo via backend proxy with cache)
// ---------------------------------------------------------------------------
export async function getWeather(city: string, date?: string): Promise<WeatherData> {
  const sp = new URLSearchParams()
  sp.set('city', city)
  if (date) sp.set('date', date)
  return fetchApi(`/api/weather?${sp.toString()}`)
}

// ---------------------------------------------------------------------------
// League Standings (Football-Data.org via backend proxy)
// ---------------------------------------------------------------------------

export interface StandingRow {
  position: number
  team: string
  teamCrest: string
  played: number
  won: number
  draw: number
  lost: number
  goalsFor: number
  goalsAgainst: number
  goalDifference: number
  points: number
  form: string
}

export interface StandingsData {
  league: string
  leagueCode: string
  season: string
  standings: StandingRow[]
}

export async function getStandings(league: string = 'PL'): Promise<StandingsData> {
  return fetchApi(`/api/standings?league=${league}`)
}

export async function getAvailableLeagues(): Promise<{ leagues: { code: string; name: string }[] }> {
  return fetchApi('/api/standings/leagues')
}

// ---------------------------------------------------------------------------
// Team / League metadata (TheSportsDB via backend proxy)
// ---------------------------------------------------------------------------

export interface TeamInfo {
  name: string
  nameShort: string
  badge: string
  logo: string
  jersey: string
  stadium: string
  stadiumCapacity: string
  stadiumThumb: string
  country: string
  league: string
  description: string
  formedYear: string
  website: string
}

export async function getTeamInfo(team: string): Promise<TeamInfo> {
  return fetchApi(`/api/team-info?team=${encodeURIComponent(team)}`)
}

// ---------------------------------------------------------------------------
// Subscription / Stripe checkout (weekly $5 → Grade A access)
// ---------------------------------------------------------------------------

export interface SubscriptionStatus {
  active: boolean
  status: string
  current_period_end: string | null
}

/** Fetch the current user's subscription status (requires auth). */
export async function getSubscriptionStatus(): Promise<SubscriptionStatus> {
  const token = getAuthToken()
  return fetchApi<SubscriptionStatus>('/api/subscription/status', {
    headers: token ? { Authorization: token } : {},
  })
}

/** Create a Stripe Checkout session and return the redirect URL. */
export async function createCheckoutSession(email?: string): Promise<{ url: string; id: string }> {
  return fetchApi('/api/checkout', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

// ---------------------------------------------------------------------------
// Match comments
// ---------------------------------------------------------------------------

export interface MatchComment {
  id: number
  body: string
  author: string
  createdAt: string
  /** Whether the signed-in reader wrote it, so deletion can be offered. */
  isMine: boolean
}

export interface CommentsResponse {
  comments: MatchComment[]
  /** False when the server has no database configured. */
  available: boolean
}

export async function getComments(matchId: string | number): Promise<CommentsResponse> {
  return fetchApi<CommentsResponse>(`/api/matches/${encodeURIComponent(String(matchId))}/comments`)
}

export async function addComment(
  matchId: string | number,
  body: string,
  author?: string,
): Promise<MatchComment> {
  return fetchApi<MatchComment>(
    `/api/matches/${encodeURIComponent(String(matchId))}/comments`,
    { method: 'POST', body: JSON.stringify({ body, author }) },
  )
}

export async function deleteComment(commentId: number): Promise<{ deleted: number }> {
  return fetchApi<{ deleted: number }>(`/api/comments/${commentId}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------------------
// Reader preferences
// ---------------------------------------------------------------------------

export interface Preferences {
  sports: string[]
  leagues: string[]
  /** False until the questionnaire has been answered, even with empty answers. */
  onboarded: boolean
  available: boolean
}

export async function getPreferences(): Promise<Preferences> {
  return fetchApi<Preferences>('/api/preferences')
}

export async function savePreferences(
  sports: string[],
  leagues: string[],
): Promise<{ saved: boolean }> {
  return fetchApi<{ saved: boolean }>('/api/preferences', {
    method: 'PUT',
    body: JSON.stringify({ sports, leagues, onboarded: true }),
  })
}
