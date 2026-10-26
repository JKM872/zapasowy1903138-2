import type { Metadata } from 'next'
import { LegalPage } from '@/components/layout/LegalPage'

export const metadata: Metadata = {
  title: 'Privacy Policy — Pickly',
  description: 'How Pickly processes personal data under the GDPR: account, payments, storage in your browser.',
  alternates: { canonical: '/privacy' },
  openGraph: { url: '/privacy', title: 'Privacy Policy — Pickly', description: 'How Pickly processes personal data under the GDPR: account, payments, storage in your browser.', siteName: 'Pickly', type: 'website' },
}

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy" updated="26 October 2026">
      <h2>1. Controller</h2>
      <p>
        The controller of your personal data is [Company name / legal form], [registered address]. Contact for
        all privacy matters: [contact e-mail].
      </p>

      <h2>2. What data we process and why</h2>
      <ul>
        <li>
          <strong>Account (Supabase)</strong> – e-mail address, hashed password or Google account identifier,
          name and profile picture provided by Google if you sign in with Google, account creation and login
          times. Purpose: creating and running your account. Legal basis: performance of a contract (Art. 6(1)(b)
          GDPR).
        </li>
        <li>
          <strong>Your saved picks and settings</strong> – picks you save in &quot;My bets&quot; and your preferences.
          Purpose: providing the feature. Basis: contract.
        </li>
        <li>
          <strong>Payments (Stripe)</strong> – Stripe customer ID, subscription status and period, and the e-mail
          used at checkout. Card details are entered on Stripe&apos;s page and handled by Stripe; we never receive
          your full card number. Purpose: billing and access to Premium. Basis: contract and legal obligations
          for accounting (Art. 6(1)(c)).
        </li>
        <li>
          <strong>Technical logs</strong> – our hosting providers record IP address, browser and request data in
          server logs for security and troubleshooting. Basis: legitimate interest (Art. 6(1)(f)).
        </li>
      </ul>
      <p>
        We do <strong>not</strong> use advertising trackers, analytics cookies or profiling for marketing, and we
        do not sell your data.
      </p>

      <h2>3. Cookies and browser storage</h2>
      <p>
        We only use storage that is strictly necessary for the service: the login session kept by Supabase in your
        browser&apos;s local storage, and a local cache of team logos. Stripe sets its own cookies on its checkout
        page for fraud prevention. Because no non-essential cookies are used, we do not show a consent banner. If
        we ever add analytics or marketing tools we will ask for your consent first.
      </p>

      <h2>4. Processors and transfers</h2>
      <ul>
        <li>Supabase (authentication and database)</li>
        <li>Stripe (payments)</li>
        <li>Vercel (website hosting) and Heroku / Salesforce (API hosting)</li>
        <li>Google (only if you choose &quot;Continue with Google&quot;)</li>
      </ul>
      <p>
        Some of these providers process data outside the EU/EEA, e.g. in the United States. Such transfers rely on
        the EU–US Data Privacy Framework or the European Commission&apos;s Standard Contractual Clauses.
      </p>
      <p>
        Match pages may embed widgets from SofaScore. When those widgets load, SofaScore receives your IP address
        and browser data under its own privacy policy.
      </p>

      <h2>5. How long we keep data</h2>
      <p>
        Account data: while your account exists, and deleted within 30 days after you ask us to delete it. Payment
        records: as long as tax and accounting law requires (typically 5–10 years). Server logs: a short period
        set by the hosting providers.
      </p>

      <h2>6. Your rights (GDPR)</h2>
      <p>
        You have the right to access, rectify, erase and port your data, to restrict or object to processing, and
        to withdraw consent at any time. To use them, e-mail [contact e-mail] from the address on your account.
        We reply within one month. You may also complain to your data protection authority – in Poland the
        President of the Personal Data Protection Office (UODO, uodo.gov.pl).
      </p>

      <h2>7. Children</h2>
      <p>Pickly is for adults aged 18+. We do not knowingly process data of minors.</p>

      <h2>8. Changes</h2>
      <p>We will update this page if our processing changes; the date above shows the latest version.</p>
    </LegalPage>
  )
}
