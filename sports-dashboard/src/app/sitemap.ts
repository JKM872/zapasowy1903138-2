import type { MetadataRoute } from 'next'

// Required for `output: 'export'`: generated once at build time as out/sitemap.xml
export const dynamic = 'force-static'

const BASE = 'https://pickly-dashboard.vercel.app'

const ROUTES: { path: string; freq: 'hourly' | 'daily' | 'monthly'; priority: number }[] = [
  { path: '/', freq: 'hourly', priority: 1 },
  { path: '/top', freq: 'hourly', priority: 0.9 },
  { path: '/pricing', freq: 'monthly', priority: 0.9 },
  { path: '/stats', freq: 'daily', priority: 0.7 },
  { path: '/leaderboard', freq: 'daily', priority: 0.6 },
  { path: '/dropping-odds', freq: 'hourly', priority: 0.6 },
  { path: '/standings', freq: 'daily', priority: 0.5 },
  { path: '/team', freq: 'daily', priority: 0.4 },
  { path: '/how-to-use', freq: 'monthly', priority: 0.4 },
  { path: '/terms', freq: 'monthly', priority: 0.2 },
  { path: '/privacy', freq: 'monthly', priority: 0.2 },
  { path: '/responsible-gambling', freq: 'monthly', priority: 0.2 },
]

export default function sitemap(): MetadataRoute.Sitemap {
  return ROUTES.map((r) => ({
    url: `${BASE}${r.path}`,
    changeFrequency: r.freq,
    priority: r.priority,
  }))
}
