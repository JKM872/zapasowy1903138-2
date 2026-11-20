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

from zoneinfo import ZoneInfo
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
UNKNOWN_RECHECK_H = 3     # unknown records are re-checked when older than this
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
    ss = m.get('sofascore') or {}
    # Only a verified Fan Vote event belongs to this match: a 'mismatch' row keeps
    # the url of the other game it was matched to, and its line-ups were used.
    if ss.get('orientation') not in ('direct', 'reversed'):
        return None
    hit = re.search(r'/(\d{5,})(?:$|[/?#])', ss.get('url') or '')
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
        if confirmed:
            out.setdefault('squad', {})[side] = [
                {'id': (x.get('player') or {}).get('id'), 'name': (x.get('player') or {}).get('shortName')
                 or (x.get('player') or {}).get('name'), 'sub': bool(x.get('substitute'))} for x in squad]
            out.setdefault('lineup', {})[side] = [
                {'name': (x.get('player') or {}).get('shortName') or (x.get('player') or {}).get('name'),
                 'id': (x.get('player') or {}).get('id'), 'star': id(x) in stars}
                for _, x, k in pool if k == 'squad' and not x.get('substitute')][:11]
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
            rows.append({'name': name, 'importance': imp, 'status': status, 'reason': str(reason),
                         'id': pl.get('id'), 'source': 'sofascore'})
        out[side] = rows
    out['hasValues'] = any_values
    return out


def resolve_event(m: Dict[str, Any], sport: str = '', day: str = ''):
    """(event_id, orientation) of the verified SofaScore event, or (None, None)."""
    eid = _event_id(m)
    orient = (m.get('sofascore') or {}).get('orientation')
    if not eid and sport and day:
        try:
            from tools import injuries as _inj
            ev = _inj._resolve(sport, m.get('homeTeam') or '', m.get('awayTeam') or '', day)
        except Exception:
            ev = None
        if ev:
            eid, orient = ev
            _stat('sofa_resolved')
    return (eid, orient) if eid else (None, None)


def sofascore_check(m: Dict[str, Any], sport: str = '', day: str = '',
                    ev=None, keep_lineup: bool = False) -> Optional[Dict[str, Any]]:
    """keep_lineup: a confirmed line-up without market values or missing players
    comes back flagged ``lineupOnly`` (display data, not a verdict source)."""
    eid, orient = ev if ev else resolve_event(m, sport, day)
    if not eid:
        _stat('sofa_no_event')
        return None
    try:
        import sofascore_scraper as ss
        data = ss._api_get_json(f"https://api.sofascore.com/api/v1/event/{eid}/lineups", timeout=10)
    except Exception:
        data = None
    if not isinstance(data, dict) or not data:
        _stat('sofa_http_fail')   # 403/404/timeout: SofaScore has no line-ups for us (yet)
        return None
    res = parse_lineups(data)
    if res is None:
        _stat('sofa_empty')
        return None
    if orient == 'reversed':
        res['home'], res['away'] = res['away'], res['home']
        for f in ('lineup', 'squad'):
            if res.get(f):
                lu = res[f]
                res[f] = {'home': lu.get('away'), 'away': lu.get('home')}
    # Without market values SofaScore cannot tell a star from a reserve.
    if not res.get('hasValues') and not (res['home'] or res['away']):
        if keep_lineup and res.get('confirmed') and res.get('lineup'):
            _stat('sofa_lineup_only')
            return {**res, 'lineupOnly': True}
        _stat('sofa_empty')
        return None
    _stat('sofa_ok')
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


STATS: Dict[str, int] = {}
ERRORS: Dict[str, str] = {}   # model -> first API error message (for the log)
_DEAD: set = set()            # (key, model) pairs that returned 429 this run


def _stat(k: str) -> None:
    STATS[k] = STATS.get(k, 0) + 1


