// ============================================================================
// PromoBanner – freemium upsell shown on the home page to non-subscribers
// ============================================================================
'use client'

import Link from 'next/link'
import { Crown, ArrowRight } from 'lucide-react'
import { useSubscription } from '@/hooks/useSubscription'

export function PromoBanner() {
  const { isSubscriber } = useSubscription()
  if (isSubscriber) return null

  return (
    <div className="mx-auto max-w-[1700px] px-2 pt-3 sm:px-4">
      <Link
        href="/pricing"
        className="group flex items-center gap-3 rounded-md border border-primary/30 bg-gradient-to-r from-primary/10 via-primary/5 to-transparent p-3 transition-colors hover:border-primary/50"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/15 text-primary">
          <Crown className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold leading-tight">
            Odblokuj zdarzenia z oceną A — analizy o najwyższej pewności modelu
          </p>
          <p className="text-xs text-muted-foreground">
            Ocena B jest darmowa. Pełna analiza w Premium za 5 USD tygodniowo.
          </p>
        </div>
        <span className="hidden items-center gap-1 text-xs font-semibold text-primary sm:inline-flex">
          Kup dostęp
          <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
        </span>
      </Link>
    </div>
  )
}
