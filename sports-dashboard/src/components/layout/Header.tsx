// ============================================================================
// Header – top bar with navigation, auth, and theme toggle
// ============================================================================
'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  Trophy, BarChart3, Ticket, Users, Sun, Moon, Menu, LogIn, LogOut, Crown,
} from 'lucide-react'
import { useTheme } from 'next-themes'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet'
import { AuthDialog } from '@/components/auth/AuthDialog'
import { useAuthStore } from '@/store/authStore'
import { useSubscription } from '@/hooks/useSubscription'

const NAV_ITEMS = [
  { href: '/standings',   label: 'Tabele',      icon: Trophy     },
  { href: '/stats',       label: 'Statystyki',  icon: BarChart3  },
  { href: '/my-bets',     label: 'Moje typy',   icon: Ticket     },
  { href: '/leaderboard', label: 'Ranking',     icon: Users      },
]

function NavLinks({ mobile, onNavigate }: { mobile?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname()
  return (
    <>
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const active = pathname === href
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              'flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
              mobile ? 'w-full' : '',
              active
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        )
      })}
    </>
  )
}

export function Header() {
  const { theme, setTheme } = useTheme()
  const { user, init, signOut } = useAuthStore()
  const { isSubscriber } = useSubscription()
  const [authOpen, setAuthOpen] = useState(false)

  useEffect(() => { init() }, [init])

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-14 max-w-[1700px] items-center gap-4 px-2 sm:px-4">
        {/* Mobile menu */}
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" className="md:hidden">
              <Menu className="h-5 w-5" />
              <span className="sr-only">Menu</span>
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-64 pt-10">
            <nav className="flex flex-col gap-1">
              <NavLinks mobile />
            </nav>
          </SheetContent>
        </Sheet>

        {/* Logo */}
        {/* Brand name is a placeholder until the real one is chosen. */}
        <Link href="/" className="flex items-center gap-2 whitespace-nowrap font-bold">
          <Trophy className="h-5 w-5 shrink-0 text-primary" />
          <span className="hidden flex-col leading-none sm:flex">
            <span className="text-base">Analiza Sportowa</span>
            <span className="text-[10px] font-normal text-muted-foreground">
              narzędzie analityczne
            </span>
          </span>
          <span className="text-base sm:hidden">AS</span>
        </Link>

        {/* Desktop nav */}
        <nav className="hidden md:flex items-center gap-1 ml-6">
          <NavLinks />
        </nav>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Premium / Upgrade */}
        <Link href="/pricing">
          <Button
            variant={isSubscriber ? 'ghost' : 'default'}
            size="sm"
            className={cn('gap-1.5', isSubscriber && 'text-amber-500')}
            title={isSubscriber ? 'Premium aktywne' : 'Odblokuj ocenę A'}
          >
            <Crown className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{isSubscriber ? 'Premium' : 'Kup dostęp'}</span>
          </Button>
        </Link>

        {/* Auth controls */}
        {user ? (
          <div className="flex items-center gap-2">
            <span className="hidden sm:inline text-xs text-muted-foreground truncate max-w-[120px]">
              {user.email}
            </span>
            <Button variant="ghost" size="icon" onClick={() => signOut()} title="Wyloguj">
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        ) : (
          <Button variant="outline" size="sm" onClick={() => setAuthOpen(true)} className="gap-1.5">
            <LogIn className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Zaloguj</span>
          </Button>
        )}

        {/* Theme toggle */}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        >
          <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
          <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
          <span className="sr-only">Przełącz motyw</span>
        </Button>
      </div>

      {/* Auth dialog */}
      <AuthDialog open={authOpen} onOpenChange={setAuthOpen} />
    </header>
  )
}
