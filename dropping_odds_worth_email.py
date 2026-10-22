#!/usr/bin/env python3
"""Mail only the price moves whose segment has historically made money.

Runs after each dropping-odds window (three a day). The existing dropping-odds
mail lists every move; most of them sit in segments that lost money on settled
history (football alone lost 8-9%). This one carries just the moves the advisor
marks "warto", each with the evidence the verdict rests on.

Two rules keep it from becoming noise:

* nothing new, nothing sent — an empty mail three times a day would teach the
  reader to ignore it;
* every event is mailed once. A ledger per day records what went out, so the
  15:00 run does not repeat what 12:00 already sent.

Usage::

    python dropping_odds_worth_email.py --dry-run           # print, send nothing
    python dropping_odds_worth_email.py --to a@b --from-email c@d --password ...
"""
from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Iterable, List, Optional, Set

OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
SITE_URL = "https://pickly-dashboard.vercel.app/dropping-odds"

SPORT_PL = {
    "football": "Piłka nożna", "tennis": "Tenis", "basketball": "Koszykówka",
    "hockey": "Hokej", "handball": "Piłka ręczna", "volleyball": "Siatkówka",
    "baseball": "Baseball", "rugby": "Rugby", "esports": "E-sport",
}
OUTCOME_PL = {"1": "gospodarz", "X": "remis", "2": "gość"}


def event_key(event: Dict[str, Any]) -> str:
    return f"{event.get('matchId')}|{event.get('outcome')}"


def ledger_path(date: str, outputs_dir: str = OUTPUTS_DIR) -> str:
    return os.path.join(outputs_dir, f"dropping_worth_sent_{date}.json")


