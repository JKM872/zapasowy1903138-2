"""Wspólny schemat formy dla wszystkich workflow (Forebet, Sports, Dropping Odds).

Czyste funkcje, bez I/O. Liczone z datowanych wierszy Livesport (te same,
już wczytane strony — zero dodatkowych ładowań):

* forma bez sparingów (ogólna / u siebie / na wyjeździe) + liczniki pominiętych,
* forma pucharowa (puchary krajowe, europejskie, międzynarodowe klubowe)
  + lista rozgrywek per drużyna,
* reprezentacje: ``category='reprezentacje'``, sparing reprezentacji →
  ``national_friendly=True`` (pomijany w mailach / TOP).

Istniejące pola formy (``home_form`` itd.) się NIE zmieniają — scoring i progi
kwalifikacji pracują na tych samych danych co dotąd. Nowe widoki są dodatkowe.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

CUP_KEYWORDS = (
    'cup', 'puchar', 'pokal', 'coupe', 'copa', 'coppa', 'beker', 'kupa',
    'champions', 'europa', 'conference', 'libertadores', 'sudamericana',
    'afc', 'caf',
)
FRIENDLY_KEYWORDS = ('friendly', 'friendl', 'towarzysk', 'club friendly', 'sparing')
# 'klubowe' samo w sobie NIE jest sparingiem ('Klubowe Mistrzostwa Świata');
# 'Towarzyskie klubowe' łapie 'towarzysk'.

# Rozgrywki reprezentacji (etykieta ligi meczu).
NATIONAL_COMP_KEYWORDS = (
    'world cup', 'mistrzostwa świata', 'mistrzostwa swiata', 'nations league',
    'liga narodów', 'liga narodow', 'euro 20', 'mistrzostwa europy', 'european championship',
    'africa cup of nations', 'puchar narodów afryki', 'copa america', 'copa américa',
    'asian cup', 'puchar azji', 'gold cup', 'international friendl',
    'towarzyskie międzynarodowe', 'mecze towarzyskie reprezentacji',
)
# Nagłówki Livesport (kraj/region) dla rozgrywek międzynarodowych.
NATIONAL_HEADERS = ('europa:', 'świat:', 'swiat:', 'world:', 'europe:', 'afryka:',
                    'africa:', 'azja:', 'asia:', 'ameryka', 'america', 'oceania:')
# Rozgrywki klubowe pod tymi samymi nagłówkami — to NIE są reprezentacje.
_CLUB_INTL = ('champions', 'europa league', 'liga europy', 'conference', 'libertadores',
              'sudamericana', 'konferencji', 'club', 'klub', 'liga mistrzów', 'liga mistrzow')

COUNTRY_NAMES = frozenset(n.lower() for n in (
    'Poland', 'Polska', 'Germany', 'Niemcy', 'France', 'Francja', 'Spain', 'Hiszpania',
    'Italy', 'Włochy', 'England', 'Anglia', 'Scotland', 'Szkocja', 'Wales', 'Walia',
    'Northern Ireland', 'Irlandia Północna', 'Ireland', 'Irlandia', 'Portugal', 'Portugalia',
    'Netherlands', 'Holandia', 'Belgium', 'Belgia', 'Croatia', 'Chorwacja', 'Serbia',
    'Slovenia', 'Słowenia', 'Slovakia', 'Słowacja', 'Czech Republic', 'Czechy', 'Czechia',
    'Austria', 'Switzerland', 'Szwajcaria', 'Hungary', 'Węgry', 'Romania', 'Rumunia',
    'Bulgaria', 'Bułgaria', 'Greece', 'Grecja', 'Turkey', 'Turcja', 'Türkiye', 'Ukraine',
    'Ukraina', 'Belarus', 'Białoruś', 'Lithuania', 'Litwa', 'Latvia', 'Łotwa', 'Estonia',
    'Finland', 'Finlandia', 'Sweden', 'Szwecja', 'Norway', 'Norwegia', 'Denmark', 'Dania',
    'Iceland', 'Islandia', 'Albania', 'Kosovo', 'Kosowo', 'North Macedonia',
    'Macedonia Północna', 'Montenegro', 'Czarnogóra', 'Bosnia and Herzegovina',
    'Bośnia i Hercegowina', 'Moldova', 'Mołdawia', 'Georgia', 'Gruzja', 'Armenia',
    'Azerbaijan', 'Azerbejdżan', 'Kazakhstan', 'Kazachstan', 'Israel', 'Izrael', 'Cyprus',
    'Cypr', 'Malta', 'Luxembourg', 'Luksemburg', 'Andorra', 'San Marino', 'Gibraltar',
    'Liechtenstein', 'Faroe Islands', 'Wyspy Owcze', 'Russia', 'Rosja',
    'Brazil', 'Brazylia', 'Argentina', 'Argentyna', 'Uruguay', 'Urugwaj', 'Chile',
    'Colombia', 'Kolumbia', 'Peru', 'Ecuador', 'Ekwador', 'Paraguay', 'Paragwaj',
    'Bolivia', 'Boliwia', 'Venezuela', 'Wenezuela', 'Mexico', 'Meksyk', 'USA',
    'United States', 'Stany Zjednoczone', 'Canada', 'Kanada', 'Costa Rica', 'Kostaryka',
    'Panama', 'Honduras', 'Jamaica', 'Jamajka', 'Japan', 'Japonia', 'South Korea',
    'Korea Południowa', 'China', 'Chiny', 'Australia', 'Iran', 'Saudi Arabia',
    'Arabia Saudyjska', 'Qatar', 'Katar', 'Iraq', 'Irak', 'Morocco', 'Maroko', 'Egypt',
    'Egipt', 'Tunisia', 'Tunezja', 'Algeria', 'Algieria', 'Nigeria', 'Senegal', 'Ghana',
    'Cameroon', 'Kamerun', 'Ivory Coast', 'Wybrzeże Kości Słoniowej', 'South Africa',
    'RPA', 'New Zealand', 'Nowa Zelandia',
))

_TEAM_SUFFIX_RE = re.compile(r'\s+(u\d{2}|w|k|\(k\)|\(w\)|women|kobiety)$', re.I)


def _has(label: Any, words) -> bool:
    if not isinstance(label, str) or not label:
        return False
    low = label.lower()
    return any(w in low for w in words)


def is_friendly(label: Any) -> bool:
    return _has(label, FRIENDLY_KEYWORDS)


def is_cup(label: Any) -> bool:
    """Puchar / rozgrywki europejskie / międzynarodowe klubowe (bez sparingów)."""
    if is_friendly(label) or not isinstance(label, str):
        return False
    low = label.lower()
    for w in CUP_KEYWORDS:
        # Krótkie skróty (AFC/CAF/cup) jako osobne słowa — 'cup' nie w 'occupy'.
        if len(w) <= 4:
            if re.search(rf'(?<![a-ząćęłńóśźż]){re.escape(w)}', low):
                return True
        elif w in low:
            return True
    return False


def _norm_team(name: Any) -> str:
    return _TEAM_SUFFIX_RE.sub('', str(name or '').strip()).lower()


def is_national_match(row: Dict[str, Any]) -> bool:
    league = str(row.get('league') or row.get('competition') or '')
    low = league.lower()
    if _has(low, _CLUB_INTL):
        return False
    if _has(low, NATIONAL_COMP_KEYWORDS) and 'club' not in low:
        return True
    if any(low.startswith(h) for h in NATIONAL_HEADERS) and is_friendly(low):
        return True
    return (_norm_team(row.get('home_team')) in COUNTRY_NAMES
            and _norm_team(row.get('away_team')) in COUNTRY_NAMES)


def _dated(row: Dict[str, Any], key: str) -> List[dict]:
    raw = row.get(key)
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


def _labels(rows: List[dict]) -> List[str]:
    out: List[str] = []
    for e in rows:
        ev = str(e.get('event') or '').strip()
        if ev and not is_friendly(ev) and ev not in out:
            out.append(ev)
    return out


_VIEWS = (
    ('home_form_dated', 'home_form', 'home_form_nf', 'home_friendlies_excluded'),
    ('away_form_dated', 'away_form', 'away_form_nf', 'away_friendlies_excluded'),
    ('home_form_home_dated', 'home_form_home', 'home_form_home_nf', 'home_home_friendlies_excluded'),
    ('away_form_away_dated', 'away_form_away', 'away_form_away_nf', 'away_away_friendlies_excluded'),
)


def apply(row: Dict[str, Any]) -> None:
    """Dodaj widoki bez sparingów, formę pucharową i kategorię. Nie rzuca."""
    try:
        _apply(row)
    except Exception as e:  # pragma: no cover — dane wejściowe są nieufne
        print(f"[form_schema] {type(e).__name__}: {e}")


def _apply(row: Dict[str, Any]) -> None:
    total = 0
    for dk, fk, nk, ck in _VIEWS:
        dated = _dated(row, dk)
        if dated:
            row[nk] = [e.get('result') for e in dated if not is_friendly(e.get('event'))]
            row[ck] = sum(1 for e in dated if is_friendly(e.get('event')))
            total += row[ck]
        else:
            # Brak datowanych wierszy (brak etykiet) → nie da się odsiać sparingów.
            form = row.get(fk)
            row[nk] = list(form) if isinstance(form, list) else []
            row[ck] = 0
    row['friendlies_excluded'] = total

    for side in ('home', 'away'):
        dated = _dated(row, f'{side}_form_dated')
        cups = [e for e in dated if is_cup(e.get('event'))]
        row[f'{side}_form_competitions'] = _labels(dated)
        row[f'{side}_cup_form'] = [e.get('result') for e in cups]
        row[f'{side}_cup_competitions'] = _labels(cups)
        row[f'{side}_form_labelled'] = sum(1 for e in dated if str(e.get('event') or '').strip())

    tag_category(row)


def tag_category(row: Dict[str, Any]) -> None:
    """``category='reprezentacje'`` + ``national_friendly`` (idempotentnie)."""
    if is_national_match(row):
        row['category'] = 'reprezentacje'
        row['national_friendly'] = is_friendly(row.get('league'))
    else:
        row.setdefault('national_friendly', False)


# ---------------------------------------------------------------------------
# Renderowanie (wspólne dla maili, TOP, digestu i analityka AI)
# ---------------------------------------------------------------------------

def _as_list(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x) for x in v if x is not None and str(x) != '']
    if isinstance(v, str) and v.strip() and v.strip().lower() not in ('nan', 'none', '[]'):
        s = v.strip()
        if s.startswith('['):
            # Lista po round-tripie CSV ("['W', 'L']").
            import ast
            try:
                return _as_list(ast.literal_eval(s))
            except (ValueError, SyntaxError):
                return []
        return [c for c in s if c in 'WDL'] if re.fullmatch(r'[WDL,\s]+', s) else [s]
    return []


def _f(v: Any) -> str:
    lst = _as_list(v)
    return ''.join(lst) if lst else '—'


def _n(v: Any) -> Optional[int]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else int(f)


def block_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Znormalizowany blok formy z wiersza pipeline (snake_case / CSV)."""
    g = row.get
    return {
        'home': _as_list(g('home_form_nf')) or g('home_form', g('home_form_overall')),
        'away': _as_list(g('away_form_nf')) or g('away_form', g('away_form_overall')),
        'homeAtHome': _as_list(g('home_form_home_nf')) or g('home_form_home'),
        'awayAtAway': _as_list(g('away_form_away_nf')) or g('away_form_away'),
        'homeCup': g('home_cup_form'), 'awayCup': g('away_cup_form'),
        'homeCupCompetitions': g('home_cup_competitions'),
        'awayCupCompetitions': g('away_cup_competitions'),
        'homeSeason': g('home_season_form'), 'awaySeason': g('away_season_form'),
        'homeAtHomeSeason': g('season_home_form'), 'awayAtAwaySeason': g('season_away_form'),
        'homeSeasonMatches': g('home_season_match_count'),
        'awaySeasonMatches': g('away_season_match_count'),
        'friendliesExcluded': g('friendlies_excluded'),
    }


