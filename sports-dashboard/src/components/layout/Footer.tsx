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
          <strong className="text-foreground">Pickly</strong> is an analytics
          tool. We are not a bookmaker: we do not accept bets, settle wagers or pay
          out winnings. Odds shown come from third parties and are for information
          only. Probabilities and expected value are model estimates, not a
          guarantee of any result.
        </p>
        <p className="leading-relaxed">
          For users aged 18+ only. Gambling involves the risk of losing money and
          can be addictive. Please gamble responsibly.
        </p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-1">
          <Link href="/pricing" className="transition-colors hover:text-foreground">
            Pricing
          </Link>
          <Link href="/terms" className="transition-colors hover:text-foreground">
            Terms
          </Link>
          <Link href="/privacy" className="transition-colors hover:text-foreground">
            Privacy
          </Link>
          <Link href="/responsible-gambling" className="transition-colors hover:text-foreground">
            Responsible gambling
          </Link>
          <a
            href="https://github.com/JKM872/zapasowy1903138-2"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 transition-colors hover:text-foreground"
          >
            <Github className="h-3.5 w-3.5" />
            Source code
          </a>
        </div>
      </div>
    </footer>
  )
}
