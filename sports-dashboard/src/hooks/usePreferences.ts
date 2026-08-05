// ============================================================================
// usePreferences – which sports and leagues the signed-in reader follows
// ============================================================================
'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getPreferences, savePreferences } from '@/lib/api'
import { useAuthStore } from '@/store/authStore'

export function usePreferences() {
  const user = useAuthStore(s => s.user)
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: ['preferences', user?.id ?? 'anonymous'],
    queryFn: getPreferences,
    // Nothing to fetch for a visitor who is not signed in.
    enabled: !!user,
    staleTime: 5 * 60_000,
  })

  const save = useMutation({
    mutationFn: ({ sports, leagues }: { sports: string[]; leagues: string[] }) =>
      savePreferences(sports, leagues),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['preferences'] }),
  })

  return {
    sports: query.data?.sports ?? [],
    leagues: query.data?.leagues ?? [],
    /**
     * Whether to offer the questionnaire. Only for a signed-in reader who has
     * never answered it — answering with nothing selected still counts, so it is
     * not shown again to someone who deliberately skipped.
     */
    needsOnboarding: !!user && query.isSuccess && query.data?.available === true
      && query.data?.onboarded === false,
    isLoading: query.isLoading,
    save,
  }
}
