// ============================================================================
// EventsShell – three-column bookmaker layout: sports / events / basket
// ============================================================================
'use client'

import { useState, type ReactNode } from 'react'
import { PanelLeft, ShoppingCart } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { SportSidebar } from './SportSidebar'
import type { Match } from '@/lib/types'

interface Props {
  sportCounts?: Record<string, number>
  matches?: Match[]
  /** Right rail content. When omitted the shell falls back to two columns. */
  aside?: ReactNode
  /** Number shown on the mobile basket button. */
  asideCount?: number
  children: ReactNode
}

/**
 * The old layout squeezed everything into `max-w-5xl` with horizontal sport
 * tabs, which is why the event rows had no room and elements piled up. Sports
 * and the basket move into side panels so the middle column can breathe.
 */
export function EventsShell({
  sportCounts,
  matches,
  aside,
  asideCount = 0,
  children,
}: Props) {
  const [sportsOpen, setSportsOpen] = useState(false)
  const [basketOpen, setBasketOpen] = useState(false)

  return (
    <div className="mx-auto w-full max-w-[1700px] px-2 sm:px-4">
      {/* Mobile panel triggers */}
      <div className="flex items-center gap-2 py-2 lg:hidden">
        <Sheet open={sportsOpen} onOpenChange={setSportsOpen}>
          <SheetTrigger asChild>
            <Button variant="outline" size="sm" className="gap-1.5">
              <PanelLeft className="h-4 w-4" />
              Dyscypliny
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-[280px] overflow-y-auto">
            <SheetHeader>
              <SheetTitle>Dyscypliny</SheetTitle>
            </SheetHeader>
            <div className="mt-3">
              <SportSidebar
                sportCounts={sportCounts}
                matches={matches}
                onNavigate={() => setSportsOpen(false)}
              />
            </div>
          </SheetContent>
        </Sheet>

        {aside && (
          <Sheet open={basketOpen} onOpenChange={setBasketOpen}>
            <SheetTrigger asChild>
              <Button variant="outline" size="sm" className="ml-auto gap-1.5">
                <ShoppingCart className="h-4 w-4" />
                Koszyk
                {asideCount > 0 && (
                  <span className="rounded-full bg-primary px-1.5 text-[10px] font-bold text-primary-foreground tabular-nums">
                    {asideCount}
                  </span>
                )}
              </Button>
            </SheetTrigger>
            <SheetContent side="right" className="w-[340px] overflow-y-auto">
              <SheetHeader>
                <SheetTitle>Koszyk analityczny</SheetTitle>
              </SheetHeader>
              <div className="mt-3">{aside}</div>
            </SheetContent>
          </Sheet>
        )}
      </div>

      <div
        className={
          aside
            ? 'grid gap-3 lg:grid-cols-[232px_minmax(0,1fr)] xl:grid-cols-[232px_minmax(0,1fr)_324px]'
            : 'grid gap-3 lg:grid-cols-[232px_minmax(0,1fr)]'
        }
      >
        {/* Sports tree – sticky so it stays put while the event list scrolls */}
        <aside className="hidden lg:block">
          <div className="sticky top-16 max-h-[calc(100vh-5rem)] overflow-y-auto rounded-md border border-border bg-panel p-2 scrollbar-thin">
            <SportSidebar sportCounts={sportCounts} matches={matches} />
          </div>
        </aside>

        {/* Events */}
        <div className="min-w-0 py-1">{children}</div>

        {/* Basket */}
        {aside && (
          <aside className="hidden xl:block">
            <div className="sticky top-16 max-h-[calc(100vh-5rem)] overflow-y-auto rounded-md border border-border bg-panel scrollbar-thin">
              {aside}
            </div>
          </aside>
        )}
      </div>
    </div>
  )
}