def _gemini_grounded(prompt: str):
    """One grounded Gemini call -> (text, source urls) or (None, []).

    Sources come from groundingMetadata: the model rarely types URLs into its
    JSON, and the search results it actually used are the better evidence."""
    import requests
    from groq_client import gemini_keys, GEMINI_MODELS, GEMINI_ENDPOINT
    keys = gemini_keys()
    if not keys:
        _stat('no_keys')
        return None, []
    models = [m.strip() for m in os.getenv('AVAIL_GEMINI_MODELS', '').split(',') if m.strip()] or \
        list(dict.fromkeys(['gemini-4-hydrogen'] + list(GEMINI_MODELS)))
    if ('provider', 'gemini') in _DEAD or all((k, m) in _DEAD for k in keys for m in models):
        _stat('llm_off_quota')  # every key x model is quota-exhausted: no more requests this run
        return None, []
    failed_all = True
    for ki, key in enumerate(keys, 1):
        for model in models:
            if (key, model) in _DEAD:
                _stat('skipped_429')
                continue
            try:
                r = requests.post(GEMINI_ENDPOINT.format(m=model), headers={'x-goog-api-key': key},
                                  json={'contents': [{'parts': [{'text': prompt}]}],
                                        'tools': [{'google_search': {}}],
                                        'generationConfig': {'temperature': 0.0, 'maxOutputTokens': 1500}},
                                  timeout=60)
            except Exception:
                _stat('net_error')
                continue
            if r.status_code != 200:
                _stat(f'http_{r.status_code}')
                _stat(f'k{ki}_{model}_http_{r.status_code}')   # per-key reason (no key value)
                if r.status_code in (403, 404, 429):
                    _DEAD.add((key, model))
                else:
                    failed_all = False
                if model not in ERRORS:
                    try:
                        msg = (r.json().get('error') or {}).get('message') or ''
                    except Exception:
                        msg = (r.text or '')[:200]
                    ERRORS[model] = f"{r.status_code}: {' '.join(str(msg).split())[:200]} (k{ki})"
                continue
            try:
                cand = (r.json().get('candidates') or [{}])[0]
                parts = cand.get('content', {}).get('parts') or []
                txt = ''.join(p.get('text', '') for p in parts).strip()
                chunks = (cand.get('groundingMetadata') or {}).get('groundingChunks') or []
                urls = [c.get('web', {}).get('uri') for c in chunks if c.get('web', {}).get('uri')]
            except Exception:
                txt, urls = '', []
            if txt:
                _stat('answered')
                _stat(f'k{ki}_{model}_http_200')
                return txt, urls
            failed_all = False
            _stat('empty')
    if failed_all:
        _DEAD.add(('provider', 'gemini'))   # every pair 404/429/unreachable: provider off for this run
    return None, []


# groq/compound* zniknęło z API Groq (404 od 2026-10); gpt-oss ma wbudowane browser_search.
GROQ_COMPOUND_MODELS = ['openai/gpt-oss-120b', 'openai/gpt-oss-20b']


def compound_urls(msg: Dict[str, Any]) -> List[str]:
    """URLs of the web-search results Groq Compound actually executed."""
    urls: List[str] = []
    for t in (msg or {}).get('executed_tools') or []:
        sr = (t or {}).get('search_results') or {}
        for res in (sr.get('results') if isinstance(sr, dict) else sr) or []:
            u = (res or {}).get('url')
            if isinstance(u, str) and u.startswith('http') and u not in urls:
                urls.append(u)
        # browser_search (gpt-oss) zwraca wyniki jako tekst w 'output'
        for u in re.findall(r'https?://[^\s\]\)\u3011"<>]+', str((t or {}).get('output') or '')):
            if 'exa.ai/search' not in u and u not in urls:
                urls.append(u)
    return urls


def _groq_compound(prompt: str):
    """Groq Compound (server-side web search) -> (text, search-result urls).
    Used when Gemini gives nothing; keys rotate on 429, exhausted pairs are skipped."""
    import requests
    from groq_client import api_keys, CHAT_ENDPOINT
    keys = api_keys()
    if not keys:
        _stat('groq_no_keys')
        return None, []
    models = [m.strip() for m in os.getenv('AVAIL_GROQ_MODELS', '').split(',') if m.strip()] or GROQ_COMPOUND_MODELS
    if ('provider', 'groq') in _DEAD or all(('groq', k, m) in _DEAD for k in keys for m in models):
        _stat('groq_off_quota')
        return None, []
    failed_all = True
    for model in models:
        for key in keys:
            if ('groq', key, model) in _DEAD:
                continue
            try:
                r = requests.post(CHAT_ENDPOINT, headers={'Authorization': f'Bearer {key}'},
                                  json={'model': model, 'temperature': 0.0, 'max_tokens': 1500,
                                        'messages': [{'role': 'user', 'content': prompt}],
                                        **({'tools': [{'type': 'browser_search'}]}
                                           if model.startswith('openai/gpt-oss') else {})},
                                  timeout=90)
            except Exception:
                _stat('groq_net_error')
                continue
            if r.status_code != 200:
                _stat(f'groq_http_{r.status_code}')
                if r.status_code in (401, 403, 404, 429):
                    _DEAD.add(('groq', key, model))
                else:
                    failed_all = False
                if 'groq:' + model not in ERRORS:
                    try:
                        msg = (r.json().get('error') or {}).get('message') or ''
                    except Exception:
                        msg = (r.text or '')[:200]
                    ERRORS['groq:' + model] = f"{r.status_code}: {' '.join(str(msg).split())[:200]}"
                continue
            try:
                msg = ((r.json().get('choices') or [{}])[0]).get('message') or {}
                txt = (msg.get('content') or '').strip()
                urls = compound_urls(msg)
            except Exception:
                txt, urls = '', []
            if txt:
                _stat('groq_answered')
                return txt, urls
            failed_all = False
            _stat('groq_empty')
    if failed_all:
        _DEAD.add(('provider', 'groq'))
    return None, []