def block_from_json(form: Dict[str, Any]) -> Dict[str, Any]:
    """Blok z eksportu JSON (``m['form']``) — klucze camelCase, *Clean przed surowymi."""
    form = form if isinstance(form, dict) else {}
    out = {}
    for k in ('home', 'away', 'homeAtHome', 'awayAtAway'):
        c = form.get(k + 'Clean')
        out[k] = c if c is not None else form.get(k)
    for k in ('homeCup', 'awayCup', 'homeCupCompetitions', 'awayCupCompetitions',
              'homeSeason', 'awaySeason', 'homeAtHomeSeason', 'awayAtAwaySeason',
              'homeSeasonMatches', 'awaySeasonMatches', 'friendliesExcluded'):
        out[k] = form.get(k)
    return out


def form_lines(b: Dict[str, Any], home: str = '', away: str = '') -> List[str]:
    """Linie bloku 'Forma' + 'Sezon' (tekst; HTML/AI używają tych samych linii)."""
    lines = ['Forma',
             f"  Ogólna {_f(b.get('home'))} / {_f(b.get('away'))}",
             f"  U siebie {_f(b.get('homeAtHome'))}",
             f"  Na wyjeździe {_f(b.get('awayAtAway'))}"]
    cups = []
    for side, name in (('home', home), ('away', away)):
        res = _as_list(b.get(f'{side}Cup'))
        if res:
            comps = ', '.join(_as_list(b.get(f'{side}CupCompetitions')))
            label = f"{name}: " if name else ''
            cups.append(f"{label}{''.join(res)}" + (f" ({comps})" if comps else ''))
    if cups:
        lines.append('  Puchary ' + ' | '.join(cups))
    if b.get('homeSeason') is not None or b.get('awaySeason') is not None:
        hn, an = _n(b.get('homeSeasonMatches')), _n(b.get('awaySeasonMatches'))
        cnt = f" ({'?' if hn is None else hn} / {'?' if an is None else an} m.)"
        lines += ['Sezon',
                  f"  Ogólna {_f(b.get('homeSeason'))} / {_f(b.get('awaySeason'))}{cnt}",
                  f"  U siebie {_f(b.get('homeAtHomeSeason'))}",
                  f"  Na wyjeździe {_f(b.get('awayAtAwaySeason'))}"]
    fx = _n(b.get('friendliesExcluded'))
    if fx:
        lines.append(f"  (pominięte sparingi: {fx})")
    return lines


def form_html(b: Dict[str, Any], home: str = '', away: str = '') -> str:
    from html import escape
    rows = []
    for ln in form_lines(b, home, away):
        if ln.startswith('  '):
            rows.append(f'<div style="padding-left:8px">{escape(ln.strip())}</div>')
        else:
            rows.append(f'<div style="font-weight:bold;margin-top:4px">{escape(ln)}</div>')
    return ('<div style="font-size:11px;color:#444;background:white;border-radius:8px;'
            'padding:8px 10px;margin-bottom:12px;text-align:left">' + ''.join(rows) + '</div>')


def is_national(m: Dict[str, Any]) -> bool:
    return str(m.get('category') or '').lower() == 'reprezentacje'


def is_national_friendly(m: Dict[str, Any]) -> bool:
    v = m.get('national_friendly', m.get('nationalFriendly'))
    return v is True or str(v).strip().lower() in ('true', '1')
