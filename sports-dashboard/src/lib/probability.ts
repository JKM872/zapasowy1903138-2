// ============================================================================
// Probability helpers
// ============================================================================
import type { Match } from './types'

/**
 * The model's probability for one outcome, as a 0-1 fraction, or null when no
 * source covers it.
 *
 * API fields mix scales: `aiPrediction.prob*`, `forebet.*Prob`, `scoring.prob`
 * and `tennis.prob*` all arrive as percentages. Converting in one place keeps
 * the "6900%" class of bug from coming back.
 */
export function outcomeProbability(match: Match, outcome: string): number | null {
  const ai = match.aiPrediction
  if (ai) {
    const v = outcome === '1' ? ai.probHome : outcome === 'X' ? ai.probDraw : ai.probAway
    if (v != null && v > 0) return v / 100
  }

  const fb = match.forebet
  if (fb) {
    const v = outcome === '1' ? fb.homeProb : outcome === 'X' ? fb.drawProb : fb.awayProb
    if (v != null && v > 0) return v / 100
  }

  // Tennis carries its own two-way split.
  if (match.tennis) {
    const v = outcome === '1' ? match.tennis.probA : outcome === '2' ? match.tennis.probB : null
    if (v != null && v > 0) return v / 100
  }

  // The scoring engine reports a probability for its own pick only.
  if (match.scoring?.pick === outcome && match.scoring.prob > 0) {
    return match.scoring.prob / 100
  }

  return null
}

/** Probability implied by decimal odds, ignoring the bookmaker's margin. */
export function impliedProbability(odds: number): number | null {
  if (!Number.isFinite(odds) || odds <= 1) return null
  return 1 / odds
}

/**
 * Expected value per unit staked: `p * odds - 1`. Positive means the model
 * thinks the price is too high, which is the only reason to be interested.
 */
export function expectedValue(probability: number, odds: number): number {
  return probability * odds - 1
}
