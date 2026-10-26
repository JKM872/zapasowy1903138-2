import type { Metadata } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import './globals.css'
import { Providers } from '@/components/providers'
import { Header } from '@/components/layout/Header'
import { Footer } from '@/components/layout/Footer'
import { Toaster } from '@/components/ui/sonner'

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
})

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
})



const SITE_URL = 'https://pickly-dashboard.vercel.app'
const SITE_TITLE = 'Pickly — sports picks with public results'
const SITE_DESCRIPTION =
  'Analytics for sports events: odds, probabilities, expected value and team form. We do not accept bets.'

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: SITE_TITLE,
  description: SITE_DESCRIPTION,
  applicationName: 'Pickly',
  keywords: ['analytics', 'sports', 'odds', 'probability', 'expected value', 'stats'],
  openGraph: {
    type: 'website',
    siteName: 'Pickly',
    url: SITE_URL,
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    locale: 'en_GB',
  },
  twitter: { card: 'summary', title: SITE_TITLE, description: SITE_DESCRIPTION },
  robots: { index: true, follow: true },
}

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
        suppressHydrationWarning
      >
        <Providers>
          <div className="relative flex min-h-screen flex-col">
            <Header />
            <main className="flex-1">{children}</main>
            <Footer />
          </div>
          <Toaster richColors position="bottom-right" />
        </Providers>
      </body>
    </html>
  )
}
