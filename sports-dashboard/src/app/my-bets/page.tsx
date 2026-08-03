// ============================================================================
// My Bets Page – personal bet tracker backed by Heroku API
// ============================================================================
'use client'

import { useState } from 'react'
import {
  Plus, Trash2, TrendingUp, TrendingDown, Minus, Loader2, AlertCircle,
  LogIn, Target,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import { useBets, useBetStats, useCreateBet, useDeleteBet } from '@/hooks/useMatches'
import { useAuthStore } from '@/store/authStore'
import { AuthDialog } from '@/components/auth/AuthDialog'
import type { ApiBet } from '@/lib/api'

/** The API returns raw English statuses; these are what the user should read. */
const BET_STATUS_LABELS: Record<string, string> = {
  won: 'trafiony',
  lost: 'nietrafiony',
  pending: 'w toku',
  void: 'anulowany',
}

export default function MyBetsPage() {
  const { user } = useAuthStore()
  const { data, isLoading, isError, error } = useBets({ limit: 200 })
  const { data: betStats } = useBetStats()
  const createBet = useCreateBet()
  const deleteBetMut = useDeleteBet()
  const [authOpen, setAuthOpen] = useState(false)

  const bets = data?.bets ?? []

  // Add bet form state
  const [homeTeam, setHomeTeam] = useState('')
  const [awayTeam, setAwayTeam] = useState('')
  const [pick, setPick] = useState<'1' | 'X' | '2' | ''>('')
  const [odds, setOdds] = useState('')
  const [stake, setStake] = useState('')
  const [matchDate, setMatchDate] = useState(new Date().toISOString().slice(0, 10))
  const [dialogOpen, setDialogOpen] = useState(false)

  const addBet = () => {
    if (!homeTeam || !awayTeam || !pick) return
    createBet.mutate(
      {
        home_team: homeTeam,
        away_team: awayTeam,
        match_date: matchDate,
        bet_selection: pick,
        odds_at_bet: parseFloat(odds) || 1.5,
        stake: parseFloat(stake) || 10,
      },
      {
        onSuccess: () => {
          setHomeTeam('')
          setAwayTeam('')
          setPick('')
          setOdds('')
          setStake('')
          setDialogOpen(false)
        },
      },
    )
  }

  const removeBet = (id: number) => {
    deleteBetMut.mutate(id)
  }

  // Stats
  const total = betStats?.total_bets ?? bets.length
  const won = betStats?.won ?? 0
  const lost = betStats?.lost ?? 0
  const pending = betStats?.pending ?? 0
  const profit = betStats?.total_profit ?? 0
  const winRate = betStats?.win_rate ?? 0
  const roi = betStats?.roi ?? 0

  // Auth gate — prompt sign in for write actions
  if (!user) {
    return (
      <div className="mx-auto max-w-6xl space-y-5 px-3 py-6 sm:px-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Moje typy</h1>
          <p className="text-muted-foreground mt-1">
            Zapisuj swoje typy i sprawdzaj, jak wychodzą w czasie.
          </p>
        </div>
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16 gap-4">
            <div className="rounded-full bg-primary/10 p-4">
              <LogIn className="h-8 w-8 text-primary" />
            </div>
            <div className="text-center space-y-1">
              <p className="font-semibold text-lg">Zaloguj się, aby zapisywać typy</p>
              <p className="text-sm text-muted-foreground max-w-sm">
                Utwórz konto, aby zapisywać typy, liczyć skuteczność i ROI.
              </p>
            </div>
            <Button onClick={() => setAuthOpen(true)} className="gap-2">
              <LogIn className="h-4 w-4" /> Zaloguj
            </Button>
          </CardContent>
        </Card>
        <AuthDialog open={authOpen} onOpenChange={setAuthOpen} />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-3 py-6 sm:px-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Moje typy</h1>
          <p className="text-muted-foreground mt-1">
            Zapisuj swoje typy i sprawdzaj, jak wychodzą w czasie.
          </p>
        </div>

        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="h-4 w-4 mr-2" /> Dodaj typ
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Nowy typ</DialogTitle>
            </DialogHeader>
            <div className="grid gap-4 py-2">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>Gospodarz</Label>
                  <Input
                    placeholder="e.g. Barcelona"
                    value={homeTeam}
                    onChange={(e) => setHomeTeam(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Gość</Label>
                  <Input
                    placeholder="e.g. Real Madrid"
                    value={awayTeam}
                    onChange={(e) => setAwayTeam(e.target.value)}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>Data zdarzenia</Label>
                  <Input
                    type="date"
                    value={matchDate}
                    onChange={(e) => setMatchDate(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Typ</Label>
                  <Select value={pick} onValueChange={(v) => setPick(v as '1' | 'X' | '2')}>
                    <SelectTrigger>
                      <SelectValue placeholder="Wybierz wynik" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="1">1 — gospodarz</SelectItem>
                      <SelectItem value="X">X — remis</SelectItem>
                      <SelectItem value="2">2 — gość</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>Kurs</Label>
                  <Input
                    type="number"
                    step="0.01"
                    placeholder="2.10"
                    value={odds}
                    onChange={(e) => setOdds(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Stawka</Label>
                  <Input
                    type="number"
                    step="0.01"
                    placeholder="10.00"
                    value={stake}
                    onChange={(e) => setStake(e.target.value)}
                  />
                </div>
              </div>
            </div>
            <Button
              className="w-full"
              onClick={addBet}
              disabled={!homeTeam || !awayTeam || !pick || createBet.isPending}
            >
              {createBet.isPending ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              Zapisz typ
            </Button>
            {createBet.isError && (
              <p className="text-xs text-destructive text-center mt-1">
                {(createBet.error as Error)?.message ?? 'Nie udało się zapisać typu'}
              </p>
            )}
          </DialogContent>
        </Dialog>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">Wszystkie</CardTitle></CardHeader>
          <CardContent><span className="text-2xl font-bold">{total}</span></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">Trafione</CardTitle></CardHeader>
          <CardContent><span className="text-2xl font-bold text-emerald-500">{won}</span></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">Nietrafione</CardTitle></CardHeader>
          <CardContent><span className="text-2xl font-bold text-red-500">{lost}</span></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">W toku</CardTitle></CardHeader>
          <CardContent><span className="text-2xl font-bold text-muted-foreground">{pending}</span></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">Skuteczność</CardTitle></CardHeader>
          <CardContent className="space-y-1">
            <span className={cn('text-2xl font-bold tabular-nums', winRate >= 50 ? 'text-emerald-500' : 'text-red-500')}>
              {winRate > 0 ? `${winRate.toFixed(0)}%` : '—'}
            </span>
            <Progress value={winRate} className="h-1.5" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">Zysk / strata</CardTitle></CardHeader>
          <CardContent>
            <span className={cn('text-2xl font-bold tabular-nums', profit >= 0 ? 'text-emerald-500' : 'text-red-500')}>
              {profit >= 0 ? '+' : ''}{profit.toFixed(2)}
            </span>
            {roi !== 0 && (
              <p className="text-[10px] text-muted-foreground mt-0.5">ROI: {roi > 0 ? '+' : ''}{roi.toFixed(1)}%</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Error state */}
      {isError && (
        <div className="flex items-center gap-3 rounded-xl border border-destructive/50 bg-destructive/10 p-4">
          <AlertCircle className="h-5 w-5 text-destructive shrink-0" />
          <div>
            <p className="text-sm font-medium text-destructive">Nie udało się pobrać typów</p>
            <p className="text-xs text-muted-foreground">{(error as Error)?.message ?? 'Serwer nie odpowiada'}</p>
          </div>
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {/* Bet list */}
      {!isLoading && (
        <div className="space-y-3">
          {bets.length === 0 && !isError && (
            <Card className="border-dashed">
              <CardContent className="py-16 text-center space-y-3">
                <div className="rounded-full bg-muted p-3 w-fit mx-auto">
                  <Target className="h-6 w-6 text-muted-foreground" />
                </div>
                <p className="text-muted-foreground">Nie zapisano jeszcze żadnego typu. Kliknij &quot;Dodaj typ&quot;, aby zacząć.</p>
              </CardContent>
            </Card>
          )}
          {bets.map((bet: ApiBet) => (
            <Card key={bet.id} className="flex items-center gap-4 p-4 hover:bg-muted/30 transition-colors">
              {/* Result icon */}
              <div className={cn(
                'shrink-0 rounded-full p-2',
                bet.status === 'won' && 'bg-emerald-500/10',
                bet.status === 'lost' && 'bg-red-500/10',
                bet.status === 'pending' && 'bg-muted',
                bet.status === 'void' && 'bg-yellow-500/10',
              )}>
                {bet.status === 'won' && <TrendingUp className="h-4 w-4 text-emerald-500" />}
                {bet.status === 'lost' && <TrendingDown className="h-4 w-4 text-red-500" />}
                {bet.status === 'pending' && <Minus className="h-4 w-4 text-muted-foreground" />}
                {bet.status === 'void' && <Minus className="h-4 w-4 text-yellow-500" />}
              </div>

              {/* Details */}
              <div className="flex-1 min-w-0">
                <p className="font-medium text-sm truncate">{bet.home_team} vs {bet.away_team}</p>
                <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                  <Badge variant="outline" className="text-[10px] py-0 h-5 font-mono">{bet.bet_selection}</Badge>
                  {bet.odds_at_bet != null && (
                    <span className="text-[10px] text-muted-foreground">@ <span className="font-mono">{bet.odds_at_bet}</span></span>
                  )}
                  {bet.stake != null && (
                    <span className="text-[10px] text-muted-foreground">Stawka: <span className="font-mono">{bet.stake}</span></span>
                  )}
                  {bet.match_date && (
                    <span className="text-[10px] text-muted-foreground/60">{bet.match_date}</span>
                  )}
                </div>
              </div>

              {/* Status badge */}
              <Badge className={cn(
                'shrink-0',
                bet.status === 'won' && 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30',
                bet.status === 'lost' && 'bg-red-500/10 text-red-600 border-red-500/30',
                bet.status === 'pending' && 'bg-muted text-muted-foreground',
                bet.status === 'void' && 'bg-yellow-500/10 text-yellow-600 border-yellow-500/30',
              )} variant="outline">
                {BET_STATUS_LABELS[bet.status] ?? bet.status}
              </Badge>

              {/* Delete */}
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={() => removeBet(bet.id)}
                disabled={deleteBetMut.isPending}
              >
                <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
              </Button>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
