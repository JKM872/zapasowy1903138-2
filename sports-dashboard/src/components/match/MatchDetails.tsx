// ============================================================================
// MatchDetails – Premium SofaScore-style match detail dialog
// ============================================================================
'use client'

import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Separator } from '@/components/ui/separator'
import Link from 'next/link'
import {
  Target, BarChart3, TrendingUp, History, Brain, Clock, Zap, CloudSun,
  Thermometer, Wind, Droplets, Lock, Crown,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { PREDICTION_COLORS } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { formatFractionPct, formatMatchTime, formatOdds, formatPct, formatVotes } from '@/lib/format'
import { RecommendationBadge } from './RecommendationBadge'
import { TeamLogo } from './TeamLogo'
import { GradeBadge } from './GradeBadge'
import { AIPredictionPanel } from './AIPredictionPanel'
import { RadialProgress } from '@/components/charts/RadialProgress'
import { FormTimeline } from '@/components/charts/FormTimeline'
import { H2HBar } from '@/components/charts/H2HBar'
import { useWeather } from '@/hooks/useMatches'
import type { Match } from '@/lib/types'

interface Props {
  match: Match | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function MatchDetails({ match, open, onOpenChange }: Props) {
  // Weather – guess city from home team name (last word)
  // Hooks must be called unconditionally (rules-of-hooks)
  const weatherCity = match?.homeTeam?.split(/\s+/).pop() ?? match?.homeTeam ?? ''
  const { data: weather } = useWeather(weatherCity, match?.date)

  if (!match) return null

  const conf = match.gemini?.confidence ?? match.scoring?.confidence ?? match.confidence ?? match.forebet?.probability ?? 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto p-0">
        {/* ── Match header ── */}
        <div className="p-5 pb-0">
          <DialogHeader>
            <div className="flex items-center gap-2 mb-3">
              <SportIcon sport={match.sport} colored className="h-[18px] w-[18px]" />
              <span className="text-xs text-muted-foreground">{match.league ?? match.sport}</span>
              <GradeBadge grade={match.predictionGrade} className="ml-1" />
              <span className="text-xs text-muted-foreground ml-auto flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {formatMatchTime(match.time)}
              </span>
            </div>

            {/* Teams face-off */}
            <DialogTitle className="sr-only">{match.homeTeam} vs {match.awayTeam}</DialogTitle>
            <div className="flex items-center justify-between py-3">
              {/* Home */}
              <div className="flex flex-col items-center gap-2 flex-1">
                <TeamLogo name={match.homeTeam} size="xl" badgeUrl={match.homeLogo} />
                <span className="font-bold text-sm text-center leading-tight">{match.homeTeam}</span>
                {match.homeForm?.length > 0 && (
                  <FormTimeline form={match.homeForm} teamName={match.homeTeam} maxItems={5} />
                )}
              </div>

              {/* Center: confidence ring */}
              <div className="flex flex-col items-center gap-1 px-4">
                <RadialProgress value={conf} size={64} strokeWidth={4} label="conf" />
                <RecommendationBadge recommendation={match.gemini?.recommendation} size="sm" />
              </div>

              {/* Away */}
              <div className="flex flex-col items-center gap-2 flex-1">
                <TeamLogo name={match.awayTeam} size="xl" badgeUrl={match.awayLogo} />
                <span className="font-bold text-sm text-center leading-tight">{match.awayTeam}</span>
                {match.awayForm?.length > 0 && (
                  <FormTimeline form={match.awayForm} teamName={match.awayTeam} maxItems={5} />
                )}
              </div>
            </div>
          </DialogHeader>
        </div>

        <Separator />

        {/* ── Premium upsell (Grade A locked for non-subscribers) ── */}
        {match.locked && (
          <div className="mx-5 mt-4 rounded-xl border border-amber-500/40 bg-gradient-to-br from-amber-500/10 to-yellow-500/5 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Crown className="h-4 w-4 text-amber-500" />
              Grade A — Premium pick
            </div>
            <p className="mt-1.5 text-xs text-muted-foreground">
              This is one of our highest-conviction selections. Unlock the full AI
              analysis, scoring-engine EV and the exact pick for $5/week.
            </p>
            <Link href="/pricing">
              <button className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-semibold text-black hover:bg-amber-400 transition-colors">
                <Lock className="h-3.5 w-3.5" /> Unlock Grade A
              </button>
            </Link>
          </div>
        )}

        {/* ── Tabs ── */}
        <div className="px-5 pb-5">
          <Tabs defaultValue="predictions" className="mt-3">
            <TabsList className="grid w-full grid-cols-5 h-9">
              <TabsTrigger value="predictions" className="text-xs gap-1"><Target className="h-3 w-3" /> Predict</TabsTrigger>
              <TabsTrigger value="odds" className="text-xs gap-1"><TrendingUp className="h-3 w-3" /> Odds</TabsTrigger>
              <TabsTrigger value="h2h" className="text-xs gap-1"><History className="h-3 w-3" /> H2H</TabsTrigger>
              <TabsTrigger value="ai" className="text-xs gap-1"><Brain className="h-3 w-3" /> AI</TabsTrigger>
              <TabsTrigger value="weather" className="text-xs gap-1"><CloudSun className="h-3 w-3" /> Weather</TabsTrigger>
            </TabsList>

            {/* ── Predictions tab ── */}
            <TabsContent value="predictions" className="space-y-4 mt-4">
              {/* Forebet */}
              {match.forebet && (
                <div className="rounded-xl border bg-card p-4 space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Target className="h-4 w-4 text-blue-500" /> Forebet Prediction
                  </div>

                  {/* Probability bar – all 3 outcomes */}
                  {(match.forebet.homeProb != null || match.forebet.probability != null) && (
                    <div className="space-y-2">
                      {match.forebet.homeProb != null && match.forebet.awayProb != null ? (
                        <>
                          <div className="flex h-5 rounded-full overflow-hidden text-[10px] font-bold text-white">
                            <div className="flex items-center justify-center bg-emerald-500" style={{ width: `${match.forebet.homeProb}%` }}>
                              {match.forebet.homeProb > 10 ? `${match.forebet.homeProb}%` : ''}
                            </div>
                            {match.forebet.drawProb != null && match.forebet.drawProb > 0 && (
                              <div className="flex items-center justify-center bg-amber-500" style={{ width: `${match.forebet.drawProb}%` }}>
                                {match.forebet.drawProb > 10 ? `${match.forebet.drawProb}%` : ''}
                              </div>
                            )}
                            <div className="flex items-center justify-center bg-rose-500" style={{ width: `${match.forebet.awayProb}%` }}>
                              {match.forebet.awayProb > 10 ? `${match.forebet.awayProb}%` : ''}
                            </div>
                          </div>
                          <div className="flex justify-between text-[10px] text-muted-foreground">
                            <span>Home {match.forebet.homeProb}%</span>
                            {match.forebet.drawProb != null && <span>Draw {match.forebet.drawProb}%</span>}
                            <span>Away {match.forebet.awayProb}%</span>
                          </div>
                        </>
                      ) : (
                        <div className="text-center">
                          <span className="font-bold text-lg">{match.forebet.probability ?? '-'}%</span>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <StatBox label="Prediction" value={
                      match.forebet.prediction ? (
                        <Badge className={cn('mt-0.5', PREDICTION_COLORS[match.forebet.prediction] ?? '')}>
                          {match.forebet.prediction}
                        </Badge>
                      ) : '-'
                    } />
                    <StatBox label="Exact Score" value={
                      <span className="font-bold">{match.forebet.exactScore ?? '-'}</span>
                    } />
                    <StatBox label="Over / Under" value={
                      <span className="font-bold">{match.forebet.overUnder ?? '-'}</span>
                    } />
                    <StatBox label="BTTS" value={
                      <span className="font-bold">{match.forebet.btts ?? '-'}</span>
                    } />
                  </div>
                </div>
              )}

              {/* SofaScore */}
              {match.sofascore?.home != null && (
                <div className="rounded-xl border bg-card p-4 space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <BarChart3 className="h-4 w-4 text-orange-500" /> SofaScore Fan Vote
                  </div>
                  <div className="flex items-center justify-around py-2">
                    <RadialProgress value={match.sofascore.home ?? 0} size={56} strokeWidth={4} color="#10b981" label="Home" />
                    {match.sofascore.draw != null && (
                      <RadialProgress value={match.sofascore.draw} size={56} strokeWidth={4} color="#f59e0b" label="Draw" />
                    )}
                    <RadialProgress value={match.sofascore.away ?? 0} size={56} strokeWidth={4} color="#ef4444" label="Away" />
                  </div>
                  <p className="text-xs text-muted-foreground text-center">
                    {formatVotes(match.sofascore.votes)} total votes
                  </p>
                </div>
              )}

              {/* Scoring Engine */}
              {match.scoring && (
                <div className="rounded-xl border bg-card p-4 space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <TrendingUp className="h-4 w-4 text-violet-500" /> Scoring Engine
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <StatBox label="Pick" value={
                      <Badge className="bg-violet-500 text-white mt-0.5">{match.scoring.pick || '-'}</Badge>
                    } />
                    <StatBox label="Probability" value={
                      <span className="font-bold">{formatPct(num(match.scoring.prob))}</span>
                    } />
                    <StatBox label="Expected Value" value={
                      <span className={cn('font-bold', num(match.scoring.ev) > 0 ? 'text-emerald-600' : 'text-rose-600')}>
                        {num(match.scoring.ev) > 0 ? '+' : ''}{num(match.scoring.ev).toFixed(3)}
                      </span>
                    } />
                    <StatBox label="Edge" value={
                      <span className={cn('font-bold', num(match.scoring.edge) > 0 ? 'text-emerald-600' : 'text-muted-foreground')}>
                        {num(match.scoring.edge) > 0 ? '+' : ''}{num(match.scoring.edge).toFixed(1)}%
                      </span>
                    } />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <StatBox label="Kelly %" value={
                      <span className="font-bold">{num(match.scoring.kelly).toFixed(1)}%</span>
                    } />
                    <StatBox label="Data Quality" value={
                      <RadialProgress value={num(match.scoring.dataQuality) * 100} size={36} strokeWidth={3} color="#8b5cf6" />
                    } />
                  </div>
                  {/* Tennis-specific info */}
                  {match.tennis && (
                    <div className="flex items-center gap-3 text-xs text-muted-foreground bg-muted/40 rounded-lg p-2.5">
                      {match.tennis.surface && <span>Surface: <strong>{match.tennis.surface}</strong></span>}
                      {match.tennis.rankingA != null && <span>#{match.tennis.rankingA} vs #{match.tennis.rankingB}</span>}
                      <span className="ml-auto font-mono tabular-nums">
                        A: {formatPct(num(match.tennis.probA))} · B: {formatPct(num(match.tennis.probB))}
                      </span>
                    </div>
                  )}
                </div>
              )}

              {!match.forebet && !match.sofascore?.home && !match.scoring && (
                <EmptyState text="No predictions available for this match." />
              )}
            </TabsContent>

            {/* ── Odds tab ── */}
            <TabsContent value="odds" className="mt-4">
              {match.odds ? (
                <div className="rounded-xl border bg-card p-4 space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">Match Odds</span>
                    {match.odds.bookmaker && (
                      <span className="text-xs text-muted-foreground">{match.odds.bookmaker}</span>
                    )}
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <OddsBox label="Home" value={match.odds.home} highlighted={match.forebet?.prediction === '1'} />
                    {match.odds.draw != null && (
                      <OddsBox label="Draw" value={match.odds.draw} highlighted={match.forebet?.prediction === 'X'} />
                    )}
                    <OddsBox label="Away" value={match.odds.away} highlighted={match.forebet?.prediction === '2'} />
                  </div>
                  {match.value_bet && (
                    <div className="flex items-center gap-2 rounded-lg bg-amber-500/10 border border-amber-500/20 p-2.5">
                      <Zap className="h-4 w-4 text-amber-500" />
                      <span className="text-xs font-medium text-amber-700 dark:text-amber-400">Value bet detected — odds may offer positive expected value</span>
                    </div>
                  )}
                </div>
              ) : (
                <EmptyState text="No odds data available." />
              )}
            </TabsContent>

            {/* ── H2H tab ── */}
            <TabsContent value="h2h" className="mt-4">
              {match.h2h ? (
                <div className="rounded-xl border bg-card p-4 space-y-4">
                  <span className="text-sm font-medium">Head to Head</span>
                  <H2HBar
                    home={match.h2h.home}
                    draw={match.h2h.draw}
                    away={match.h2h.away}
                    homeTeam={match.homeTeam}
                    awayTeam={match.awayTeam}
                  />
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <StatBox label={match.homeTeam} value={
                      <span className="text-2xl font-bold text-emerald-600">{match.h2h.home}</span>
                    } />
                    <StatBox label="Draws" value={
                      <span className="text-2xl font-bold text-amber-600">{match.h2h.draw}</span>
                    } />
                    <StatBox label={match.awayTeam} value={
                      <span className="text-2xl font-bold text-rose-600">{match.h2h.away}</span>
                    } />
                  </div>
                </div>
              ) : (
                <EmptyState text="No head-to-head data available." />
              )}
            </TabsContent>

            {/* ── AI Analysis tab ── */}
            <TabsContent value="ai" className="mt-4">
              {match.aiPrediction ? (
                <AIPredictionPanel
                  prediction={match.aiPrediction}
                  homeTeam={match.homeTeam}
                  awayTeam={match.awayTeam}
                />
              ) : match.gemini ? (
                <div className="rounded-xl border bg-card p-4 space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <Brain className="h-4 w-4 text-violet-500" /> Gemini AI Analysis
                    </div>
                    <RecommendationBadge recommendation={match.gemini.recommendation} size="md" />
                  </div>

                  {match.gemini.prediction && (
                    <div className="flex items-center gap-3 rounded-lg bg-violet-500/5 border border-violet-500/10 p-3">
                      <span className="text-sm text-muted-foreground">Prediction:</span>
                      <Badge className="bg-violet-500 text-white">{match.gemini.prediction}</Badge>
                      {match.gemini.confidence && (
                        <RadialProgress value={match.gemini.confidence} size={36} strokeWidth={3} color="#8b5cf6" />
                      )}
                    </div>
                  )}

                  {match.gemini.reasoning && (
                    <div className="space-y-2">
                      <span className="text-xs text-muted-foreground font-medium">Analysis</span>
                      <div className="bg-muted/50 rounded-lg p-3 text-sm leading-relaxed whitespace-pre-line">
                        {match.gemini.reasoning}
                      </div>
                    </div>
                  )}
                </div>
              ) : match.scoring ? (
                <div className="rounded-xl border bg-card p-4 space-y-4">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Brain className="h-4 w-4 text-violet-500" /> Scoring Engine Analysis
                  </div>
                  <div className="flex items-center gap-3 rounded-lg bg-violet-500/5 border border-violet-500/10 p-3">
                    <span className="text-sm text-muted-foreground">Pick:</span>
                    <Badge className="bg-violet-500 text-white">{match.scoring.pick || '-'}</Badge>
                    <RadialProgress value={num(match.scoring.confidence)} size={36} strokeWidth={3} color="#8b5cf6" />
                  </div>
                  <div className="grid grid-cols-3 gap-3 text-center">
                    <div className="rounded-lg bg-muted/40 p-2.5">
                      <p className="text-[10px] text-muted-foreground mb-1">EV</p>
                      <p className={cn('text-lg font-bold tabular-nums', num(match.scoring.ev) > 0 ? 'text-emerald-600' : 'text-rose-600')}>
                        {num(match.scoring.ev) > 0 ? '+' : ''}{num(match.scoring.ev).toFixed(3)}
                      </p>
                    </div>
                    <div className="rounded-lg bg-muted/40 p-2.5">
                      <p className="text-[10px] text-muted-foreground mb-1">Edge</p>
                      <p className="text-lg font-bold tabular-nums">{num(match.scoring.edge) > 0 ? '+' : ''}{num(match.scoring.edge).toFixed(1)}%</p>
                    </div>
                    <div className="rounded-lg bg-muted/40 p-2.5">
                      <p className="text-[10px] text-muted-foreground mb-1">Kelly</p>
                      <p className="text-lg font-bold tabular-nums">{num(match.scoring.kelly).toFixed(1)}%</p>
                    </div>
                  </div>
                </div>
              ) : (
                <EmptyState text="No AI analysis available for this match." />
              )}
            </TabsContent>

            {/* ── Weather tab ── */}
            <TabsContent value="weather" className="mt-4">
              {weather ? (
                <div className="rounded-xl border bg-card p-4 space-y-4">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <CloudSun className="h-4 w-4 text-sky-500" /> Match Day Weather
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {weather.city} &middot; {weather.date} &middot; {weather.description}
                  </p>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="rounded-lg bg-muted/40 p-3 text-center">
                      <Thermometer className="h-4 w-4 mx-auto mb-1 text-orange-500" />
                      <p className="text-lg font-bold tabular-nums">
                        {weather.tempMax != null ? `${weather.tempMax}°` : '—'}
                      </p>
                      <p className="text-[10px] text-muted-foreground">Max temp</p>
                    </div>
                    <div className="rounded-lg bg-muted/40 p-3 text-center">
                      <Thermometer className="h-4 w-4 mx-auto mb-1 text-blue-500" />
                      <p className="text-lg font-bold tabular-nums">
                        {weather.tempMin != null ? `${weather.tempMin}°` : '—'}
                      </p>
                      <p className="text-[10px] text-muted-foreground">Min temp</p>
                    </div>
                    <div className="rounded-lg bg-muted/40 p-3 text-center">
                      <Wind className="h-4 w-4 mx-auto mb-1 text-teal-500" />
                      <p className="text-lg font-bold tabular-nums">
                        {weather.windSpeed != null ? `${weather.windSpeed}` : '—'}
                      </p>
                      <p className="text-[10px] text-muted-foreground">Wind km/h</p>
                    </div>
                    <div className="rounded-lg bg-muted/40 p-3 text-center">
                      <Droplets className="h-4 w-4 mx-auto mb-1 text-blue-400" />
                      <p className="text-lg font-bold tabular-nums">
                        {weather.precipitation != null ? `${weather.precipitation}mm` : '—'}
                      </p>
                      <p className="text-[10px] text-muted-foreground">Rain</p>
                    </div>
                  </div>
                  {weather.precipitation != null && weather.precipitation > 5 && (
                    <div className="flex items-center gap-2 rounded-lg bg-blue-500/10 border border-blue-500/20 p-2.5">
                      <Droplets className="h-4 w-4 text-blue-500" />
                      <span className="text-xs font-medium text-blue-700 dark:text-blue-400">
                        Significant rain expected — may affect match conditions
                      </span>
                    </div>
                  )}
                  {weather.windSpeed != null && weather.windSpeed > 40 && (
                    <div className="flex items-center gap-2 rounded-lg bg-amber-500/10 border border-amber-500/20 p-2.5">
                      <Wind className="h-4 w-4 text-amber-500" />
                      <span className="text-xs font-medium text-amber-700 dark:text-amber-400">
                        Strong winds — may influence long balls and set pieces
                      </span>
                    </div>
                  )}
                </div>
              ) : (
                <EmptyState text="Weather data not available for this location." />
              )}
            </TabsContent>
          </Tabs>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── Helpers ──

/** Coerce possibly-null/undefined/NaN numeric API values to a safe number. */
function num(v: number | null | undefined, fallback = 0): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback
}

// ── Helper components ──

function StatBox({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-muted/40 p-2.5 text-center">
      <p className="text-[10px] text-muted-foreground mb-1 truncate">{label}</p>
      <div>{value}</div>
    </div>
  )
}

function OddsBox({ label, value, highlighted }: { label: string; value: number | null; highlighted?: boolean }) {
  return (
    <div className={cn(
      'text-center rounded-lg border p-3 transition-colors',
      highlighted && 'border-primary/40 bg-primary/5',
    )}>
      <p className="text-[10px] text-muted-foreground mb-1">{label}</p>
      <p className="text-xl font-bold tabular-nums">{formatOdds(value)}</p>
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return (
    <p className="text-sm text-muted-foreground text-center py-8">{text}</p>
  )
}
