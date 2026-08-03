import Link from 'next/link'
import { Github } from 'lucide-react'

/**
 * The layout deliberately mirrors a bookmaker, so the footer has to state
 * plainly that this is an analysis tool: no stakes are taken and no payouts are
 * made here.
 */
export function Footer() {
  return (
    <footer className="mt-6 border-t border-border bg-panel">
      <div className="mx-auto max-w-[1700px] space-y-3 px-2 py-5 text-xs text-muted-foreground sm:px-4">
        <p className="max-w-3xl leading-relaxed">
          <strong className="text-foreground">Analiza Sportowa</strong> to narzędzie
          analityczne. Nie jesteśmy bukmacherem: nie przyjmujemy zakładów, nie
          prowadzimy rozliczeń i nie wypłacamy wygranych. Prezentowane kursy pochodzą
          od podmiotów zewnętrznych i mają charakter informacyjny. Prawdopodobieństwa
          i wartość oczekiwana to szacunki modelu, nie gwarancja wyniku.
        </p>
        <p className="leading-relaxed">
          Serwis przeznaczony dla osób powyżej 18 lat. Gra hazardowa wiąże się z
          ryzykiem utraty pieniędzy i może prowadzić do uzależnienia.
        </p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-1">
          <Link href="/pricing" className="transition-colors hover:text-foreground">
            Cennik
          </Link>
          <a
            href="https://github.com/JKM872/zapasowy1903138-2"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 transition-colors hover:text-foreground"
          >
            <Github className="h-3.5 w-3.5" />
            Kod źródłowy
          </a>
        </div>
      </div>
    </footer>
  )
}
