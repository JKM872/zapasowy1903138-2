// ============================================================================
// Pricing Page – weekly 19 zł subscription that unlocks Grade A predictions
// ============================================================================
'use client'

import { Suspense, useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { Check, Crown, Loader2, Lock, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { AuthDialog } from '@/components/auth/AuthDialog'
import { useAuthStore } from '@/store/authStore'
import { useSubscription } from '@/hooks/useSubscription'
import * as api from '@/lib/api'

const FREE_FEATURES = [
  'All Grade B analyses',
  'Odds, form and head-to-head record',
  'Live scores and event details',
  'Save your picks and track stats',
]

const PREMIUM_FEATURES = [
  'Everything in Free',
  'Top Picks before kick-off (settled results stay public)',
  'Grade A analyses with the highest model confidence',
  'Full model analysis, expected value and Kelly criterion',
  'Value signals and confidence levels',
]

export default function PricingPage() {
  return (
    <Suspense fallback={null}>
      <PricingContent />
    </Suspense>
  )
}

function PricingContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const queryClient = useQueryClient()
  const user = useAuthStore((s) => s.user)
  const { isSubscriber, currentPeriodEnd, refetch } = useSubscription()
  const [authOpen, setAuthOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  // Handle Stripe redirect result
  useEffect(() => {
    if (searchParams.get('success')) {
      toast.success('Subscription active. Grade A unlocked.')
      // Give the webhook a moment, then refresh status
      const t = setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['subscription'] })
        queryClient.invalidateQueries({ queryKey: ['matches'] })
        refetch()
      }, 1500)
      router.replace('/pricing')
      return () => clearTimeout(t)
    }
    if (searchParams.get('canceled')) {
      toast('Payment cancelled. You have not been charged.')
      router.replace('/pricing')
    }
  }, [searchParams, queryClient, refetch, router])

  const handleSubscribe = async () => {
    if (!user) {
      setAuthOpen(true)
      return
    }
    setLoading(true)
    try {
      const { url } = await api.createCheckoutSession(user.email ?? undefined)
      if (url) {
        window.location.href = url
      } else {
        toast.error('Couldn’t start checkout. Please try again.')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Couldn’t start checkout')
    } finally {
      setLoading(false)
    }
  }

  const handleManage = async () => {
    setLoading(true)
    try {
      const { url } = await api.openBillingPortal()
      if (url) window.location.href = url
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Couldn’t open the billing portal')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-10">
      {/* Hero */}
      <div className="text-center mb-10">
        <Badge variant="secondary" className="mb-3 gap-1">
          <Sparkles className="h-3.5 w-3.5" /> Premium Analysis
        </Badge>
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">
          Unlock Grade A analysis
        </h1>
        <p className="mt-3 text-muted-foreground max-w-xl mx-auto">
          Grade B stays free forever. Premium shows Grade A events, where the model
          is most confident, with the full analysis. $5 / €5 per week,
          cancel anytime.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Free plan */}
        <Card className="p-6 flex flex-col">
          <div className="mb-4">
            <h2 className="text-lg font-semibold">Free</h2>
            <p className="text-sm text-muted-foreground">No card required</p>
          </div>
          <div className="mb-6">
            <span className="text-3xl font-bold">$0</span>
            <span className="text-muted-foreground"> forever</span>
          </div>
          <ul className="space-y-2.5 flex-1">
            {FREE_FEATURES.map((f) => (
              <li key={f} className="flex items-start gap-2 text-sm">
                <Check className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
                <span>{f}</span>
              </li>
            ))}
          </ul>
          <Button variant="outline" className="mt-6 w-full" disabled>
            Your current plan
          </Button>
        </Card>

        {/* Premium plan */}
        <Card className="p-6 flex flex-col relative border-primary/40 ring-1 ring-primary/20">
          <div className="absolute -top-3 left-6">
            <Badge className="gap-1 bg-primary text-primary-foreground">
              <Crown className="h-3.5 w-3.5" /> Premium
            </Badge>
          </div>
          <div className="mb-4">
            <h2 className="text-lg font-semibold flex items-center gap-1.5">
              Premium
            </h2>
            <p className="text-sm text-muted-foreground">Full access to Grade A</p>
          </div>
          <div className="mb-6">
            <span className="text-3xl font-bold">$5</span>
            <span className="text-muted-foreground">/week</span>
            <p className="text-xs text-muted-foreground">or €5 · billed weekly</p>
          </div>
          <ul className="space-y-2.5 flex-1">
            {PREMIUM_FEATURES.map((f) => (
              <li key={f} className="flex items-start gap-2 text-sm">
                <Check className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
                <span>{f}</span>
              </li>
            ))}
          </ul>

          {isSubscriber ? (
            <div className="mt-6 space-y-2">
              <Button className="w-full gap-1.5" disabled>
                <Crown className="h-4 w-4" /> Subscription active
              </Button>
              <Button variant="outline" className="w-full" onClick={handleManage} disabled={loading}>
                Manage or cancel subscription
              </Button>
              {currentPeriodEnd && (
                <p className="text-xs text-center text-muted-foreground">
                  Renews {new Date(currentPeriodEnd).toLocaleDateString('en-GB')}
                </p>
              )}
            </div>
          ) : (
            <Button className="mt-6 w-full gap-1.5" onClick={handleSubscribe} disabled={loading}>
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Lock className="h-4 w-4" />
              )}
              {user ? 'Get Premium – $5/week' : 'Sign in to get Premium'}
            </Button>
          )}
        </Card>
      </div>

      <p className="mt-8 text-center text-xs text-muted-foreground">
        Secure payments by Stripe. Cancel anytime from your account.
        Analyses are for information only and do not guarantee any result. We do not
        accept bets. 18+ only.
      </p>

      <AuthDialog open={authOpen} onOpenChange={setAuthOpen} />
    </main>
  )
}
