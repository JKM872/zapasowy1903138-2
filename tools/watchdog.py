#!/usr/bin/env python3
"""Strażnik — wykrywa „ciche” awarie runów (zielony status, śmieciowe wyniki).

Przegląda dzisiejsze runy głównych workflow przez `gh` (GH_TOKEN), parsuje logi
jobów, sonduje przekaźniki SOFASCORE_RELAY i — gdy są problemy — wysyła mail.
Zawsze zapisuje results/watchdog_<data>.json.

    python tools/watchdog.py [YYYY-MM-DD] [--email] [--repo owner/name]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent

WORKFLOWS = ['scrape_forebet.yml', 'scrape.yml', 'scrape_away.yml',
             'oddssafari_dropping.yml', 'top_picks.yml', 'daily_digest.yml']

# Minimalna liczba meczów z listingu Forebet per sport (poniżej => ALERT).
FOREBET_MIN = {'football': 200, 'basketball': 30, 'hockey': 30,
               'volleyball': 30, 'handball': 30, 'tennis': 20}
FOREBET_MIN_DEFAULT = 0
FANVOTE_MIN_MATCHES = 20      # Fan Vote 0% przy > tylu meczach => ALERT

ALERT, WARN = 'ALERT', 'WARN'

RE_TS = re.compile(r'^\S*\d{4}-\d\d-\d\dT[\d:.]+Z\s?')
RE_FOREBET = re.compile(r'Forebet (\w+) (\d{4}-\d\d-\d\d): (\d+) meczów \(HTML=')
RE_FV_SUMMARY = re.compile(r'Fan Vote: (\d+)/(\d+) z głosami')
RE_FV_FOUND = re.compile(r'Fan Vote: (\d+) found / (\d+) not_found')
RE_QUOTA = re.compile(r'Przekaźnik SofaScore|zbyt wiele razy|too many times|Service invoked', re.I)
RE_BLOCKED = re.compile(r'SofaScore zablokowany dla IP')
RE_BUDGET = re.compile(r'Czas wyczerpany')
RE_TRACEBACK = re.compile(r'Traceback \(most recent call last\)')

MEANING = {
    'forebet_low': ('Listing Forebet prawie pusty — zła data, Cloudflare lub zmiana HTML.',
                    'Sprawdź log forebet_listing / zrzut HTML; uruchom ponownie sport.'),
    'job_failed': ('Job zakończył się błędem — część danych nie powstała.',
                   'Otwórz log joba i napraw przyczynę; ewentualnie re-run.'),
    'traceback': ('W logu jest wyjątek Pythona (run mógł być zielony).',
                  'Zobacz Traceback w logu i popraw kod.'),
    'fanvote_zero': ('Brak Fan Vote dla całego runu — SofaScore/przekaźnik nie działa.',
                     'Sprawdź limity Apps Script (SOFASCORE_RELAY) i blokadę IP.'),
    'relay_quota': ('Przekaźnik Apps Script wyczerpał dzienny limit Google.',
                    'Dodaj kolejny przekaźnik z innego konta albo poczekaj do resetu.'),
    'sofa_blocked': ('SofaScore blokuje IP runnera (403).',
                     'Upewnij się, że SOFASCORE_RELAY jest ustawiony i działa.'),
    'budget': ('Wzbogacanie przerwane limitem czasu — część meczów bez danych.',
               'Rozważ węższy zakres lub dłuższy budżet czasu.'),
    'no_run': ('Workflow zaplanowany na dziś, a nie ma żadnego runu.',
               'Sprawdź, czy workflow nie jest wyłączony; uruchom ręcznie.'),
    'relay_dead': ('Sonda przekaźnika: limit wyczerpany / błąd.',
                   'Wymień lub odciąż ten przekaźnik.'),
}


def _issue(level: str, workflow: str, sport: str, code: str, problem: str,
           url: str = '') -> Dict[str, Any]:
    meaning, action = MEANING[code]
    return {'level': level, 'workflow': workflow, 'sport': sport, 'code': code,
            'problem': problem, 'meaning': meaning, 'action': action, 'url': url}


def gh(args: List[str]) -> str:
    """Wywołuje gh CLI i zwraca stdout (pusty string przy błędzie)."""
    try:
        p = subprocess.run(['gh', *args], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f'   ⚠️ gh {args[:2]}: {e}')
        return ''
    if p.returncode != 0:
        print(f'   ⚠️ gh {" ".join(args[:3])}: {p.stderr.strip()[:200]}')
        return ''
    return p.stdout


def parse_log(text: str, workflow: str, url: str = '') -> List[Dict[str, Any]]:
    """Zamienia log joba na listę problemów wg reguł."""
    issues: List[Dict[str, Any]] = []
    fv_found = fv_total = 0
    fv_seen = False
    quota = blocked = budget = tb = False
    for raw in text.splitlines():
        line = RE_TS.sub('', raw)
        m = RE_FOREBET.search(line)
        if m:
            sport, n = m.group(1), int(m.group(3))
            minimum = FOREBET_MIN.get(sport, FOREBET_MIN_DEFAULT)
            if n < minimum:
                issues.append(_issue(ALERT, workflow, sport, 'forebet_low',
                                     f'Forebet {sport}: {n} meczów (min {minimum})', url))
            continue
        m = RE_FV_SUMMARY.search(line)
        if m:
            fv_seen = True
            fv_found += int(m.group(1)); fv_total += int(m.group(2))
            continue
        m = RE_FV_FOUND.search(line)
        if m:
            fv_seen = True
            fv_found += int(m.group(1)); fv_total += int(m.group(1)) + int(m.group(2))
            continue
        if RE_QUOTA.search(line):
            quota = True
        if RE_BLOCKED.search(line):
            blocked = True
        if RE_BUDGET.search(line):
            budget = True
        if RE_TRACEBACK.search(line):
            tb = True
    if fv_seen and fv_found == 0 and fv_total > FANVOTE_MIN_MATCHES:
        issues.append(_issue(ALERT, workflow, '', 'fanvote_zero',
                             f'Fan Vote 0/{fv_total} meczów', url))
    if quota:
        issues.append(_issue(WARN, workflow, '', 'relay_quota',
                             'Przekaźnik SofaScore: dzienny limit wyczerpany', url))
    if blocked:
        issues.append(_issue(WARN, workflow, '', 'sofa_blocked',
                             'SofaScore zablokowany dla IP runnera', url))
    if budget:
        issues.append(_issue(WARN, workflow, '', 'budget',
                             'Czas wyczerpany podczas wzbogacania', url))
    if tb:
        issues.append(_issue(ALERT, workflow, '', 'traceback', 'Traceback w logu', url))
    return issues


def _sport_of(job_name: str) -> str:
    m = re.search(r'\((\w+)', job_name or '')
    return m.group(1) if m else ''


def check_workflow(repo: str, wf: str, day: str) -> Dict[str, Any]:
    out = gh(['run', 'list', '-R', repo, '--workflow', wf, '-L', '20',
              '--json', 'databaseId,createdAt,status,conclusion,url'])
    runs = [r for r in (json.loads(out) if out.strip() else [])
            if str(r.get('createdAt', '')).startswith(day)]
    res: Dict[str, Any] = {'workflow': wf, 'runs_today': len(runs), 'issues': []}
    if not runs:
        return res
    run = runs[0]  # gh zwraca od najnowszego
    res['run'] = {k: run.get(k) for k in ('databaseId', 'status', 'conclusion', 'url')}
    jobs_raw = gh(['api', f'repos/{repo}/actions/runs/{run["databaseId"]}/jobs?per_page=100'])
    jobs = (json.loads(jobs_raw).get('jobs', []) if jobs_raw.strip() else [])
    for job in jobs:
        if job.get('status') != 'completed':
            continue
        url = job.get('html_url', '')
        sport = _sport_of(job.get('name', ''))
        if job.get('conclusion') == 'failure':
            failed = [s['name'] for s in job.get('steps', []) if s.get('conclusion') == 'failure']
            res['issues'].append(_issue(ALERT, wf, sport, 'job_failed',
                                        f'Job „{job.get("name")}” failure'
                                        + (f' (krok: {", ".join(failed)})' if failed else ''), url))
        log = gh(['api', f'repos/{repo}/actions/jobs/{job["id"]}/logs'])
        for it in parse_log(log, wf, url):
            if not it['sport']:
                it['sport'] = sport
            res['issues'].append(it)
    return res


def scheduled_today(wf_path: Path, day: str, now: dt.datetime) -> bool:
    """Czy workflow ma cron, który dziś już powinien był wystartować."""
    if not wf_path.exists():
        return False
    weekday = (dt.date.fromisoformat(day).isoweekday()) % 7  # cron: 0=niedziela
    for cron in re.findall(r"cron:\s*['\"]([^'\"]+)['\"]", wf_path.read_text(encoding='utf-8')):
        parts = cron.split()
        if len(parts) != 5:
            continue
        minute, hour, _dom, _mon, dow = parts
        if dow != '*' and str(weekday) not in re.split(r'[,-]', dow):
            continue
        first_hour = int(re.split(r'[,\-/]', hour)[0]) if hour != '*' else 0
        first_min = int(re.split(r'[,\-/]', minute)[0]) if minute != '*' else 0
        # +1 h zapasu na opóźnienia schedulera GitHub
        if (now.hour, now.minute) >= (first_hour + 1, first_min):
            return True
    return False


def probe_relays(relays: List[str]) -> List[Dict[str, Any]]:
    import requests
    from urllib.parse import quote
    out = []
    for i, relay in enumerate(relays, 1):
        # Ten sam format co sofascore_scraper: <relay>?url=<www_url>
        target = 'https://www.sofascore.com/api/v1/sport/football/categories'
        url = f'{relay}?url={quote(target, safe="")}'
        try:
            r = requests.get(url, timeout=30)
            body = (r.text or '')[:3000]
            exhausted = bool(re.search(r'zbyt wiele razy|too many times|Service invoked', body, re.I))
            ok = r.status_code == 200 and not exhausted and body.lstrip().startswith('{')
            out.append({'relay': i, 'status': r.status_code, 'exhausted': exhausted, 'ok': ok})
        except Exception as e:  # noqa: BLE001
            out.append({'relay': i, 'status': None, 'exhausted': False, 'ok': False,
                        'error': str(e)[:200]})
    return out


def build_html(issues: List[Dict[str, Any]], day: str) -> str:
    from html import escape
    rows = ''.join(
        f"<tr><td>{'🔴' if i['level'] == ALERT else '🟡'} {escape(i['level'])}</td>"
        f"<td>{escape(i['workflow'])}</td><td>{escape(i['sport'] or '—')}</td>"
        f"<td>{escape(i['problem'])}</td><td>{escape(i['meaning'])}</td>"
        f"<td>{escape(i['action'])}"
        + (f" <a href=\"{escape(i['url'])}\">log</a>" if i.get('url') else '')
        + '</td></tr>' for i in issues)
    return (f'<h2>Strażnik — {escape(day)}</h2>'
            '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">'
            '<thead><tr><th>Poziom</th><th>Workflow</th><th>Sport</th><th>Problem</th>'
            '<th>Co to znaczy</th><th>Sugerowana akcja</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def send_email(issues: List[Dict[str, Any]], day: str) -> None:
    import smtplib
    from email.mime.text import MIMEText
    to, frm, pw = (os.getenv('EMAIL_RECIPIENT'), os.getenv('EMAIL_SENDER'),
                   os.getenv('EMAIL_PASSWORD'))
    if not (to and frm and pw):
        print('   ℹ️ Mail Strażnika pominięty (brak EMAIL_*)')
        return
    msg = MIMEText(build_html(issues, day), 'html', 'utf-8')
    msg['Subject'] = f'⚠️ Strażnik: {len(issues)} problemów — {day}'
    msg['From'], msg['To'] = frm, to
    with smtplib.SMTP('smtp.gmail.com', 587) as s:
        s.starttls()
        s.login(frm, pw)
        s.send_message(msg)
    print(f'   📧 Mail Strażnika wysłany ({len(issues)} problemów)')


def run(day: str, repo: str, email: bool, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    issues: List[Dict[str, Any]] = []
    workflows = []
    for wf in WORKFLOWS:
        res = check_workflow(repo, wf, day)
        if res['runs_today'] == 0 and scheduled_today(ROOT / '.github' / 'workflows' / wf, day, now):
            res['issues'].append(_issue(ALERT, wf, '', 'no_run', 'Brak runu mimo harmonogramu'))
        issues.extend(res['issues'])
        workflows.append(res)
    relays = [r.strip() for r in os.getenv('SOFASCORE_RELAY', '').split(',') if r.strip()]
    probes = probe_relays(relays) if relays else []
    for p in probes:
        if not p['ok']:
            issues.append(_issue(WARN, 'SOFASCORE_RELAY', '', 'relay_dead',
                                 f"Przekaźnik #{p['relay']}: "
                                 + ('limit wyczerpany' if p['exhausted'] else f"status {p['status']}")))
    report = {'date': day, 'generated_at': now.isoformat(), 'issues': issues,
              'workflows': workflows, 'relays': probes,
              'counts': {ALERT: sum(i['level'] == ALERT for i in issues),
                         WARN: sum(i['level'] == WARN for i in issues)}}
    path = ROOT / 'results' / f'watchdog_{day}.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"🛡️ Strażnik {day}: {report['counts'][ALERT]} ALERT, {report['counts'][WARN]} WARN")
    for i in issues:
        print(f"   [{i['level']}] {i['workflow']} {i['sport']}: {i['problem']}")
    if issues and email:
        send_email(issues, day)
    elif not issues:
        print('   ✅ Wszystko OK — mail nie jest wysyłany')
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('date', nargs='?', default=dt.datetime.now(dt.timezone.utc).date().isoformat())
    ap.add_argument('--email', action='store_true')
    ap.add_argument('--repo', default=os.getenv('GITHUB_REPOSITORY', 'JKM872/zapasowy1903138-2'))
    a = ap.parse_args()
    run(a.date, a.repo, a.email)
    return 0


if __name__ == '__main__':
    sys.exit(main())
