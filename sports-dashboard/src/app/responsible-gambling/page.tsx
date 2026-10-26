import type { Metadata } from 'next'
import { LegalPage } from '@/components/layout/LegalPage'

export const metadata: Metadata = {
  title: 'Responsible Gambling — Pickly',
  description: 'Pickly is for adults 18+. Our picks are analyses, not guarantees. Where to get help with gambling.',
  alternates: { canonical: '/responsible-gambling' },
  openGraph: { url: '/responsible-gambling', title: 'Responsible Gambling — Pickly', description: 'Pickly is for adults 18+. Our picks are analyses, not guarantees. Where to get help with gambling.', siteName: 'Pickly', type: 'website' },
}

export default function ResponsibleGamblingPage() {
  return (
    <LegalPage title="Responsible Gambling" updated="26 October 2026">
      <p className="mt-4">
        <strong>18+ only.</strong> Pickly publishes analyses, not guarantees. Even well-researched picks lose,
        sometimes many in a row. Never bet money you cannot afford to lose.
      </p>

      <h2>Keep it under control</h2>
      <ul>
        <li>Set a budget (bankroll) before you start and never top it up to chase losses.</li>
        <li>Use small, fixed stakes – for example 1–2% of your bankroll per pick.</li>
        <li>Set deposit, loss and time limits with your bookmaker; licensed operators must offer them.</li>
        <li>Do not bet when upset, under the influence or to solve money problems.</li>
        <li>Only use bookmakers licensed in your country.</li>
      </ul>

      <h2>Warning signs</h2>
      <ul>
        <li>You bet more than you planned or borrow money to bet.</li>
        <li>You chase losses or hide betting from people close to you.</li>
        <li>Betting affects your sleep, work, relationships or mood.</li>
      </ul>
      <p>If any of these sound familiar, take a break and talk to someone. Help is free and confidential.</p>

      <h2>Where to get help</h2>
      <ul>
        <li>
          <strong>United Kingdom</strong> – National Gambling Helpline (run by GamCare), free 24/7:{' '}
          <a href="tel:08088020133">0808 8020 133</a>, live chat at{' '}
          <a href="https://www.gamcare.org.uk/" target="_blank" rel="noopener noreferrer">gamcare.org.uk</a>.
          Information and support from{' '}
          <a href="https://www.gambleaware.org/" target="_blank" rel="noopener noreferrer">BeGambleAware</a>.
        </li>
        <li>
          <strong>Poland</strong> – Telefon Zaufania Uzależnienia Behawioralne (behavioural addictions incl.
          gambling): <a href="tel:801889880">801 889 880</a>. Current Polish helplines are listed at{' '}
          <a href="https://findahelpline.com/countries/pl/topics/gambling" target="_blank" rel="noopener noreferrer">
            findahelpline.com
          </a>.
        </li>
        <li>
          <strong>Other countries</strong> – find a free local helpline at{' '}
          <a href="https://findahelpline.com/" target="_blank" rel="noopener noreferrer">findahelpline.com</a>.
        </li>
        <li>
          <strong>Self-exclusion</strong> – ask your bookmaker to exclude you, and install a blocking tool such as{' '}
          <a href="https://gamban.com/" target="_blank" rel="noopener noreferrer">Gamban</a>.
        </li>
      </ul>

      <h2>Taking a break from Pickly</h2>
      <p>
        You can cancel Premium at any time from the Pricing page (Manage or cancel subscription). To have your account
        closed, e-mail [contact e-mail].
      </p>
    </LegalPage>
  )
}
