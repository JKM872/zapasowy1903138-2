// ============================================================================
// SPORTS DASHBOARD - TypeScript Types
// ============================================================================

export type Sport = 'football' | 'basketball' | 'tennis' | 'hockey' | 'volleyball' | 'handball'

export type Prediction = '1' | 'X' | '2' | '1X' | 'X2' | '12' | null

export interface ForebetData {
  prediction: Prediction
  probability: number | null
  exactScore: string | null
  overUnder: string | null
  btts: string | null
}

export interface SofascoreData {
  home: number | null
  draw: number | null
  away: number | null
  votes: number
}

export interface OddsData {
  home: number | null
  draw: number | null
  away: number | null
  bookmaker: string | null
}

export interface H2HData {
  home: number
  draw: number
  away: number
  total: number
  winRate: number
}

export type GeminiRecommendation = 'HIGH' | 'MEDIUM' | 'LOW' | 'SKIP'

export interface GeminiAnalysis {
  prediction: string | null
  confidence: number | null
  reasoning: string | null
  recommendation?: GeminiRecommendation | null
}

export interface LiveScore {
  id: string
  homeTeam: string
  awayTeam: string
  homeScore: number
  awayScore: number
  status: 'scheduled' | 'live' | 'halftime' | 'finished'
  time: string
  league: string
  sport: string
}

export interface Match {
  id: string | number
  homeTeam: string
  awayTeam: string
  time: string
  date: string
  sport: Sport
  league: string | null
  country: string | null
  matchUrl: string | null
  qualifies: boolean
  forebet: ForebetData | null
  sofascore: SofascoreData | null
  odds: OddsData | null
  h2h: H2HData | null
  homeForm: string[]
  awayForm: string[]
  formAdvantage: boolean
  focusTeam: string
  gemini?: GeminiAnalysis | null
  confidence?: number
  value_bet?: boolean
}

export interface MatchFilters {
  geminiRecommendation?: GeminiRecommendation | 'all'
  sport: Sport | 'all'
  date: Date | null
  minConfidence: number
  hasOdds: boolean
  hasPredictions: boolean
  hasSofascore: boolean
  search: string
  sortBy: 'time' | 'confidence' | 'sport'
  sortOrder: 'asc' | 'desc'
}

export interface StatsData {
  total_matches: number
  matches_with_predictions: number
  matches_with_sofascore: number
  matches_with_odds: number
  accuracy_7d: number | null
  accuracy_30d: number | null
  roi_7d: number | null
  roi_30d: number | null
  sport_breakdown: SportStat[]
}

export interface SportStat {
  sport: Sport
  total: number
  with_predictions: number
  accuracy: number | null
}

export interface UserBet {
  id: string
  matchLabel: string
  match_id?: string
  match?: Match
  pick: string
  prediction?: string
  stake?: number
  odds?: number
  result: 'pending' | 'won' | 'lost' | 'void'
  profit?: number | null
  createdAt: string
  created_at?: string
}

export interface ApiResponse<T> {
  data: T
  date?: string
  source?: string
  meta?: {
    total: number
    page: number
    per_page: number
  }
  stats?: {
    total: number
    qualifying: number
    formAdvantage: number
  }
  error?: string
}
