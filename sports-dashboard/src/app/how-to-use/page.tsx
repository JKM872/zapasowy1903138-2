import type { Metadata } from 'next'
import Link from 'next/link'
import { LegalPage } from '@/components/layout/LegalPage'
import { RiskDisclaimer } from '@/components/top/RiskDisclaimer'
import { DrawdownNote } from '@/components/top/BankrollChart'

const TITLE = 'How to use our picks & responsible gambling — Pickly'
const DESCRIPTION =
  'What a Pickly pick is, how to size stakes (1–2% of bankroll), best price and the minimum price, withdrawn picks, closing line value, losing streaks and where to get help.'

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: '/how-to-use' },
  openGraph: { url: '/how-to-use', title: TITLE, description: DESCRIPTION, siteName: 'Pickly', type: 'website' },
}

export default function HowToUsePage() {
  return (
    <LegalPage title="How to use our picks & responsible gambling" updated="27 October 2026">
      <RiskDisclaimer className="mt-4" />

      <h2 id="what-a-pick-is">What a pick is</h2>
      <p>
        A pick is the result of a statistical analysis: form, head-to-head, model probabilities, market prices and
        line-up news. It is our estimate that a selection is priced better than its real chance. It is not a tip
        guarantee and not financial advice. Good picks lose often; the edge only shows over many bets.
      </p>

      <h2 id="grades">Grades and segments</h2>
      <p>
        Every pick has a grade (A, B or C) from the strength of its signals. We also track results by segment –
        sport, odds range and home/away – and stop publishing segments that lose money over a meaningful sample.
        The full public record is on <Link href="/top">Top Picks</Link>.
      </p>

      <h2 id="stake">Stake: 1–2% of your bankroll</h2>
      <p>
        Decide on a bankroll – money set aside for betting that you can afford to lose – and stake a small, fixed
        share of it on each pick. Every pick shows a suggested stake: <strong>1% of bankroll</strong> by default and
        up to <strong>2%</strong> for grade A picks with a clear calculated edge (a cautious quarter-Kelly rule).
      </p>
      <ul>
        <li>Bankroll 1 000 $/€: a 1.0% pick is a 10 $/€ stake, a 1.4% pick 14 $/€, the maximum 2.0% is 20 $/€.</li>
        <li>After a losing run the bankroll is smaller, so the same percentage means a smaller stake – this protects you.</li>
        <li>Never raise stakes to win back losses.</li>
      </ul>
      <p>
        Why so small? With 1–2% stakes a run of ten losses costs roughly 10–20% of the bankroll, not all of it, so
        you are still there when the results turn.
      </p>

      <h2 id="best-price">Best price and &quot;Don&apos;t bet below&quot;</h2>
      <p>
        Prices differ between bookmakers. Where we can, each pick shows the <strong>best price</strong> we found and
        its source. Taking 1.85 instead of 1.75 adds several points of ROI over time. Some picks also show
        <strong> Don&apos;t bet below Y.YY</strong>: under that price the pick is no longer profitable by our
        numbers – skip it rather than take a worse price.
      </p>

      <h2 id="withdrawn">Withdrawn picks</h2>
      <p>
        Before kick-off we re-check line-ups and prices. If a key player is out or the price falls below the
        minimum, the pick is <strong>withdrawn</strong>. Withdrawn picks are listed publicly with the reason and are
        not counted in the record or the bankroll. If you already placed the bet, it is your decision – we simply
        would not place it at that point.
      </p>
      <p>
        Cards show &quot;Line-ups checked N min before kick-off&quot; when that check ran, or &quot;Line-ups
        unverified&quot; when no recent line-up data was available (common for late-night games).
      </p>

      <h2 id="clv">Closing line value (CLV)</h2>
      <p>
        CLV compares the price when we published a pick with the price just before kick-off (the closing line, from
        Pinnacle where available). If the price drops after we publish, the market moved our way: CLV is positive.
        Beating the closing line regularly is the most reliable sign of real skill over 100+ picks, even during a
        losing run, because it does not depend on luck in single results. Our average CLV, the share of picks that
        beat the close and the sample size are on <Link href="/top">Top Picks</Link>.
      </p>

      <h2 id="losing-streaks">Expect losing streaks</h2>
      <p>
        Even at a 60% hit rate, runs of five or more losses in a row are normal over a few hundred picks. Plan for
        them before they happen.
      </p>
      <DrawdownNote />
      <p>
        Prices for hockey are counted as the 2-way price including overtime, so the record matches what you can
        actually bet.
      </p>

      <h2 id="responsible-gambling">Responsible gambling</h2>
      <ul>
        <li><strong>18+ only.</strong> Betting is entertainment with a real risk of losing money.</li>
        <li>Set deposit, loss and time limits with your bookmaker before you start.</li>
        <li>Never chase losses and never bet borrowed money.</li>
        <li>Take a break if betting affects your sleep, work, relationships or mood.</li>
      </ul>
      <p>Free, confidential help:</p>
      <ul>
        <li>
          <a href="https://www.begambleaware.org/" target="_blank" rel="noopener noreferrer">BeGambleAware.org</a>{' '}
          – information and support (UK).
        </li>
        <li>
          <a href="https://www.gamcare.org.uk/" target="_blank" rel="noopener noreferrer">GamCare</a> – National
          Gambling Helpline <a href="tel:08088020133">0808 8020 133</a>, 24/7 (UK).
        </li>
        <li>
          <a href="tel:18004262537">1-800-GAMBLER</a> – National Problem Gambling Helpline (USA), see{' '}
          <a href="https://www.ncpgambling.org/" target="_blank" rel="noopener noreferrer">ncpgambling.org</a>.
        </li>
        <li>
          <a href="https://anonimowihazardzisci.org/" target="_blank" rel="noopener noreferrer">Anonimowi Hazardziści</a>{' '}
          – Gamblers Anonymous groups in Poland.
        </li>
        <li>
          Other countries: <a href="https://findahelpline.com/" target="_blank" rel="noopener noreferrer">findahelpline.com</a>.
          More on our <Link href="/responsible-gambling">Responsible Gambling</Link> page.
        </li>
      </ul>

      <h2 id="disclaimer">Disclaimer</h2>
      <p>
        Pickly is an analytics service, not a bookmaker. We do not accept bets or pay out winnings. Odds come from
        third parties and may change. Past results do not predict future results. You alone decide whether and how
        much to bet.
      </p>

      <h2 id="credits">Image credits</h2>
      <p>
        Logos via <a href="https://www.thesportsdb.com" target="_blank" rel="noopener noreferrer">TheSportsDB</a>;
        photos via <a href="https://commons.wikimedia.org" target="_blank" rel="noopener noreferrer">Wikimedia Commons</a>{' '}
        under their licenses. The info icon on a photo shows its author and license and links to the file page.
        Trademarks belong to their owners. Where no free image exists we show the team&apos;s or player&apos;s initials.
      </p>
    </LegalPage>
  )
}
