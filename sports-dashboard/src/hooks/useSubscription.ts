// ============================================================================
// useSubscription – current user's subscription status (Grade A access)
// ============================================================================
'use client'

import { useQuery } from '@tanstack/react-query'
import * as api from '@/lib/api'
import { useAuthStore } from '@/store/authStore'

/**
 * Returns the current user's subscription status.
 * Only queries when the user is authenticated; anonymous users are inactive.
 */
export function useSubscription() {
  const user = useAuthStore((s) => s.user)

  const query = useQuery({
    queryKey: ['subscription', user?.id ?? 'anon'],
    queryFn: () => api.getSubscriptionStatus(),
    enabled: !!user,
    staleTime: 60_000,     // avoid refetching on every render
    retry: 1,
  })

  return {
    ...query,
    isSubscriber: !!user && (query.data?.active ?? false),
    status: query.data?.status ?? 'inactive',
    currentPeriodEnd: query.data?.current_period_end ?? null,
  }
}
