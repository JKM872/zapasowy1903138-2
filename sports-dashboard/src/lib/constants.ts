// ============================================================================
// SPORTS DASHBOARD - Constants
// ============================================================================
import {
  Trophy, Dribbble, CircleDot, Snowflake, Circle, HandMetal,
} from 'lucide-react'
import type { Sport } from './types'

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || ''

// ---------------------------------------------------------------------------
// Sport configuration
// ---------------------------------------------------------------------------
export const SPORTS: { id: Sport; name: string; icon: typeof Trophy; color: string; bgColor: string }[] = [
  { id: 'football',   name: 'Football',   icon: Trophy,     color: 'text-emerald-600', bgColor: 'bg-emerald-100 dark:bg-emerald-950' },
  { id: 'basketball', name: 'Basketball', icon: Dribbble,   color: 'text-amber-600',   bgColor: 'bg-amber-100 dark:bg-amber-950'     },
  { id: 'tennis',     name: 'Tennis',     icon: CircleDot,  color: 'text-violet-600',  bgColor: 'bg-violet-100 dark:bg-violet-950'   },
  { id: 'hockey',     name: 'Hockey',     icon: Snowflake,  color: 'text-blue-600',    bgColor: 'bg-blue-100 dark:bg-blue-950'       },
  { id: 'volleyball', name: 'Volleyball', icon: Circle,     color: 'text-pink-600',    bgColor: 'bg-pink-100 dark:bg-pink-950'       },
  { id: 'handball',   name: 'Handball',   icon: HandMetal,  color: 'text-teal-600',    bgColor: 'bg-teal-100 dark:bg-teal-950'       },
]

export const SPORT_MAP = Object.fromEntries(SPORTS.map(s => [s.id, s])) as Record<Sport, typeof SPORTS[number]>

// ---------------------------------------------------------------------------
// Prediction helpers
// ---------------------------------------------------------------------------
export const PREDICTION_LABELS: Record<string, string> = {
  '1':  'Home',
  'X':  'Draw',
  '2':  'Away',
  '1X': 'Home/Draw',
  'X2': 'Draw/Away',
  '12': 'Home/Away',
}

export const PREDICTION_COLORS: Record<string, string> = {
  '1':  'bg-emerald-500 text-white',
  'X':  'bg-amber-500 text-white',
  '2':  'bg-rose-500 text-white',
  '1X': 'bg-emerald-400 text-white',
  'X2': 'bg-amber-400 text-white',
  '12': 'bg-violet-500 text-white',
}

// ---------------------------------------------------------------------------
// Confidence tiers
// ---------------------------------------------------------------------------
export function getConfidenceTier(confidence: number) {
  if (confidence >= 85) return { label: 'Very High', color: 'text-emerald-600', bg: 'bg-emerald-500' }
  if (confidence >= 70) return { label: 'High',      color: 'text-blue-600',    bg: 'bg-blue-500'    }
  if (confidence >= 55) return { label: 'Medium',    color: 'text-amber-600',   bg: 'bg-amber-500'   }
  return { label: 'Low', color: 'text-zinc-500', bg: 'bg-zinc-400' }
}

// ---------------------------------------------------------------------------
// Quick filter presets
// ---------------------------------------------------------------------------
export const QUICK_FILTERS = [
  { label: '🔥 AI Top Picks',   action: { geminiRecommendation: 'HIGH', hasPredictions: true } },
  { label: 'High Confidence',  action: { minConfidence: 85, hasPredictions: true } },
  { label: 'Value Bets',       action: { hasOdds: true, hasPredictions: true }     },
  { label: 'With SofaScore',   action: { hasSofascore: true }                       },
  { label: 'Today',            action: { date: 'today' as const }                   },
  { label: 'Tomorrow',         action: { date: 'tomorrow' as const }                },
]

// ---------------------------------------------------------------------------
// Default filter state
// ---------------------------------------------------------------------------
export const DEFAULT_FILTERS = {
  sport: 'all' as const,
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
