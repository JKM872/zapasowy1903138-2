// ============================================================================
// SPORTS DASHBOARD - React‑Query hooks
// ============================================================================
'use client'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import * as api from '@/lib/api'
import { useFilterStore } from '@/store/filterStore'
import { useAuthStore } from '@/store/authStore'

export function useMatches() {
  const { sport, date, search } = useFilterStore()
  const userId = useAuthStore((s) => s.user?.id ?? 'anon')
  const dateStr = date ? format(date, 'yyyy-MM-dd') : undefined

  return useQuery({
    // userId in the key so matches refetch after login/logout — the server
    // unlocks Grade A for active subscribers based on the auth token.
    queryKey: ['matches', sport, dateStr ?? 'latest', search, userId],
    queryFn: () => api.getMatches({ sport, date: dateStr, search }),
    staleTime: 60_000,          // 1 min
    refetchInterval: 300_000,   // 5 min background refresh
  })
}

export function useMatchDetail(id: string) {
  return useQuery({
    queryKey: ['match', id],
    queryFn: () => api.getMatch(id),
    enabled: !!id,
  })
}

export function useStats(days = 30) {
  return useQuery({
    queryKey: ['stats', days],
    queryFn: () => api.getStats(days),
    staleTime: 300_000,
  })
}

export function useAvailableDates() {
  return useQuery({
    queryKey: ['dates'],
    queryFn: () => api.getAvailableDates(),
    staleTime: 600_000,
  })
}

export function useLiveScores(sport: string = 'football') {
  return useQuery({
    queryKey: ['live-scores', sport],
    queryFn: () => api.getLiveScores(sport),
    staleTime: 15_000,            // 15s stale
    refetchInterval: 30_000,      // Poll every 30s
    refetchIntervalInBackground: false,  // Stop when tab is inactive
  })
}

// ---------------------------------------------------------------------------
// User Bets hooks
// ---------------------------------------------------------------------------

export function useBets(params?: { status?: string; days?: number; limit?: number }) {
  return useQuery({
    queryKey: ['bets', params?.status, params?.days, params?.limit],
    queryFn: () => api.getBets(params),
    staleTime: 30_000,
  })
}

export function useBetStats() {
  return useQuery({
    queryKey: ['bet-stats'],
    queryFn: () => api.getBetStats(),
    staleTime: 60_000,
  })
}

export function useCreateBet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.createBet,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bets'] })
      qc.invalidateQueries({ queryKey: ['bet-stats'] })
    },
  })
}

export function useSettleBet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ betId, ...data }: { betId: number; actual_result: string; home_score: number; away_score: number }) =>
      api.settleBet(betId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bets'] })
      qc.invalidateQueries({ queryKey: ['bet-stats'] })
    },
  })
}

export function useDeleteBet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.deleteBet,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bets'] })
      qc.invalidateQueries({ queryKey: ['bet-stats'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Weather
// ---------------------------------------------------------------------------

export function useWeather(city: string, date?: string) {
  return useQuery({
    queryKey: ['weather', city, date],
    queryFn: () => api.getWeather(city, date),
    enabled: !!city,
    staleTime: 3600_000,       // 1 hour
    retry: 1,                  // Don't hammer on failure
  })
}

// ---------------------------------------------------------------------------
// League Standings (Football-Data.org)
// ---------------------------------------------------------------------------

export function useStandings(league: string = 'PL') {
  return useQuery({
    queryKey: ['standings', league],
    queryFn: () => api.getStandings(league),
    staleTime: 600_000,   // 10 min
    retry: 1,
  })
}

export function useAvailableLeagues() {
  return useQuery({
    queryKey: ['available-leagues'],
    queryFn: () => api.getAvailableLeagues(),
    staleTime: 3600_000,
  })
}

// ---------------------------------------------------------------------------
// Team info (TheSportsDB)
// ---------------------------------------------------------------------------

export function useTeamInfo(team: string) {
  return useQuery({
    queryKey: ['team-info', team],
    queryFn: () => api.getTeamInfo(team),
    enabled: !!team,
    staleTime: 86400_000,   // 24h — metadata rarely changes
    retry: 1,
  })
}