def parse_llm(txt: Optional[str], grounding: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    if not txt:
        return None
    hit = re.search(r'\{.*\}', txt, re.S)
    if not hit:
        _stat('no_json')
        return None
    try:
        d = json.loads(hit.group(0))
    except Exception:
        _stat('bad_json')
        return None
    sources = [u for u in (d.get('sources') or []) if isinstance(u, str) and u.startswith('http')]
    sources += [u for u in (grounding or []) if u not in sources]
    if not sources:
        _stat('no_sources')
        return None  # unsourced claims are not evidence
    clean = {'confirmed': False, 'source': 'llm', 'sources': sources[:5],
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
        txt, urls = _gemini_grounded(prompt)
        if not txt:
            txt, urls = _groq_compound(prompt)
        return parse_llm(txt, urls)
    except Exception:
        _stat('exception')
        return None


# ── orchestration ─────────────────────────────────────────────────────────────

def _kickoff(day: str, hhmm: Optional[str], explicit: Optional[str] = None,
             sport: Optional[str] = None) -> Optional[datetime]:
    from tools import pricing
    try:
        return pricing._parse_ts(pricing.parse_kickoff(day, hhmm, [explicit], sport))
    except Exception:
        return None


def candidates(day: str, all_qualifying: bool = False) -> List[Dict[str, Any]]:
    """Today's A/B rows plus every TOP pick, deduplicated.

    ``all_qualifying``: also every other qualifying row the main Forebet e-mail
    lists (grade C, D ...). Those carry ``info_only``: their records are for
    display and never change a grade, a TOP pick or a Fan Favourites verdict."""
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
            ab = (m.get('predictionGrade') or '') in ('A', 'B')
            if not ab and not all_qualifying:
                continue
            pick = (m.get('scoring') or {}).get('pick')
            if pick not in ('1', '2'):
                continue
            k = key_of(sport, m.get('homeTeam') or '', m.get('awayTeam') or '')
            out[k] = {'sport': sport, 'm': m, 'side': 'home' if pick == '1' else 'away', 'top': False}
            if not ab:
                out[k]['info_only'] = True
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
            out[k].pop('info_only', None)
        else:
            out[k] = {'sport': t.get('sport'), 'side': side, 'top': True,
                      'm': {'homeTeam': h, 'awayTeam': a, 'time': t.get('time'), 'league': t.get('league')}}
    try:
        fan = json.load(open(os.path.join(ROOT, 'results', f'fanvote_{day}.json'), encoding='utf-8-sig'))
    except Exception:
        fan = {}
    for blk in (fan.get('sports') or {}).values():
        for p in (blk or {}).get('picks') or []:
            if p.get('side') not in ('home', 'away'):
                continue
            k = key_of(p.get('sport') or '', p.get('home') or '', p.get('away') or '')
            if k in out:
                out[k]['fan'] = True
                if out[k].pop('info_only', None):
                    out[k]['side'] = p['side']   # as before --all-qualifying: the fan side decides
                continue
            hit = re.search(r'/match/(?:[^/]+/)*?(\d{5,})', p.get('sofascoreUrl') or '')
            out[k] = {'sport': p.get('sport'), 'side': p['side'], 'top': False, 'fan': True,
                      'm': {'homeTeam': p.get('home'), 'awayTeam': p.get('away'), 'time': p.get('time'),
                            'league': p.get('league'), 'kickoffUtc': p.get('kickoff'),
                            'sofascore': {'url': p.get('sofascoreUrl'), 'orientation': 'direct'} if hit else {}}}
    return [{'key': k, **v} for k, v in out.items()]


def needs_check(prev: Optional[Dict[str, Any]], ko: Optional[datetime], now: datetime) -> bool:
    if prev is None:
        return True
    if prev.get('confirmed') or (prev.get('lineupInfo') or {}).get('confirmed'):
        return False  # confirmed line-up already seen; nothing will improve
    try:
        last = datetime.fromisoformat(prev.get('checkedAt'))
    except Exception:
        return True
    # An unknown record (or one written before key players / signals existed)
    # is not frozen: SofaScore publishes missing players 1-24 h before kick-off.
    if (prev.get('source') is None or 'signals' not in prev) and now - last >= timedelta(hours=UNKNOWN_RECHECK_H):
        return True
    if ko is None:
        return False
    window_start = ko - timedelta(minutes=RECHECK_BEFORE_MIN)
    if now < window_start:
        return False
    # Inside the line-up window: SofaScore is cheap, so keep looking until the
    # line-up is confirmed (also for unknown records). The search-grounded LLM
    # is asked once more at most.
    if prev.get('source') in ('sofascore', None):
        return True
    return last < window_start


# ── information signals (never change grades, TOP or Fan Favourites) ─────────

def enrich(rec: Dict[str, Any], m: Dict[str, Any], sport: str, day: str, side: str,
           ev=None, deadline: Optional[float] = None) -> Dict[str, Any]:
    """Add free-source rows, key players, next fixture and signals to ``rec``."""
    import time as _time
    from tools import availability_sources as src, key_players as kp
    rec['sport'] = sport
    extra = src.rows_for_match(sport, m.get('league'), m.get('country'),
                               m.get('homeTeam') or '', m.get('awayTeam') or '', day)
    if extra['home'] or extra['away']:
        rec['extra'] = {'home': extra['home'], 'away': extra['away']}
        rec['extraSources'] = extra['sources']
    eid, orient = ev or (None, None)
    if eid and sport == 'tennis' and (deadline is None or _time.monotonic() < deadline):
        wo = parse_tennis_status((kp._get(f'event/{eid}') or {}).get('event') or {}, orient)
        if wo:
            ex = rec.setdefault('extra', {'home': [], 'away': []})
            for s in ('home', 'away'):
                ex.setdefault(s, []).extend(wo[s])
            rec['extraSources'] = sorted(set((rec.get('extraSources') or []) + ['sofascore_status']))
    if eid and sport in kp.SPORTS and (deadline is None or _time.monotonic() < deadline):
        e = (kp._get(f'event/{eid}') or {}).get('event') or {}
        ids = {'home': (e.get('homeTeam') or {}).get('id'), 'away': (e.get('awayTeam') or {}).get('id')}
        if orient == 'reversed':
            ids = {'home': ids['away'], 'away': ids['home']}
        tid = ids.get(side)
        if tid:
            tn = e.get('tournament') or {}
            name = (tn.get('uniqueTournament') or {}).get('name') or tn.get('name')
            rec['eventId'], rec['teams'] = eid, ids
            rec['competition'] = {'name': name, 'ts': e.get('startTimestamp'),
                                  'tier': kp.tier(name, (e.get('roundInfo') or {}).get('name'))}
            rec['keyPlayers'] = {side: kp.team_key_players(sport, tid, day, deadline=deadline)}
            rec['nextFixture'] = {side: kp.next_fixture(tid, e.get('startTimestamp'), eid, day)}
    rec['signals'] = signals(rec, side)
    rec['status'] = status_of(rec, side)
    return rec


def parse_tennis_status(e: Dict[str, Any], orient: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """SofaScore tennis event -> rows for a walkover / withdrawal / retirement.

    Walkover or retirement: the side that did not win (winnerCode) is 'out'.
    Cancelled before the start without a winner: both players unknown -> None
    (a cancelled match is voided, not a signal about one player)."""
    if not isinstance(e, dict):
        return None
    st = e.get('status') or {}
    desc = str(st.get('description') or '').lower()
    typ = str(st.get('type') or '').lower()
    wc = e.get('winnerCode')
    kind = 'walkover' if ('walkover' in desc or desc in ('wo', 'w/o')) else \
        'retired' if ('retired' in desc or 'retirement' in desc) else None
    if not kind and typ == 'canceled' and wc in (1, 2):
        kind = 'withdrawal'
    if not kind or wc not in (1, 2):
        return None
    loser = 'away' if wc == 1 else 'home'
    if orient == 'reversed':
        loser = 'home' if loser == 'away' else 'away'
    team = e.get('awayTeam' if (wc == 1) else 'homeTeam') or {}
    row = {'name': team.get('shortName') or team.get('name') or loser, 'importance': 'star', 'status': 'out',
           'reason': kind, 'id': team.get('id'), 'source': 'sofascore_status'}
    return {'home': [row] if loser == 'home' else [], 'away': [row] if loser == 'away' else []}


def signals(rec: Optional[Dict[str, Any]], side: Optional[str] = None) -> List[Dict[str, Any]]:
    """star_out / star_doubtful / reserves / lineups_ok for the picked side.

    star_out = a key player (>= KEY_SHARE of the team's output over the last
    matches) listed out, or benched in the confirmed line-up. Without key-player
    data the SofaScore market-value star counts (basis 'market value').
    No data -> [] (shown as "unknown"); signals inform only."""
    if not rec:
        return []
    from tools import key_players as kp
    side = side or rec.get('side')
    if side not in ('home', 'away'):
        return []
    out: List[Dict[str, Any]] = []
    kps = kp.status_for(((rec.get('keyPlayers') or {}).get(side) or []), rec, side, rec.get('sport') or 'football')
    for p in kps:
        if (p.get('share') or 0) < kp.KEY_SHARE:
            continue
        if p['status'] in ('out', 'bench'):
            out.append({'kind': 'star_out', 'name': p['name'], 'share': p['share'], 'unit': p.get('unit'),
                        'reason': p.get('reason'), 'source': p.get('source')})
        elif p['status'] == 'doubtful':
            out.append({'kind': 'star_doubtful', 'name': p['name'], 'share': p['share'], 'unit': p.get('unit'),
                        'reason': p.get('reason'), 'source': p.get('source')})
    if not kps:
        for r in (rec.get(side) or []) + ((rec.get('extra') or {}).get(side) or []):
            if isinstance(r, dict) and r.get('importance') == 'star' and r.get('status') in ('out', 'doubtful'):
                kind = 'star_doubtful' if r.get('status') == 'doubtful' else 'star_out'
                out.append({'kind': kind, 'name': r.get('name'), 'share': None, 'basis': 'market value',
                            'reason': r.get('reason'), 'source': r.get('source') or rec.get('source')})
    comp = rec.get('competition') or {}
    rs = kp.reserves_reason(comp.get('tier') or 1, comp.get('ts'), (rec.get('nextFixture') or {}).get(side))
    benched = [p for p in kps if p['status'] == 'bench']
    if rs:
        out.append(rs)
    elif len(benched) >= 2:
        out.append({'kind': 'reserves', 'reason': f'{len(benched)} key players on the bench',
                    'reasonPl': f'{len(benched)} kluczowych na ławce'})
    confirmed = rec.get('confirmed') or (rec.get('lineupInfo') or {}).get('confirmed')
    if confirmed and not any(s['kind'] == 'star_out' for s in out):
        out.append({'kind': 'lineups_ok'})
    return out


_STATUS_ORDER = ('star_out', 'reserves', 'star_doubtful', 'lineups_ok')


def status_of(rec: Optional[Dict[str, Any]], side: Optional[str] = None) -> str:
    """One status per record: star_out | reserves | star_doubtful | lineups_ok |
    no_key_absence (sources checked, nothing important) | unknown."""
    if not rec:
        return 'unknown'
    side = side or rec.get('side')
    sigs = signals(rec, side)
    kinds = {s['kind'] for s in sigs}
    for k in _STATUS_ORDER:
        if k in kinds:
            return k
    extra = rec.get('extra') or {}
    if (rec.get('source') and not rec.get('unknown')) or extra.get('home') or extra.get('away'):
        return 'no_key_absence'
    return 'unknown'


_BADGE = {
    'pl': {'unknown': 'brak danych', 'star_out': 'Gwiazda nie gra', 'star_doubtful': 'Gwiazda niepewna',
           'reserves': 'Możliwe rezerwy', 'lineups_ok': 'Składy OK', 'no_key_absence': 'Bez absencji kluczowych',
           'market': 'top-3 wartości rynkowej', 'saves': 'obron'},
    'en': {'unknown': 'unknown', 'star_out': 'Star out', 'star_doubtful': 'Star doubtful',
           'reserves': 'Likely reserves', 'lineups_ok': 'Line-ups OK', 'no_key_absence': 'No key absences',
           'market': 'top-3 market value', 'saves': 'of saves'},
}


def badge_pl(rec: Optional[Dict[str, Any]], side: Optional[str] = None, sport: str = '',
             lang: str = 'pl') -> Dict[str, str]:
    """{'kind', 'text'}: Polish for the main e-mail, ``lang='en'`` for the site."""
    from tools import key_players as kp
    t = _BADGE.get(lang) or _BADGE['pl']
    st = status_of(rec, side)
    if st == 'unknown':
        return {'kind': st, 'text': t['unknown']}
    sigs = signals(rec, side or (rec or {}).get('side'))
    s = next((x for x in sigs if x['kind'] == st), {})
    if st in ('star_out', 'star_doubtful'):
        if s.get('share') is not None:
            if s.get('unit') == 'saves':
                lbl = t['saves']
            elif lang == 'en':
                lbl = f"of {(kp.METRIC.get(sport) or ('', 'output', ''))[1]}"
            else:
                lbl = (kp.METRIC.get(sport) or ('', '', 'dorobku'))[2]
            why = f"{s['share'] * 100:.0f}% {lbl}"
        else:
            why = t['market']
        return {'kind': st, 'text': f"{t[st]}: {s.get('name')} ({why})"}
    if st == 'reserves':
        why = s.get('reasonPl') if lang == 'pl' else s.get('reason')
        return {'kind': st, 'text': f"{t[st]}: {why or s.get('reason')}"}
    return {'kind': st, 'text': t[st]}


def key_lines(rec: Optional[Dict[str, Any]], side: Optional[str] = None, n: int = 3) -> List[str]:
    from tools import key_players as kp
    if not rec:
        return []
    side = side or rec.get('side')
    return [kp.fmt_line(p) for p in kp.status_for(((rec.get('keyPlayers') or {}).get(side) or [])[:n], rec, side,
                                                  rec.get('sport') or 'football')]


def run(day: str, use_llm: bool = True, force: bool = False, log=print,
        all_qualifying: bool = False, path: Optional[str] = None,
        ignore_kickoff: bool = False) -> Dict[str, Any]:
    """Check every candidate and write the store.

    all_qualifying: also every qualifying row of the main e-mail (info only).
    path / ignore_kickoff: dry runs write elsewhere and also look at matches
    that already started (to measure coverage after the fact)."""
    path = path or os.path.join(ROOT, 'results', f'availability_{day}.json')
    try:
        store = json.load(open(path, encoding='utf-8-sig'))
    except Exception:
        store = {}
    now = datetime.now(timezone.utc)
    checked = llm_calls = 0
    import time as _time
    t0, budget = _time.monotonic(), float(os.getenv('AVAIL_BUDGET_S', '1200'))

    def _save():
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(store, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    cands = candidates(day, all_qualifying=all_qualifying)
    # A/B, TOP and Fan Favourites first: they can lose the budget race otherwise.
    # Grounded-call priority: TOP, then Fan Favourites, then Forebet A/B.
    cands.sort(key=lambda c: (bool(c.get('info_only')), 0 if c.get('top') else 1 if c.get('fan') else 2))
    llm_max = int(os.getenv('AVAIL_LLM_MAX', '200'))
    for c in cands:
        left = budget - (_time.monotonic() - t0)
        if left <= 0:
            log(f'   availability: budżet {budget:.0f}s wyczerpany, stop po {checked} sprawdzeniach')
            break
        m, sport, side = c['m'], c['sport'], c['side']
        info_only = bool(c.get('info_only'))
        ko = _kickoff(day, m.get('time'), m.get('kickoffUtc'), sport)
        if not ignore_kickoff:
            if ko and ko < now - timedelta(minutes=10):
                continue  # already started
            if ko and ko > now + timedelta(hours=LOOKAHEAD_H):
                continue
        prev = store.get(c['key'])
        if prev and prev.get('infoOnly') and not info_only:
            prev = None   # promoted to A/B/TOP/fan: judge it properly now
        if not force and not needs_check(prev, ko, now):
            continue
        ev = resolve_event(m, sport, day)
        res = sofascore_check(m, sport, day, ev=ev if ev[0] else None, keep_lineup=True)
        lineup_info = None
        if res is not None and res.get('lineupOnly'):
            # Confirmed XI without values/missing list: shown (key players on the
            # bench, "line-ups OK"), but legacy verdict fields stay "unknown".
            lineup_info, res = {'confirmed': True, 'lineup': res.get('lineup'), 'squad': res.get('squad')}, None
        elif res is not None and res.get('squad'):
            lineup_info = {'confirmed': True, 'lineup': res.get('lineup'), 'squad': res.get('squad')}
        llm_at = (prev or {}).get('llmAt')
        llm_due = not llm_at or now - datetime.fromisoformat(llm_at) >= timedelta(hours=UNKNOWN_RECHECK_H)
        if res is None and use_llm and not info_only and left >= 60 and llm_due and llm_calls < llm_max:
            res = llm_check(m, sport, day)
            llm_calls += 1
            llm_at = now.isoformat()
        checked += 1
        if checked % 10 == 0:
            _save()
        if res is None and prev and prev.get('source') and not prev.get('unknown'):
            # A failed re-check (403/404/timeout) never wipes what an earlier run found.
            rec = {k: v for k, v in prev.items() if k not in ('signals', 'status')}
            rec['lastFailAt'] = now.isoformat()
            v = {'board': rec.get('infoVerdict') or rec.get('board'), 'top_block': rec.get('top_block')}
            _stat('kept_previous')
        elif res is None:
            rec = {'checkedAt': now.isoformat(), 'source': None, 'confirmed': False,
                   'side': side, 'board': 'ok', 'top_block': False, 'unknown': True}
            v = {'board': 'ok', 'top_block': False}
        else:
            op = 'away' if side == 'home' else 'home'
            v = verdict(summarize(res[side]), summarize(res[op]))
            rec = {
                'checkedAt': now.isoformat(), 'source': res.get('source'), 'confirmed': res.get('confirmed'),
                'side': side, 'home': res['home'], 'away': res['away'],
                'sources': res.get('sources'), 'lineup': res.get('lineup'), **v,
            }
        if llm_at:
            rec['llmAt'] = llm_at
        if lineup_info:
            rec['lineupInfo'] = lineup_info
        if info_only:
            # Display only: the record never downgrades, blocks or withdraws anything.
            rec.update(infoOnly=True, infoVerdict=v.get('board'), board='ok', top_block=False)
        try:
            enrich(rec, m, sport, day, side, ev, deadline=t0 + budget)
        except Exception as e:
            _stat('enrich_error')
            log(f"   availability enrich {c['key']}: {type(e).__name__}: {e}")
        store[c['key']] = rec
        if res is None:
            continue
        if v['board'] != 'ok' or v['top_block']:
            names = ', '.join(p['name'] for p in res[side] if p['importance'] == 'star')
            log(f"   🚑 {c['key']}: {v['board']}{' / TOP blocked' if v['top_block'] else ''} ({names})")
    if use_llm:
        try:
            summarize_news(day, store, [c for c in cands if c.get('top') or c.get('fan')], log=log)
        except Exception as e:
            log(f'   availability summaries failed: {e}')
    _save()
    try:
        from tools import key_players as _kp, availability_sources as _src
        _kp.save(day)
        log(f"   availability sources: {_src.STATS} | key players: {_kp.STATS}")
    except Exception:
        pass
    flagged = sum(1 for r in store.values() if r.get('board') != 'ok' or r.get('top_block'))
    log(f"   availability {day}: checked {checked} (LLM {llm_calls}), flagged {flagged}/{len(store)} | {STATS}")
    if ERRORS:
        log(f"   availability gemini errors: {ERRORS}")
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


NO_NEWS = 'No confirmed team news yet'
SUMMARY_MAX_CALLS = int(os.getenv('AVAIL_SUMMARY_MAX', '60'))


def _players(rec: Dict[str, Any], side: str) -> List[Dict[str, Any]]:
    return [{'name': p.get('name'), 'importance': p.get('importance') or 'other',
             'status': p.get('status') or 'out', 'reason': p.get('reason') or ''}
            for p in rec.get(side) or [] if isinstance(p, dict) and p.get('name')]


def badge(players: List[Dict[str, Any]]) -> str:
    """'2 stars out', '1 star doubtful', '3 key out' — '' when nothing notable."""
    s = sum(1 for p in players if p['importance'] == 'star' and p['status'] != 'doubtful')
    d = sum(1 for p in players if p['importance'] == 'star' and p['status'] == 'doubtful')
    k = sum(1 for p in players if p['importance'] == 'key' and p['status'] != 'doubtful')
    parts = []
    if s:
        parts.append(f"{s} star{'s' if s > 1 else ''} out")
    if d:
        parts.append(f"{d} star{'s' if d > 1 else ''} doubtful")
    if k and not s:
        parts.append(f"{k} key out")
    return ', '.join(parts)


def team_news(rec: Optional[Dict[str, Any]], pick_side: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """API shape: home/away lists, side badges, confirmed XI, AI summary."""
    if not rec or rec.get('unknown') or not rec.get('source'):
        return None
    side = pick_side or rec.get('side')
    home, away = _players(rec, 'home'), _players(rec, 'away')
    ours, theirs = (home, away) if side == 'home' else (away, home)
    return {'home': home, 'away': away, 'side': side,
            'confirmedLineup': bool(rec.get('confirmed')), 'lineup': rec.get('lineup'),
            'source': rec.get('source'), 'sources': rec.get('sources'), 'checkedAt': rec.get('checkedAt'),
            'badgePick': badge(ours), 'badgeOpponent': badge(theirs),
            'verdict': rec.get('board'), 'summary': rec.get('aiSummary') or None}


def email_line(rec: Optional[Dict[str, Any]], home: str = '', away: str = '') -> str:
    """One e-mail line: AI summary if present, else side badges, else NO_NEWS."""
    tn = team_news(rec)
    if not tn:
        return f'Team news: {NO_NEWS}'
    if tn['summary']:
        return f"Team news: {tn['summary']}"
    bits = []
    for lbl, b in (('our pick', tn['badgePick']), ('opponent', tn['badgeOpponent'])):
        if b:
            bits.append(f'{lbl} {b}')
    return 'Team news: ' + ('; '.join(bits) if bits else 'no key absences reported')


_SUM_PROMPT = """You write team-news notes for a betting tip. Use ONLY the data below; do not add players or facts.
Match: {home} vs {away} ({sport}). Our pick: {team} ({side}).
Absences of {home} (home): {h}
Absences of {away} (away): {a}
Confirmed line-ups: {conf}. Source: {src}.
In 1-2 short English sentences say whose absences matter and whether they weaken our pick.
Answer ONLY with JSON: {{"summary": "...", "weakens": "yes|no|slightly"}}"""


def _fmt_players(ps: List[Dict[str, Any]]) -> str:
    return '; '.join(f"{p['name']} [{p['importance']}, {p['status']}: {p['reason']}]" for p in ps) or 'none reported'


def parse_summary(txt: Optional[str]) -> Optional[str]:
    """Pull 'summary' out of a model reply; None on junk. Max 2 sentences / 300 chars."""
    if not txt:
        return None
    hit = re.search(r'\{.*\}', txt, re.S)
    s = None
    if hit:
        try:
            s = json.loads(hit.group(0)).get('summary')
        except Exception:
            s = None
    if not isinstance(s, str) or not s.strip():
        return None
    s = ' '.join(s.split())
    sent = re.split(r'(?<=[.!?])\s+', s)
    s = ' '.join(sent[:2])
    return s[:300]


def summarize_news(day: str, store: Dict[str, Any], keys: List[Dict[str, Any]],
                   chat=None, max_calls: int = SUMMARY_MAX_CALLS, log=print) -> int:
    """AI summary per TOP / Fan Favourites match, cached in the store per day.
    Unsourced (unknown) records get NO_NEWS without any call."""
    if chat is None:
        try:
            import groq_client
            chat = lambda p: groq_client.chat(p, max_tokens=200, log=lambda *_: None)
        except Exception:
            chat = None
    calls = 0
    for c in keys:
        rec = store.get(c['key'])
        if not rec:
            continue
        sig = f"{rec.get('checkedAt')}|{rec.get('confirmed')}"
        if rec.get('aiSummary') and rec.get('aiSummarySig') == sig:
            continue
        if rec.get('unknown') or not rec.get('source'):
            rec['aiSummary'], rec['aiSummarySig'] = NO_NEWS, sig
            continue
        h, a = _players(rec, 'home'), _players(rec, 'away')
        if not h and not a:
            rec['aiSummary'], rec['aiSummarySig'] = (
                'No absences reported for either side.' if rec.get('source') == 'sofascore' else NO_NEWS), sig
            continue
        if chat is None or calls >= max_calls:
            continue
        m = c['m']
        side = rec.get('side') or c.get('side')
        prompt = _SUM_PROMPT.format(
            home=m.get('homeTeam'), away=m.get('awayTeam'), sport=c.get('sport'),
            team=m.get('homeTeam') if side == 'home' else m.get('awayTeam'), side=side,
            h=_fmt_players(h), a=_fmt_players(a), conf='yes' if rec.get('confirmed') else 'not yet',
            src=rec.get('source'))
        calls += 1
        try:
            s = parse_summary(chat(prompt))
        except Exception:
            s = None
        if s:
            rec['aiSummary'], rec['aiSummarySig'] = s, sig
    log(f'   availability summaries {day}: {calls} Groq calls')
    return calls


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('day', nargs='?', default=datetime.now(ZoneInfo('Europe/Warsaw')).date().isoformat())
    ap.add_argument('--no-llm', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--all-qualifying', action='store_true',
                    help='also every qualifying row of the main e-mail (information only)')
    ap.add_argument('--dry-run', action='store_true',
                    help='write outputs/availability_dryrun_<day>.json (copy of the store), include started matches')
    a = ap.parse_args()
    out_path = None
    if a.dry_run:
        import shutil
        from tools import key_players as _kp
        os.makedirs(os.path.join(ROOT, 'outputs'), exist_ok=True)
        out_path = os.path.join(ROOT, 'outputs', f'availability_dryrun_{a.day}.json')
        src_path = os.path.join(ROOT, 'results', f'availability_{a.day}.json')
        if os.path.exists(src_path) and not os.path.exists(out_path):
            shutil.copy(src_path, out_path)
        _kp.CACHE_PATH = os.path.join(ROOT, 'outputs', f'key_players_dryrun_{a.day}.json')
    run(a.day, use_llm=not a.no_llm, force=a.force, all_qualifying=a.all_qualifying,
        path=out_path, ignore_kickoff=a.dry_run)
