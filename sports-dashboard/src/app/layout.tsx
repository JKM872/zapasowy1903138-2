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
