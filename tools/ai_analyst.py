"""Analityk AI — ocena TOP + Twierdza przez Gemini (zamiast ręcznego wklejania maila do AI).

analyse(candidates, day) -> [{key, verdict, confidence, reason, risks}]
  verdict: GRAJ | ODPUŚĆ | OBSERWUJ, confidence 1-5.
Każdy błąd (sieć, limit, zły JSON) => [] — nigdy nie przerywa przebiegu.

AI_ANALYST_FINAL_MODEL (opcjonalnie, np. 'gemini-4-argon'): jedno dodatkowe
zapytanie z TOP 10 GRAJ o ranking końcowy; 4xx (płatny/niedostępny) = pomijamy.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from html import escape
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCH = int(os.getenv('AI_ANALYST_BATCH', '25'))
VERDICTS = ('GRAJ', 'OBSERWUJ', 'ODPUŚĆ')
_VERDICT_ALIASES = {'ODPUSC': 'ODPUŚĆ', 'ODPUŚC': 'ODPUŚĆ', 'ODPUSĆ': 'ODPUŚĆ'}

# Pola surowego meczu (matches_<day>_*.json) przekazywane modelowi.
RAW_FIELDS = ('odds', 'forebet', 'form', 'h2h', 'sofascore', 'scoring', 'predictionGrade',
              'earlySeason', 'staleModel', 'seasonFormConflict', 'seasonMatchCount', 'seasonForm', 'season_form',
              'recency', 'league', 'time', 'injuries', 'injuryCounts', 'injury_risk')

PROMPT = (
    "Jesteś analitykiem zakładów sportowych. Oceń każdy kandydat (typ na zwycięzcę) na podstawie "
    "WSZYSTKICH danych: kursy, prawdopodobieństwa Forebet, forma ogólna, u siebie/na wyjeździe, "
    "forma w BIEŻĄCYM sezonie (ważniejsza niż końcówka poprzedniego — transfery), flagi "
    "early_season/season_form_conflict/stale_model, H2H (ważone wiekiem), SofaScore Fan Vote, "
    "grade, score, sygnały. Puchar vs słabszy rywal: dominacja może nie być widoczna w H2H.\n"
    "Absencje (injuries: home/away, reason kontuzja/zawieszenie/wątpliwy, key=kluczowy; "
    "injury_risk=typowana strona osłabiona): brak gwiazdy typowanej strony to ryzyko, "
    "braki u rywala to atut. Brak pola = brak danych, nie brak absencji.\n"
    "Zwróć WYŁĄCZNIE tablicę JSON, bez komentarzy, jeden obiekt na kandydata:\n"
    '[{"key": "<key bez zmian>", "verdict": "GRAJ|ODPUŚĆ|OBSERWUJ", "confidence": 1-5, '
    '"reason": "max 2 zdania po polsku", "risks": ["krótko", "..."]}]\n'
    "Dzień: {day}. Kandydaci:\n{data}")

FINAL_PROMPT = (
    "Ułóż ranking końcowy (najpewniejszy pierwszy) tych typów ocenionych jako GRAJ. "
    "Zwróć WYŁĄCZNIE tablicę JSON z polami key, verdict, confidence (1-5), reason (max 2 zdania "
    "po polsku), risks (lista). Dzień: {day}.\n{data}")


def candidate_key(c: Dict[str, Any]) -> str:
    return f"{c.get('sport')}|{c.get('match')}|{c.get('pick')}"


def _raw_index(day: str) -> Dict[tuple, Dict[str, Any]]:
    idx: Dict[tuple, Dict[str, Any]] = {}
    for p in sorted(glob.glob(os.path.join(ROOT, 'results', f'matches_{day}_*.json'))):
        name = os.path.basename(p)[len(f'matches_{day}_'):-5]
        sport = name[:-8] if name.endswith('_forebet') else name
        try:
            ms = json.load(open(p, encoding='utf-8-sig')).get('matches') or []
        except Exception:
            continue
        for m in ms:
            k = (sport, f"{m.get('homeTeam')} vs {m.get('awayTeam')}")
            # Forebet (pliki *_forebet) wygrywa — ma flagi recency i formę sezonu.
            if k not in idx or name.endswith('_forebet'):
                idx[k] = m
    return idx


def build_candidates(day: str, top: List[Dict[str, Any]],
                     twierdza: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """TOP + Twierdza (bez duplikatów) wzbogacone o surowe dane meczu."""
    try:
        idx = _raw_index(day)
    except Exception:
        idx = {}
    out, seen = [], set()
    for src, rows in (('TOP', top or []), ('Twierdza', twierdza or [])):
        for r in rows:
            c = {'source': src, **{k: v for k, v in r.items() if k != 'stars'}}
            k = candidate_key(c)
            if k in seen:
                continue
            seen.add(k)
            c['key'] = k
            raw = idx.get((r.get('sport'), r.get('match'))) or {}
            c['data'] = {f: raw[f] for f in RAW_FIELDS if raw.get(f) not in (None, '', {}, [])}
            out.append(c)
    return out


def parse_json_list(txt: Optional[str]) -> List[Dict[str, Any]]:
    """Wyciągnij listę obiektów JSON z odpowiedzi (``` fence, śmieci wokół)."""
    if not txt:
        return []
    s = re.sub(r'```(?:json)?', '', str(txt))
    for cand in (s.strip(), s[s.find('['):s.rfind(']') + 1] if '[' in s else ''):
        if not cand:
            continue
        try:
            v = json.loads(cand)
        except Exception:
            continue
        if isinstance(v, dict):
            v = v.get('items') or v.get('results') or [v]
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    # Ucięta / zabrudzona odpowiedź: ratujemy każdy kompletny obiekt z polem key.
    dec, out, i = json.JSONDecoder(), [], s.find('{')
    while i != -1:
        try:
            obj, end = dec.raw_decode(s, i)
        except Exception:
            i = s.find('{', i + 1)
            continue
        if isinstance(obj, dict) and 'key' in obj:
            out.append(obj)
        i = s.find('{', end)
    return out


def _normalise(items: List[Dict[str, Any]], keys: set) -> List[Dict[str, Any]]:
    out = []
    for it in items:
        k = it.get('key')
        if k not in keys:
            continue
        v = str(it.get('verdict') or '').strip().upper()
        v = _VERDICT_ALIASES.get(v, v)
        if v not in VERDICTS:
            continue
        try:
            conf = max(1, min(5, int(round(float(it.get('confidence'))))))
        except Exception:
            conf = 1
        risks = it.get('risks') or []
        if isinstance(risks, str):
            risks = [risks]
        out.append({'key': k, 'verdict': v, 'confidence': conf,
                    'reason': str(it.get('reason') or '').strip()[:400],
                    'risks': [str(x)[:120] for x in risks if x][:4]})
    return out


def _chat(prompt: str, **kw) -> Optional[str]:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import groq_client
    return groq_client.gemini_chat(prompt, max_tokens=16000, temperature=0.2, timeout=90, **kw)


def _final_ranking(results: List[Dict[str, Any]], cands: Dict[str, Dict[str, Any]],
                   day: str) -> List[Dict[str, Any]]:
    """Opcjonalny ranking końcowy droższym modelem; przy błędzie bez zmian."""
    model = os.getenv('AI_ANALYST_FINAL_MODEL', '').strip()
    graj = sorted([r for r in results if r['verdict'] == 'GRAJ'],
                  key=lambda r: -r['confidence'])[:10]
    if not model or not graj:
        return results
    try:
        import requests
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        import groq_client
        keys = groq_client.gemini_keys()
        if not keys:
            return results
        data = json.dumps([{**cands[r['key']], 'ocena': r} for r in graj],
                          ensure_ascii=False, default=str)
        r = requests.post(groq_client.GEMINI_ENDPOINT.format(m=model),
                          headers={'x-goog-api-key': keys[0]},
                          json={'contents': [{'parts': [{'text': FINAL_PROMPT.format(day=day, data=data)}]}],
                                'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 4000}},
                          timeout=120)
        if r.status_code != 200:
            print(f"   ℹ️ Analityk AI: model końcowy {model} HTTP {r.status_code} — pomijam")
            return results
        parts = (r.json().get('candidates') or [{}])[0].get('content', {}).get('parts') or []
        final = _normalise(parse_json_list(''.join(p.get('text', '') for p in parts)),
                           {g['key'] for g in graj})
        if not final:
            return results
        fk = {f['key'] for f in final}
        print(f"   🧠 Analityk AI: ranking końcowy {model} ({len(final)})")
        return final + [r for r in results if r['key'] not in fk]
    except Exception as e:
        print(f"   ℹ️ Analityk AI: model końcowy pominięty ({type(e).__name__})")
        return results


def analyse(candidates: List[Dict[str, Any]], day: str) -> List[Dict[str, Any]]:
    try:
        cands = {}
        for c in candidates or []:
            c = dict(c)
            c.setdefault('key', candidate_key(c))
            cands[c['key']] = c
        if not cands:
            return []
        items = list(cands.values())
        results: List[Dict[str, Any]] = []
        for i in range(0, len(items), max(1, BATCH)):
            todo = items[i:i + BATCH]
            for attempt in range(2):   # druga próba tylko dla brakujących kluczy
                data = json.dumps(todo, ensure_ascii=False, default=str)
                got = _normalise(parse_json_list(_chat(PROMPT.replace('{day}', day).replace('{data}', data))),
                                 {c['key'] for c in todo})
                done = {r['key'] for r in results}
                results += [r for r in got if r['key'] not in done]
                done = {r['key'] for r in results}
                print(f"   🧠 Analityk AI: partia {i // BATCH + 1} próba {attempt + 1}: "
                      f"{len(got)}/{len(todo)}")
                todo = [c for c in todo if c['key'] not in done]
                if not todo:
                    break
        if not results:
            return []
        results = _final_ranking(results, cands, day)
        for r in results:
            c = cands[r['key']]
            r.update({'match': c.get('match'), 'pick': c.get('pick'), 'odds': c.get('odds'),
                      'sport': c.get('sport'), 'source': c.get('source'),
                      'injuryLine': c.get('injuryLine') or ''})
        return results
    except Exception as e:
        print(f"   ⚠️ Analityk AI: {type(e).__name__} — pomijam")
        return []


def save(results: List[Dict[str, Any]], day: str) -> Optional[str]:
    try:
        p = os.path.join(ROOT, 'results', f'ai_analyst_{day}.json')
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
        return p
    except Exception:
        return None


def load(day: str) -> List[Dict[str, Any]]:
    try:
        return json.load(open(os.path.join(ROOT, 'results', f'ai_analyst_{day}.json'),
                              encoding='utf-8-sig')) or []
    except Exception:
        return []


def run(day: str, top: List[Dict[str, Any]], twierdza: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Zbuduj kandydatów, oceń, zapisz. Zawsze zwraca listę."""
    try:
        res = analyse(build_candidates(day, top, twierdza), day)
    except Exception:
        res = []
    if res and len(res) >= len(load(day)):   # nie nadpisuj pełniejszej oceny gorszą
        save(res, day)
    counts = {v: sum(1 for r in res if r['verdict'] == v) for v in VERDICTS}
    print(f"   🧠 Analityk AI: {len(res)} werdyktów {counts}")
    return res


def ordered(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rank = {v: i for i, v in enumerate(VERDICTS)}
    return sorted(results or [], key=lambda r: (rank.get(r.get('verdict'), 9),
                                                -int(r.get('confidence') or 0)))


_BADGE = {'GRAJ': '#1e8e3e', 'OBSERWUJ': '#80868b', 'ODPUŚĆ': '#d93025'}


def html_section(results: List[Dict[str, Any]]) -> str:
    """Sekcja maila (inline CSS). Pusty string, gdy brak wyników."""
    if not results:
        return ''
    cards = []
    for r in ordered(results):
        v = r.get('verdict')
        conf = int(r.get('confidence') or 0)
        try:
            odds = f"{float(r.get('odds')):.2f}"
        except Exception:
            odds = escape(str(r.get('odds') or '-'))
        risks = ''.join(f"<li style='margin:0'>{escape(str(x))}</li>" for x in r.get('risks') or [])
        cards.append(
            "<div style='border:1px solid #dadce0;border-radius:8px;padding:10px;margin:8px 0;"
            "font-family:Arial,sans-serif;font-size:14px'>"
            f"<span style='background:{_BADGE.get(v, '#80868b')};color:#fff;padding:2px 8px;"
            f"border-radius:4px;font-weight:bold'>{escape(str(v))}</span> "
            f"<b>{escape(str(r.get('match') or r.get('key')))}</b> "
            f"<span style='color:#5f6368'>({escape(str(r.get('sport') or ''))})</span><br>"
            f"<span>{escape(str(r.get('pick') or ''))} @ {odds}</span> "
            f"<span style='color:#f9ab00'>{'★' * conf}{'☆' * (5 - conf)}</span><br>"
            f"<span>{escape(str(r.get('reason') or ''))}</span>"
            + (f"<br><span style='color:#5f6368;font-size:12px'>{escape(str(r['injuryLine']))}</span>"
               if r.get('injuryLine') else '')
            + (f"<ul style='margin:4px 0 0 18px;padding:0;color:#5f6368;font-size:12px'>{risks}</ul>"
               if risks else '')
            + "</div>")
    return ("<div style='margin-bottom:16px'><h2 style='font-family:Arial,sans-serif'>🧠 Analityk AI</h2>"
            + ''.join(cards) + "</div>")