def load_ledger(path: str) -> Set[str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return set()
    return set(data.get("sent", [])) if isinstance(data, dict) else set()


def save_ledger(path: str, keys: Iterable[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"sent": sorted(set(keys)),
                   "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                  fh, ensure_ascii=False, indent=2)


def select_new_worth(events: Iterable[Dict[str, Any]], sent: Set[str]) -> List[Dict[str, Any]]:
    """Events with a "warto" verdict that have not been mailed yet. Pure."""
    out = [e for e in events
           if (e.get("verdict") or {}).get("verdict") == "warto"
           and event_key(e) not in sent]
    # Strongest evidence first: realistic ROI, then sample size.
    out.sort(key=lambda e: (-((e["verdict"].get("roiRealistic")) or 0),
                            -((e["verdict"].get("n")) or 0)))
    return out


def _fmt_odds(value: Optional[float]) -> str:
    return f"{value:.2f}" if isinstance(value, (int, float)) else "—"


def build_html(events: List[Dict[str, Any]], date: str,
               model: Optional[Dict[str, Any]]) -> str:
    rows = []
    for e in events:
        v = e["verdict"]
        esc = html.escape
        rows.append(f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee">
            <div style="font-weight:600">{esc(e.get('homeTeam',''))} vs {esc(e.get('awayTeam',''))}</div>
            <div style="font-size:12px;color:#666">{esc(SPORT_PL.get(e.get('sport'), e.get('sport','')))}
              · {esc(e.get('league',''))} · {esc(e.get('eventTime',''))}</div>
          </td>
          <td style="padding:8px;border-bottom:1px solid #eee;white-space:nowrap">
            {esc(OUTCOME_PL.get(str(e.get('outcome')), str(e.get('outcome'))))}<br>
            <span style="font-size:12px;color:#666">{_fmt_odds(e.get('openOdds'))} → <b>{_fmt_odds(e.get('currentOdds'))}</b>
              ({(e.get('dropPct') or 0):.0f}%)</span>
          </td>
          <td style="padding:8px;border-bottom:1px solid #eee;font-size:12px;white-space:nowrap">
            {v.get('n')} ruchów<br>trafność {v.get('hitRate')}%<br>
            <b style="color:#1b8a3c">ROI {v.get('roiRealistic'):+}%</b>
          </td>
        </tr>""")

    basis = ""
    if model and model.get("settled"):
        rng = model.get("dateRange") or {}
        basis = (f"na podstawie {model['settled']} rozstrzygniętych spadków"
                 f" ({rng.get('from','?')} – {rng.get('to','?')})")

    return f"""<!doctype html><html><body style="font-family:Arial,sans-serif;color:#222">
  <h2 style="margin-bottom:4px">Spadki kursów, które historycznie zarabiały — {html.escape(date)}</h2>
  <p style="font-size:13px;color:#555;margin-top:0">
    {len(events)} nowych zdarzeń w segmentach (dyscyplina i strona), które zarabiały w obu
    połowach okresu i po obniżeniu kursu o 5%, {basis}.
  </p>
  <table style="border-collapse:collapse;width:100%;font-size:14px">
    <tr style="text-align:left;background:#f5f5f5">
      <th style="padding:8px">Zdarzenie</th><th style="padding:8px">Spadek</th><th style="padding:8px">Historia segmentu</th>
    </tr>
    {''.join(rows)}
  </table>
  <p style="font-size:12px;color:#777;margin-top:16px">
    To historia, nie gwarancja. Nie wiemy, dlaczego kurs spadł. ROI liczone jest po kursie
    obniżonym o 5%, bo realnie łapie się gorszą cenę niż w chwili odczytu.
    Pełna lista: <a href="{SITE_URL}">{SITE_URL}</a>.
    Serwis analityczny, nie przyjmujemy zakładów. 18+.
  </p>
</body></html>"""


def send(html_body: str, subject: str, to: str, sender: str, password: str,
         provider: str = "gmail") -> None:
    from dropping_odds_email import SMTP_CONFIG
    cfg = SMTP_CONFIG.get(provider, SMTP_CONFIG["gmail"])
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    server = smtplib.SMTP(cfg["server"], cfg["port"], timeout=30)
    try:
        if cfg.get("use_tls"):
            server.starttls()
        server.login(sender, password)
        server.sendmail(sender, [a.strip() for a in to.split(",") if a.strip()], msg.as_string())
    finally:
        server.quit()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", help="YYYY-MM-DD (domyslnie najnowszy dzien z danymi)")
    ap.add_argument("--to")
    ap.add_argument("--from-email")
    ap.add_argument("--password")
    ap.add_argument("--provider", default="gmail")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from dropping_odds_feed import load_dropping_odds
    data = load_dropping_odds(date=args.date)
    date = data.get("date")
    if not date:
        print("Brak danych dropping odds — nic do wyslania.")
        return 0

    path = ledger_path(date)
    sent = load_ledger(path)
    fresh = select_new_worth(data["events"], sent)
    print(f"{date}: zdarzen {len(data['events'])}, 'warto' nowych {len(fresh)}, "
          f"juz wyslanych {len(sent)}")
    if not fresh:
        print("Nic nowego — mail nie zostaje wyslany.")
        return 0

    subject = f"Spadki kursów, które zarabiały: {len(fresh)} nowych — {date}"
    body = build_html(fresh, date, data.get("model"))
    if args.dry_run:
        for e in fresh:
            v = e["verdict"]
            print(f"  {e['sport']:10} {e['homeTeam']} vs {e['awayTeam']}  "
                  f"n={v['n']} roi_real={v['roiRealistic']}")
        return 0

    if not (args.to and args.from_email and args.password):
        print("Brak danych pocztowych (--to/--from-email/--password).", file=sys.stderr)
        return 1
    send(body, subject, args.to, args.from_email, args.password, args.provider)
    # Recorded only after a successful send, so a failed send is retried next run.
    save_ledger(path, sent | {event_key(e) for e in fresh})
    print(f"Wyslano {len(fresh)} zdarzen do {args.to}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
