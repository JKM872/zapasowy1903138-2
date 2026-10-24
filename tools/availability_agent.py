"""Availability agent: are the players a pick depends on actually playing?

Runs on every Grade A/B candidate of the day (board + e-mail) and, with a
stricter rule, on every TOP pick. Writes ``results/availability_<day>.json``,
which ``tools/top_picks.py`` and ``api_server.py`` read.

Sources, in order:
  1. SofaScore ``/event/{id}/lineups``: ``missingPlayers`` (injured/suspended,
     with market values) and, once published, the confirmed line-up, which also
     reveals stars left on the bench (rotation/rest). Good for football and NBA.
  2. Gemini with Google Search grounding, for everything SofaScore leaves blank
     (hockey, European basketball, handball, volleyball, tennis withdrawals).
     The model must name players and give a source; an answer without a source
     counts as "unknown", never as "absent".

A pick is judged only on the *picked* side's losses relative to the opponent's:
both teams missing their star is not a reason to drop a favourite.

Verdicts per match (for the picked side):
  ok         – nothing material.
  downgrade  – one grade down on the board (A->B, B->C, so B leaves A/B).
  drop       – out of A/B on the board.
  TOP uses ``top_block`` (stricter) and, for picks already published, the
  re-check close to kick-off turns a block into ``withdrawn``.

Every failure degrades to "no information" and never stops a run.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

STAR_COUNT = 3            # a team's 3 most valuable players are its "stars"
LOOKAHEAD_H = float(os.getenv('AVAIL_LOOKAHEAD_H', '30'))
RECHECK_BEFORE_MIN = 120  # confirmed line-ups appear ~60 min before kick-off
LLM_SPORTS = {'hockey', 'basketball', 'handball', 'volleyball', 'tennis', 'baseball',
              'rugby', 'football'}
SITE_TZ = timezone(timedelta(hours=int(os.getenv('SITE_TZ_OFFSET_H', '2'))))  # Europe/Warsaw (CEST)


# ── pure decision logic (unit-tested) ─────────────────────────────────────────

def summarize(players: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count absences by importance. Doubtful players count half (rounded down
    per category is too lenient, so they are tallied separately)."""
    out = {'stars': 0, 'key': 0, 'other': 0, 'doubtful_stars': 0}
    for p in players or []:
        imp = p.get('importance') or 'other'
        if p.get('status') == 'doubtful':
            if imp == 'star':
                out['doubtful_stars'] += 1
            continue
        if imp == 'star':
            out['stars'] += 1
        elif imp == 'key':
            out['key'] += 1
        else:
            out['other'] += 1
    return out


def verdict(ours: Dict[str, int], theirs: Dict[str, int]) -> Dict[str, Any]:
    """Board verdict and TOP verdict for the picked side."""
    net_stars = ours['stars'] - theirs['stars']
    net_key = (ours['stars'] + ours['key']) - (theirs['stars'] + theirs['key'])
    if ours['stars'] >= 2 and net_stars >= 1:
        board = 'drop'
    elif net_stars >= 1 or (ours['key'] >= 2 and net_key >= 2):
        board = 'downgrade'
    else:
        board = 'ok'
    # TOP: any uncompensated star absence, a doubtful star, or a pile of
    # key players out blocks the pick.
    top_block = (net_stars >= 1
                 or (ours['doubtful_stars'] >= 1 and theirs['stars'] == 0)
                 or net_key >= 2)
    return {'board': board, 'top_block': bool(top_block),
            'netStars': net_stars, 'netKey': net_key}


def apply_grade(grade: Optional[str], board_verdict: Optional[str]) -> Optional[str]:
    """Grade after the availability verdict."""
    order = ['A', 'B', 'C', 'D', 'F']
    if not grade or grade not in order or board_verdict in (None, 'ok'):
        return grade
    if board_verdict == 'drop':
        return 'C' if order.index(grade) < 2 else grade
    return order[min(order.index(grade) + 1, len(order) - 1)]


def key_of(sport: str, home: str, away: str) -> str:
    return f"{sport}|{home}|{away}"


# ── SofaScore ─────────────────────────────────────────────────────────────────

