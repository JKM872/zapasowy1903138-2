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
    <div className="mx-auto max-w-5xl px-4 pt-4">
      <Link
        href="/pricing"
        className="group flex items-center gap-3 rounded-xl border border-primary/30 bg-gradient-to-r from-primary/10 via-primary/5 to-transparent p-3.5 transition-colors hover:border-primary/50"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
          <Crown className="h-4.5 w-4.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold leading-tight">
            Unlock Grade A picks — our highest-conviction selections
          </p>
          <p className="text-xs text-muted-foreground">
            Grade B is free. Go Premium for full AI analysis at $5/week.
          </p>
        </div>
        <span className="hidden sm:inline-flex items-center gap-1 text-xs font-semibold text-primary">
          Upgrade
          <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
        </span>
      </Link>
    </div>
  )
}
