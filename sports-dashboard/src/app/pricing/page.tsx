// ============================================================================
// Pricing Page – weekly $5 subscription that unlocks Grade A predictions
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
  'Wszystkie analizy z oceną B',
  'Kursy, forma i bilans bezpośrednich spotkań',
  'Wyniki na żywo i szczegóły zdarzeń',
  'Zapisywanie typów i statystyki',
]

const PREMIUM_FEATURES = [
  'Wszystko z planu darmowego',
  'Analizy z oceną A, o najwyższej pewności modelu',
  'Pełna analiza modelu, wartość oczekiwana i kryterium Kelly',
  'Wskazania wartości i poziom pewności',
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
      toast.success('Subskrypcja aktywna. Oceny A odblokowane.')
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
      toast('Płatność anulowana. Nie pobrano opłaty.')
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
        toast.error('Could not start checkout. Please try again.')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Nie udało się rozpocząć płatności')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-10">
      {/* Hero */}
      <div className="text-center mb-10">
        <Badge variant="secondary" className="mb-3 gap-1">
          <Sparkles className="h-3.5 w-3.5" /> Analizy Premium
        </Badge>
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">
          Odblokuj analizy z oceną A
        </h1>
        <p className="mt-3 text-muted-foreground max-w-xl mx-auto">
          Ocena B pozostaje darmowa na stałe. W Premium widzisz zdarzenia z oceną A,
          o najwyższej pewności modelu, wraz z pełną analizą. 5 USD tygodniowo,
          rezygnacja w każdej chwili.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Free plan */}
        <Card className="p-6 flex flex-col">
          <div className="mb-4">
            <h2 className="text-lg font-semibold">Darmowy</h2>
            <p className="text-sm text-muted-foreground">Start bez karty płatniczej</p>
          </div>
          <div className="mb-6">
            <span className="text-3xl font-bold">$0</span>
            <span className="text-muted-foreground">/tydzień</span>
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
            Twój obecny plan
          </Button>
        </Card>

        {/* Premium plan */}
        <Card className="p-6 flex flex-col relative border-primary/40 ring-1 ring-primary/20">
          <div className="absolute -top-3 left-6">
            <Badge className="gap-1 bg-primary text-primary-foreground">
              <Crown className="h-3.5 w-3.5" /> Najczęściej wybierany
            </Badge>
          </div>
          <div className="mb-4">
            <h2 className="text-lg font-semibold flex items-center gap-1.5">
              Premium
            </h2>
            <p className="text-sm text-muted-foreground">Pełny dostęp do ocen A</p>
          </div>
          <div className="mb-6">
            <span className="text-3xl font-bold">$5</span>
            <span className="text-muted-foreground">/tydzień</span>
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
                <Crown className="h-4 w-4" /> Subskrypcja aktywna
              </Button>
              {currentPeriodEnd && (
                <p className="text-xs text-center text-muted-foreground">
                  Odnowienie {new Date(currentPeriodEnd).toLocaleDateString('pl-PL')}
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
              {user ? 'Wykup dostęp za 5 USD tygodniowo' : 'Zaloguj się, aby wykupić dostęp'}
            </Button>
          )}
        </Card>
      </div>

      <p className="mt-8 text-center text-xs text-muted-foreground">
        Bezpieczną płatność obsługuje Stripe. Rezygnacja w każdej chwili z poziomu konta.
        Analizy mają charakter informacyjny i nie są gwarancją wyniku. Nie przyjmujemy
        zakładów. Serwis dla osób powyżej 18 lat.
      </p>

      <AuthDialog open={authOpen} onOpenChange={setAuthOpen} />
    </main>
  )
}
