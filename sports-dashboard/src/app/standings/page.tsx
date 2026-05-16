// ============================================================================
// Standings Page – league tables from Football-Data.org
// ============================================================================
'use client'

import { useState } from 'react'
import Image from 'next/image'
import { Loader2, Trophy } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { useStandings, useAvailableLeagues } from '@/hooks/useMatches'

function formToBadges(form: string) {
  if (!form) return null
  return form.split(',').map((r, i) => {
    const c =
      r === 'W' ? 'bg-emerald-500' :
      r === 'D' ? 'bg-amber-500' :
      r === 'L' ? 'bg-red-500' : 'bg-muted'
    return (
      <span key={i} className={cn('inline-block w-5 h-5 rounded-full text-white text-[10px] font-bold flex items-center justify-center', c)}>
        {r}
      </span>
    )
  })
}

export default function StandingsPage() {
  const [league, setLeague] = useState('PL')
  const { data: leaguesData } = useAvailableLeagues()
  const { data, isLoading, isError, error } = useStandings(league)

  const leagues = leaguesData?.leagues ?? []

  return (
    <div className="container py-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Standings</h1>
          <p className="text-muted-foreground mt-1">
            Live league tables powered by Football-Data.org.
          </p>
        </div>

        {leagues.length > 0 && (
          <Select value={league} onValueChange={setLeague}>
            <SelectTrigger className="w-[220px]">
              <SelectValue placeholder="Select league" />
            </SelectTrigger>
            <SelectContent>
              {leagues.map((l) => (
                <SelectItem key={l.code} value={l.code}>{l.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {isError && (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardContent className="py-8 text-center">
            <p className="text-sm text-destructive">
              {(error as Error)?.message?.includes('503')
                ? 'Set FOOTBALL_DATA_API_KEY environment variable on Heroku to enable standings.'
                : (error as Error)?.message ?? 'Failed to load standings'}
            </p>
          </CardContent>
        </Card>
      )}

      {data && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Trophy className="h-5 w-5 text-primary" />
              {data.league}
            </CardTitle>
            {data.season && (
              <CardDescription>Season {data.season}</CardDescription>
            )}
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/30">
                    <th className="text-left py-2.5 px-3 w-8">#</th>
                    <th className="text-left py-2.5 px-3">Team</th>
                    <th className="text-center py-2.5 px-2 w-10">P</th>
                    <th className="text-center py-2.5 px-2 w-10">W</th>
                    <th className="text-center py-2.5 px-2 w-10">D</th>
                    <th className="text-center py-2.5 px-2 w-10">L</th>
                    <th className="text-center py-2.5 px-2 w-12 hidden sm:table-cell">GF</th>
                    <th className="text-center py-2.5 px-2 w-12 hidden sm:table-cell">GA</th>
                    <th className="text-center py-2.5 px-2 w-12">GD</th>
                    <th className="text-center py-2.5 px-2 w-12 font-bold">Pts</th>
                    <th className="text-center py-2.5 px-2 hidden md:table-cell">Form</th>
                  </tr>
                </thead>
                <tbody>
                  {data.standings.map((row, i) => (
                    <tr
                      key={row.team}
                      className={cn(
                        'border-b border-border/40 hover:bg-muted/30 transition-colors',
                        i < 4 && 'border-l-2 border-l-emerald-500',
                        i >= data.standings.length - 3 && 'border-l-2 border-l-red-500',
                      )}
                    >
                      <td className="py-2 px-3 text-muted-foreground font-mono text-xs">{row.position}</td>
                      <td className="py-2 px-3">
                        <div className="flex items-center gap-2">
                          {row.teamCrest && (
                            <Image
                              src={row.teamCrest}
                              alt=""
                              width={20}
                              height={20}
                              className="h-5 w-5 object-contain"
                              unoptimized
                            />
                          )}
                          <span className="font-medium truncate max-w-[180px]">{row.team}</span>
                        </div>
                      </td>
                      <td className="text-center py-2 px-2 tabular-nums">{row.played}</td>
                      <td className="text-center py-2 px-2 tabular-nums text-emerald-600">{row.won}</td>
                      <td className="text-center py-2 px-2 tabular-nums text-muted-foreground">{row.draw}</td>
                      <td className="text-center py-2 px-2 tabular-nums text-red-500">{row.lost}</td>
                      <td className="text-center py-2 px-2 tabular-nums hidden sm:table-cell">{row.goalsFor}</td>
                      <td className="text-center py-2 px-2 tabular-nums hidden sm:table-cell">{row.goalsAgainst}</td>
                      <td className={cn(
                        'text-center py-2 px-2 tabular-nums font-medium',
                        row.goalDifference > 0 ? 'text-emerald-600' : row.goalDifference < 0 ? 'text-red-500' : '',
                      )}>
                        {row.goalDifference > 0 ? '+' : ''}{row.goalDifference}
                      </td>
                      <td className="text-center py-2 px-2 tabular-nums font-bold">{row.points}</td>
                      <td className="py-2 px-2 hidden md:table-cell">
                        <div className="flex items-center gap-0.5 justify-center">
                          {formToBadges(row.form)}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Legend */}
            <div className="flex items-center gap-4 text-[10px] text-muted-foreground px-4 py-2 border-t">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-emerald-500" /> Champions League
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-red-500" /> Relegation
              </span>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
