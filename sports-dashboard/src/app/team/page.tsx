import type { Metadata } from 'next'
import { Suspense } from 'react'
import { TeamView } from './TeamView'

const TITLE = 'Team history — Pickly'
const DESCRIPTION =
  'Last results, form, home and away record and our Top Picks record for any team or player, from our stored match results.'

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: '/team' },
  openGraph: { url: '/team', title: TITLE, description: DESCRIPTION, siteName: 'Pickly', type: 'website' },
}

// Static export cannot pre-render every team name, so ?sport=&name= is read in the browser.
export default function TeamPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-3xl px-3 py-6 text-sm text-muted-foreground">Loading…</div>}>
      <TeamView />
    </Suspense>
  )
}
