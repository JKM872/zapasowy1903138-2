'use client'

import { useEffect, useState, type FormEvent } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { History, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SPORTS, getSportConfig } from '@/lib/constants'
import { teamHref } from '@/lib/api'
import { TeamHistoryCard } from '@/components/match/TeamHistoryPanel'

export function TeamView() {
  const params = useSearchParams()
  const router = useRouter()
  const name = (params.get('name') ?? '').trim()
  const sport = (params.get('sport') ?? 'football').trim() || 'football'
  const [draftName, setDraftName] = useState(name)
  const [draftSport, setDraftSport] = useState(sport)

  useEffect(() => { setDraftName(name); setDraftSport(sport) }, [name, sport])

  function submit(e: FormEvent) {
    e.preventDefault()
    const n = draftName.trim()
    if (n) router.push(teamHref(n, draftSport))
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-3 py-6 sm:px-4">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
          <History className="h-6 w-6 text-primary" />
          Team history
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Last results, form, home and away record and our Top Picks record, from our stored match results
          (last 400 days).
        </p>
      </div>

      <form onSubmit={submit} className="flex flex-wrap items-end gap-2" role="search" aria-label="Find a team">
        <div className="min-w-[12rem] flex-1">
          <label htmlFor="team-name" className="mb-1 block text-xs text-muted-foreground">Team or player</label>
          <Input
            id="team-name"
            value={draftName}
            maxLength={80}
            onChange={e => setDraftName(e.target.value)}
            placeholder="e.g. Legia Warszawa or Djokovic N."
          />
        </div>
        <div>
          <label htmlFor="team-sport" className="mb-1 block text-xs text-muted-foreground">Sport</label>
          <select
            id="team-sport"
            value={draftSport}
            onChange={e => setDraftSport(e.target.value)}
            className="h-9 rounded-md border bg-background px-2 text-sm"
          >
            {SPORTS.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
        <Button type="submit" size="sm" className="h-9">
          <Search className="mr-1.5 h-4 w-4" /> Show history
        </Button>
      </form>

      {name ? (
        <>
          <p className="text-xs text-muted-foreground">{getSportConfig(sport).name}</p>
          <TeamHistoryCard key={`${sport}|${name}`} name={name} sport={sport} limit={30} />
          <p className="text-xs text-muted-foreground">
            Past results do not predict future results. Scores are shown with this team first.
          </p>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          Enter a team or player, or open a team from a match or from Top Picks.
        </p>
      )}
    </div>
  )
}
