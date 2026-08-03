// ============================================================================
// SPORTS DASHBOARD - TypeScript Types
// ============================================================================

/**
 * Sports the registry knows how to label and draw.
 *
 * The backend derives `sport` straight from the stored row, so a key that is not
 * listed here can still arrive. Never index the registry directly with a raw
 * value — use `getSportConfig`, which falls back gracefully. Leaving `baseball`
 * out is what made the sport tabs add up to 658 while "all" reported 670.
 */
export type Sport =
  | 'football'
  | 'basketball'
  | 'tennis'
  | 'hockey'
  | 'volleyball'
  | 'handball'
  | 'baseball'
  | 'table_tennis'

export type Prediction = '1' | 'X' | '2' | '1X' | 'X2' | '12' | null

export interface ForebetData {
  prediction: Prediction
  probability: number | null
  exactScore: string | null
  overUnder: string | null
  btts: string | null
  homeProb: number | null
  drawProb: number | null
  awayProb: number | null
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
  keyFactors?: string[]
  riskFactors?: string[]
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

/** Scoring engine output (football + tennis) */
export interface ScoringData {
  pick: string
  prob: number
  ev: number
  edge: number
  kelly: number
  confidence: number
  dataQuality: number
}

/** Tennis-specific metadata */
export interface TennisData {
  surface: string
  rankingA: number | null
  rankingB: number | null
  probA: number
  probB: number
}

/** AI Prediction consensus block */
export interface AIConsensus {
  sources: number
  total: number
  strength: 'STRONG' | 'MODERATE' | 'WEAK' | 'DIVIDED' | 'UNKNOWN'
  predictions: Record<string, string>
}

/** AI Prediction risk block */
export interface AIRisk {
  score: number
  level: 'LOW' | 'MEDIUM' | 'HIGH'
  flags: string[]
}

/** Factor breakdown item */
export interface AIFactor {
  name: string
  value: number
  weight: number
  impact: 'positive' | 'neutral' | 'negative'
  quality: number
  description: string
  details?: Record<string, unknown>
}

/** Ultra PRO AI Prediction — full match analysis */
export interface AIPrediction {
  pick: string
  pickLabel: string
  compositeConfidence: number
  confidenceTier: 'VERY HIGH' | 'HIGH' | 'MEDIUM' | 'LOW' | 'VERY LOW'
  probHome: number
  probDraw: number
  probAway: number
  consensus: AIConsensus
  ev: number
  edge: number
  valueRating: 'EXCELLENT' | 'GOOD' | 'FAIR' | 'NONE'
  risk: AIRisk
  factors: AIFactor[]
  dataQuality: number
  dataQualityLabel: 'EXCELLENT' | 'GOOD' | 'FAIR' | 'POOR'
  availableSources: string[]
  missingSources: string[]
  keyArgumentsFor: string[]
  keyArgumentsAgainst: string[]
  verdict: string
  shortVerdict: string
  doNotBetReasons: string[]
}

export interface Match {
  id: string | number
  homeTeam: string
  awayTeam: string
  homeLogo?: string
  awayLogo?: string
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
  scoring?: ScoringData | null
  tennis?: TennisData | null
  aiPrediction?: AIPrediction | null
  confidence?: number
  value_bet?: boolean
  /** Overall grade A-F. Basis for the Grade A/B freemium paywall. */
  predictionGrade?: string | null
  /** Set by the backend paywall when premium (Grade A) data is masked for non-subscribers. */
  locked?: boolean
}

export interface MatchFilters {
  geminiRecommendation?: GeminiRecommendation | 'all'
  sport: Sport | 'all'
  /** Exact league name, set by the sidebar tree. Null means every league. */
  league: string | null
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
  sportCounts?: Record<string, number>
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

// Weather data from Open-Meteo (via /api/weather)
export interface WeatherData {
  city: string
  date: string
  tempMax: number | null
  tempMin: number | null
  feelsLike: number | null
  precipitation: number | null
  windSpeed: number | null
  weatherCode: number | null
  description: string
  unit: string
}
