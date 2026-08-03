import type { Metadata } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import { MATERIAL_SYMBOLS_HREF } from '@/lib/constants'
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



export const metadata: Metadata = {
  title: 'Analiza zdarzeń sportowych',
  description:
    'Narzędzie analityczne dla zdarzeń sportowych: kursy, prawdopodobieństwa, wartość oczekiwana i forma drużyn. Nie przyjmujemy zakładów.',
  keywords: ['analiza', 'sport', 'kursy', 'prawdopodobieństwo', 'wartość oczekiwana', 'statystyki'],
}

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pl" suppressHydrationWarning>
      <head>
        {/* Material Symbols is an icon font, so it is not available through
            next/font/google. Requesting it by icon_names ships only the glyphs
            the sport registry actually uses instead of the ~3 MB full set. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="stylesheet" href={MATERIAL_SYMBOLS_HREF} />
      </head>
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