def _event_id(m: Dict[str, Any]) -> Optional[int]:
    url = ((m.get('sofascore') or {}).get('url') or '')
    hit = re.search(r'/(\d{5,})(?:$|[/?#])', url)
    return int(hit.group(1)) if hit else None


def _value(pl: Dict[str, Any]) -> Optional[float]:
    v = (pl.get('proposedMarketValueRaw') or {}).get('value')
    return float(v) if isinstance(v, (int, float)) and v > 0 else None


def parse_lineups(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """SofaScore lineups -> {'home': [...], 'away': [...], 'confirmed': bool}.

    Stars = the STAR_COUNT most valuable players of the matchday squad plus
    the missing list; a star is "absent" when missing, or when line-ups are
    confirmed and he starts on the bench.
    """
    if not isinstance(data, dict):
        return None
    confirmed = bool(data.get('confirmed'))
    out: Dict[str, Any] = {'confirmed': confirmed, 'home': [], 'away': [], 'source': 'sofascore'}
    any_values = False
    for side in ('home', 'away'):
        team = data.get(side) or {}
        squad = [x for x in team.get('players') or [] if isinstance(x, dict)]
        missing = [x for x in team.get('missingPlayers') or [] if isinstance(x, dict)]
        pool = [(_value((x.get('player') or {})), x, 'squad') for x in squad] + \
               [(_value((x.get('player') or {})), x, 'missing') for x in missing]
        valued = sorted((p for p in pool if p[0]), key=lambda p: -p[0])
        any_values = any_values or bool(valued)
        stars = {id(p[1]) for p in valued[:STAR_COUNT]}
        median = valued[len(valued) // 2][0] if valued else None
        rows = []
        for v, x, kind in pool:
            pl = x.get('player') or {}
            name = pl.get('shortName') or pl.get('name')
            if not name:
                continue
            imp = 'star' if id(x) in stars else ('key' if (v and median and v >= median) else 'other')
            if kind == 'missing':
                status = 'doubtful' if x.get('type') == 'doubtful' else 'out'
                reason = x.get('description') or x.get('reason') or x.get('type') or 'out'
            elif confirmed and x.get('substitute') and imp == 'star':
                status, reason = 'out', 'on the bench (confirmed line-up)'
            else:
                continue
            rows.append({'name': name, 'importance': imp, 'status': status, 'reason': str(reason)})
        out[side] = rows
    out['hasValues'] = any_values
    return out


def sofascore_check(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    eid = _event_id(m)
    if not eid:
        return None
    try:
        import sofascore_scraper as ss
        data = ss._api_get_json(f"https://api.sofascore.com/api/v1/event/{eid}/lineups", timeout=10)
    except Exception:
        return None
    res = parse_lineups(data) if isinstance(data, dict) else None
    if res is None:
        return None
    orient = (m.get('sofascore') or {}).get('orientation')
    if orient == 'reversed':
        res['home'], res['away'] = res['away'], res['home']
    # Without market values SofaScore cannot tell a star from a reserve.
    if not res.get('hasValues') and not (res['home'] or res['away']):
        return None
    return res


# ── LLM with Google Search grounding ──────────────────────────────────────────

_PROMPT = """You are a sports team-news checker. Use Google Search.
Match: {home} vs {away} ({sport}, {league}), {day} {time} (Europe/Warsaw).
List players of EACH side who will NOT play or are doubtful (injury, suspension,
illness, rest/rotation, national-team duty; for tennis: withdrawal, injury
concerns, retirement in the previous match).
Only report what a source from the last 7 days states. Mark importance:
"star" = one of the team's 2-3 most important players (top scorer, first-choice
goalkeeper/goalie, franchise player; for tennis the player himself),
"key" = regular starter, "other" = squad player.
Answer ONLY with JSON:
{{"home":[{{"name":"","importance":"star|key|other","status":"out|doubtful","reason":""}}],
 "away":[...], "sources":["url", ...], "confidence":"high|medium|low"}}
If you find nothing reliable, return empty lists and "confidence":"low"."""


def _gemini_grounded(prompt: str) -> Optional[str]:
    """One grounded Gemini call, rotating the keys groq_client knows about."""
    import requests
    from groq_client import gemini_keys, GEMINI_MODELS, GEMINI_ENDPOINT
    for key in gemini_keys():
        for model in GEMINI_MODELS:
            try:
                r = requests.post(GEMINI_ENDPOINT.format(m=model), headers={'x-goog-api-key': key},
                                  json={'contents': [{'parts': [{'text': prompt}]}],
                                        'tools': [{'google_search': {}}],
                                        'generationConfig': {'temperature': 0.0, 'maxOutputTokens': 1200}},
                                  timeout=60)
            except Exception:
                continue
            if r.status_code != 200:
                continue
            try:
                parts = (r.json().get('candidates') or [{}])[0].get('content', {}).get('parts') or []
                txt = ''.join(p.get('text', '') for p in parts).strip()
            except Exception:
                txt = ''
            if txt:
                return txt
    return None


def parse_llm(txt: Optional[str]) -> Optional[Dict[str, Any]]:
    if not txt:
        return None
    hit = re.search(r'\{.*\}', txt, re.S)
    if not hit:
        return None
    try:
        d = json.loads(hit.group(0))
    except Exception:
        return None
    if not d.get('sources'):
        return None  # unsourced claims are not evidence
    clean = {'confirmed': False, 'source': 'llm', 'sources': d.get('sources')[:5],
             'confidence': d.get('confidence') or 'low'}
    for side in ('home', 'away'):
        rows = []
        for p in d.get(side) or []:
            if not isinstance(p, dict) or not p.get('name'):
                continue
            imp = p.get('importance') if p.get('importance') in ('star', 'key', 'other') else 'other'
            st = 'doubtful' if p.get('status') == 'doubtful' else 'out'
            rows.append({'name': str(p['name'])[:60], 'importance': imp, 'status': st,
                         'reason': str(p.get('reason') or '')[:80]})
        clean[side] = rows
    # Low-confidence answers may still list stars, but only as doubtful.
    if clean['confidence'] == 'low':
        for side in ('home', 'away'):
            for p in clean[side]:
                p['status'] = 'doubtful'
    return clean


def llm_check(m: Dict[str, Any], sport: str, day: str) -> Optional[Dict[str, Any]]:
    if sport not in LLM_SPORTS:
        return None
    prompt = _PROMPT.format(home=m.get('homeTeam'), away=m.get('awayTeam'), sport=sport,
                            league=m.get('league') or '', day=day, time=m.get('time') or '')
    try:
        return parse_llm(_gemini_grounded(prompt))
    except Exception:
        return None


# ── orchestration ─────────────────────────────────────────────────────────────

def _kickoff(day: str, hhmm: Optional[str]) -> Optional[datetime]:
    try:
        h, mi = (hhmm or '').split(':')[:2]
        return datetime.strptime(day, '%Y-%m-%d').replace(hour=int(h), minute=int(mi), tzinfo=SITE_TZ)
    except Exception:
        return None


def candidates(day: str) -> List[Dict[str, Any]]:
    """Today's A/B rows plus every TOP pick, deduplicated."""
    out: Dict[str, Dict[str, Any]] = {}
    for p in sorted(glob.glob(os.path.join(ROOT, 'results', f'matches_{day}_*_forebet.json'))):
        sport = os.path.basename(p)[len(f'matches_{day}_'):-len('_forebet.json')]
        try:
            ms = json.load(open(p, encoding='utf-8-sig')).get('matches') or []
        except Exception:
            continue
        for m in ms:
            if not isinstance(m, dict) or not m.get('qualifies'):
                continue
            if (m.get('predictionGrade') or '') not in ('A', 'B'):
                continue
            pick = (m.get('scoring') or {}).get('pick')
            if pick not in ('1', '2'):
                continue
            k = key_of(sport, m.get('homeTeam') or '', m.get('awayTeam') or '')
            out[k] = {'sport': sport, 'm': m, 'side': 'home' if pick == '1' else 'away', 'top': False}
    try:
        tops = json.load(open(os.path.join(ROOT, 'results', f'top_{day}.json'), encoding='utf-8-sig'))
    except Exception:
        tops = []
    for t in tops:
        h, _, a = (t.get('match') or '').partition(' vs ')
        k = key_of(t.get('sport') or '', h, a)
        side = 'home' if t.get('pick') == h else 'away'
        if k in out:
            out[k]['top'] = True
            out[k]['side'] = side
        else:
            out[k] = {'sport': t.get('sport'), 'side': side, 'top': True,
                      'm': {'homeTeam': h, 'awayTeam': a, 'time': t.get('time'), 'league': t.get('league')}}
    return [{'key': k, **v} for k, v in out.items()]


def needs_check(prev: Optional[Dict[str, Any]], ko: Optional[datetime], now: datetime) -> bool:
    if prev is None:
        return True
    if prev.get('confirmed'):
        return False  # confirmed line-up already seen; nothing will improve
    if ko is None:
        return False
    try:
        last = datetime.fromisoformat(prev.get('checkedAt'))
    except Exception:
        return True
    window_start = ko - timedelta(minutes=RECHECK_BEFORE_MIN)
    if now < window_start:
        return False
    # Inside the line-up window: SofaScore is cheap, so keep looking until the
    # line-up is confirmed. The search-grounded LLM is asked once more at most.
    if prev.get('source') == 'sofascore':
        return True
    return last < window_start


def run(day: str, use_llm: bool = True, force: bool = False, log=print) -> Dict[str, Any]:
    path = os.path.join(ROOT, 'results', f'availability_{day}.json')
    try:
        store = json.load(open(path, encoding='utf-8-sig'))
    except Exception:
        store = {}
    now = datetime.now(timezone.utc)
    checked = llm_calls = 0
    for c in candidates(day):
        m, sport, side = c['m'], c['sport'], c['side']
        ko = _kickoff(day, m.get('time'))
        if ko and ko < now - timedelta(minutes=10):
            continue  # already started
        if ko and ko > now + timedelta(hours=LOOKAHEAD_H):
            continue
        prev = store.get(c['key'])
        if not force and not needs_check(prev, ko, now):
            continue
        res = sofascore_check(m)
        if res is None and use_llm:
            res = llm_check(m, sport, day)
            llm_calls += 1
        checked += 1
        if res is None:
            store[c['key']] = {'checkedAt': now.isoformat(), 'source': None, 'confirmed': False,
                               'side': side, 'board': 'ok', 'top_block': False, 'unknown': True}
            continue
        op = 'away' if side == 'home' else 'home'
        v = verdict(summarize(res[side]), summarize(res[op]))
        store[c['key']] = {
            'checkedAt': now.isoformat(), 'source': res.get('source'), 'confirmed': res.get('confirmed'),
            'side': side, 'home': res['home'], 'away': res['away'],
            'sources': res.get('sources'), **v,
        }
        if v['board'] != 'ok' or v['top_block']:
            names = ', '.join(p['name'] for p in res[side] if p['importance'] == 'star')
            log(f"   🚑 {c['key']}: {v['board']}{' / TOP blocked' if v['top_block'] else ''} ({names})")
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(store, fh, ensure_ascii=False, indent=1)
    flagged = sum(1 for r in store.values() if r.get('board') != 'ok' or r.get('top_block'))
    log(f"   availability {day}: checked {checked} (LLM {llm_calls}), flagged {flagged}/{len(store)}")
    return store


def load(day: str) -> Dict[str, Any]:
    try:
        return json.load(open(os.path.join(ROOT, 'results', f'availability_{day}.json'), encoding='utf-8-sig'))
    except Exception:
        return {}


def note(rec: Optional[Dict[str, Any]]) -> str:
    """Short English line for UI/e-mail: 'Key absences: X (injury), Y (bench)'."""
    if not rec:
        return ''
    side = rec.get('side')
    rows = [p for p in (rec.get(side) or []) if p.get('importance') in ('star', 'key')]
    if not rows:
        return ''
    return 'Key absences: ' + ', '.join(
        f"{p['name']}{'*' if p['importance'] == 'star' else ''} ({p.get('reason') or p['status']})" for p in rows[:4])


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('day', nargs='?', default=datetime.now(SITE_TZ).date().isoformat())
    ap.add_argument('--no-llm', action='store_true')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    run(a.day, use_llm=not a.no_llm, force=a.force)
