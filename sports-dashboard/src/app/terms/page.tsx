import type { Metadata } from 'next'
import Link from 'next/link'
import { LegalPage } from '@/components/layout/LegalPage'

export const metadata: Metadata = {
  title: 'Terms of Service — Pickly',
  description: 'Terms of Service for Pickly, a sports analytics subscription. 18+ only. Analyses, not guarantees.',
  alternates: { canonical: '/terms' },
  openGraph: { url: '/terms', title: 'Terms of Service — Pickly', description: 'Terms of Service for Pickly, a sports analytics subscription. 18+ only. Analyses, not guarantees.', siteName: 'Pickly', type: 'website' },
}

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Service" updated="26 October 2026">
      <h2>1. Who we are</h2>
      <p>
        Pickly (&quot;we&quot;, &quot;us&quot;) is operated by [Company name / legal form], [registered
        address], [company registration / VAT number]. Contact: [contact e-mail].
      </p>

      <h2>2. What Pickly is – and is not</h2>
      <p>
        Pickly is an <strong>analytics and information service</strong> about sports events. We publish
        statistics, model probabilities, expected value estimates and our own picks.
      </p>
      <ul>
        <li>We are <strong>not a bookmaker</strong>. We do not accept bets, hold stakes, settle wagers or pay out winnings.</li>
        <li>Everything we publish is an <strong>analysis, not a guarantee</strong>. Past results do not predict future results and you can lose money by following any pick.</li>
        <li>Odds shown come from third parties, may be delayed or wrong and are for information only.</li>
        <li>Nothing on Pickly is financial, investment or betting advice. You alone decide whether to place a bet, where and for how much.</li>
      </ul>

      <h2>3. Age and eligibility</h2>
      <p>
        You must be <strong>at least 18 years old</strong> (or the higher legal gambling age in your country) to
        create an account or subscribe. You are responsible for checking that sports betting is legal where you
        live and for using only licensed operators.
      </p>

      <h2>4. Account</h2>
      <p>
        You can sign up with e-mail and password or with Google. Keep your login details secret; you are
        responsible for activity on your account. We may suspend accounts used for abuse, scraping, sharing paid
        content or breaking these terms.
      </p>

      <h2>5. Premium subscription</h2>
      <ul>
        <li>Premium is a <strong>weekly subscription</strong> at the price shown on the <Link href="/pricing">Pricing</Link> page at checkout. It renews automatically every week until you cancel.</li>
        <li>Payments are processed by <strong>Stripe</strong>. We never see or store your full card number.</li>
        <li>You can <strong>cancel at any time</strong> in the billing portal (Pricing page → Manage or cancel subscription). Cancellation stops the next renewal; you keep access until the end of the paid week.</li>
        <li>
          Premium is digital content supplied immediately. If you are an EU/EEA consumer, by starting the
          subscription you request immediate access and acknowledge that you lose the 14-day right of
          withdrawal for the period already started, to the extent permitted by law. This does not affect your
          other statutory rights.
        </li>
        <li>We may change the price for future periods; we will tell you before the change takes effect and you can cancel.</li>
      </ul>

      <h2>6. Acceptable use</h2>
      <p>
        Paid content is for your personal use. Do not resell, republish or automatically scrape it.
      </p>

      <h2>7. Availability and liability</h2>
      <p>
        The service is provided &quot;as is&quot;. Data may be incomplete, late or wrong, and the service may be
        unavailable at times. To the extent permitted by law we are not liable for betting losses or for
        decisions you make based on our content. Nothing in these terms limits liability that cannot be limited
        by law, including your rights as a consumer.
      </p>

      <h2>8. Privacy</h2>
      <p>
        How we handle personal data is described in our <Link href="/privacy">Privacy Policy</Link>.
      </p>

      <h2>9. Changes and law</h2>
      <p>
        We may update these terms; the date above shows the latest version. These terms are governed by the law
        of [country of the operator], without removing the protection given to consumers by the law of their
        country of residence. EU consumers may also use the EU Online Dispute Resolution platform.
      </p>

      <h2>10. Contact</h2>
      <p>Questions about these terms: [contact e-mail].</p>
    </LegalPage>
  )
}
