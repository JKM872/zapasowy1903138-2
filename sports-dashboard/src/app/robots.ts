import type { MetadataRoute } from 'next'

// Required for `output: 'export'`: generated once at build time as out/robots.txt
export const dynamic = 'force-static'

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: '*', allow: '/', disallow: ['/my-bets'] },
    sitemap: 'https://pickly-dashboard.vercel.app/sitemap.xml',
  }
}
