// ============================================================================
// SPORTS DASHBOARD - React‑Query hooks
// ============================================================================
'use client'
import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import * as api from '@/lib/api'
import { useFilterStore } from '@/store/filterStore'

export function useMatches() {
  const { sport, date, search } = useFilterStore()
  const dateStr = date ? format(date, 'yyyy-MM-dd') : undefined

  return useQuery({
    queryKey: ['matches', sport, dateStr ?? 'latest', search],
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
