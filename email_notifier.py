"""
Moduł do wysyłania powiadomień email o kwalifikujących się meczach

NOWE: Sekcje pre-posortowanych kursów (home/draw/away) - od najwyższych do najniższych
"""

import smtplib
import math
import json
import os
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional, Any
import pandas as pd
from datetime import datetime


# ============================================================================
# GLOBAL HELPER FUNCTIONS - Obsługa NaN, None i różnych formatów danych
# ============================================================================

def ensure_ai_prediction_dict(val: Any) -> Dict[str, Any]:
    """
    Normalizuje ai_prediction do dict.
    Po read_csv dict jest serializowany do stringa JSON — ta funkcja odwraca to.
    Obsługuje: dict (passthrough), JSON string, None, NaN, pusty string.
    """
    if isinstance(val, dict):
        return {str(k): v for k, v in val.items()}  # type: ignore[union-attr]
    if val is None:
        return {}
    if isinstance(val, float):
        return {}  # NaN z pandas
    if isinstance(val, str):
        s = val.strip()
        if not s or s.lower() in ('nan', 'none', '{}'):
            return {}
        try:
            parsed = json.loads(s.replace("'", '"'))
            if isinstance(parsed, dict):
                return {str(k): v for k, v in parsed.items()}  # type: ignore[union-attr]
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def is_nan_or_none(val: Any) -> bool:
    """
    Sprawdza czy wartość jest NaN, None lub pustym stringiem.
    Obsługuje różne formaty pandas/numpy NaN.
    """
    if val is None:
        return True
    if isinstance(val, str):
        return val.strip() == '' or val.lower() == 'nan' or val.lower() == 'none'
    if isinstance(val, float):
        try:
            return math.isnan(val)
        except (TypeError, ValueError):
            return False
    return False


def safe_value(val: Any, default: Any = '') -> Any:
    """
    Zwraca wartość lub default jeśli wartość jest NaN/None.
    """
    if is_nan_or_none(val):
        return default
    return val


def safe_float(val: Any, default: float = 0.0) -> float:
    """
    Bezpiecznie konwertuje wartość na float.
    Obsługuje NaN, None, stringi, etc.
    """
    if is_nan_or_none(val):
        return default
    try:
        result = float(val)
        if math.isnan(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


def parse_form_list(form_data: Any) -> List[str]:
    """
    Parsuje dane formy z różnych formatów (string, lista, etc.) do listy.
    Obsługuje formaty: ['W', 'L', 'D'], "['W', 'L', 'D']", "W-L-D", "WLD", etc.
    """
    if is_nan_or_none(form_data):
        return []
    
    # Już jest listą
    if isinstance(form_data, list):
        return [str(x).strip().upper() for x in form_data if x]  # type: ignore[union-attr]
    
    # String - parsuj
    if isinstance(form_data, str):
        form_str = form_data.strip()
        if not form_str:
            return []
        
        # Format: "['W', 'L', 'D']" - stringified list
        if form_str.startswith('[') and form_str.endswith(']'):
            try:
                import ast
                parsed = ast.literal_eval(form_str)
                if isinstance(parsed, list):
                    return [str(x).strip().upper() for x in parsed if x]  # type: ignore[union-attr]
            except (ValueError, SyntaxError):
                pass
        
        # Format: "W-L-D" lub "W,L,D"
        for sep in ['-', ',', ' ', ';']:
            if sep in form_str:
                return [x.strip().upper() for x in form_str.split(sep) if x.strip()]
        
        # Format: "WLDWD" - pojedyncze znaki
        if all(c.upper() in 'WLD' for c in form_str if c.strip()):
            return [c.upper() for c in form_str if c.upper() in 'WLD']
    
    return []


def format_odds_value(val: Any) -> str:
    """
    Formatuje wartość kursu do wyświetlenia.
    """
    if is_nan_or_none(val):
        return '—'
    try:
        f = float(val)
        if math.isnan(f) or f <= 0:
            return '—'
        return f'{f:.2f}'
    except (ValueError, TypeError):
        return '—'


def has_valid_odds(match: Dict[str, Any]) -> bool:
    """
    Sprawdza czy mecz ma przynajmniej jeden ważny kurs.
    """
    home = safe_float(match.get('home_odds'))
    away = safe_float(match.get('away_odds'))
    return home > 0 or away > 0


def _render_team_logos_row(home_logo: str, away_logo: str, home_name: str, away_name: str) -> str:
    """Render an optional row of team badge images above the team names line."""
    if not home_logo and not away_logo:
        return ''
    parts: list[str] = []
    if home_logo:
        parts.append(
            f'<img src="{home_logo}" alt="{home_name}" width="36" height="36" '
            f'style="border-radius:50%;object-fit:contain;background:#f5f5f5;" '
            f'onerror="this.style.display=\'none\'">'
        )
    else:
        parts.append('<span style="display:inline-block;width:36px;"></span>')
    parts.append('<span style="display:inline-block;width:24px;"></span>')
    if away_logo:
        parts.append(
            f'<img src="{away_logo}" alt="{away_name}" width="36" height="36" '
            f'style="border-radius:50%;object-fit:contain;background:#f5f5f5;" '
            f'onerror="this.style.display=\'none\'">'
        )
    else:
        parts.append('<span style="display:inline-block;width:36px;"></span>')
    return f'<div style="margin-bottom:8px;">{"".join(parts)}</div>'


def _clean_odds_for_render(val: Any) -> Optional[float]:
    """
    Czyści wartość kursu przed renderowaniem - zamienia string 'nan' na None.
    Obsługuje: None, string 'nan', float NaN, pandas NaN, numpy NaN.
    """
    if val is None:
        return None
    
    # Sprawdź pandas/numpy NaN
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    
    if isinstance(val, str):
        if val.lower() == 'nan' or val.lower() == 'none' or val.strip() == '':
            return None
        try:
            return float(val)
        except ValueError:
            return None
    if isinstance(val, float):
        if math.isnan(val):
            return None
        return val
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _sofascore_status(match: Dict[str, Any]) -> Optional[bool]:
    """Zwróć tri-state status SofaScore dla rekordu meczu.

    - ``True``  — scraper próbował i znalazł dane (mogą być częściowe);
    - ``False`` — scraper próbował i jawnie nie znalazł (placeholder w mailu);
    - ``None``  — nie wiemy (legacy CSV/dict bez kolumny ``sofascore_found``).

    Czytane jest pole ``match['sofascore_found']``; akceptujemy wartości
    bool, stringi ``'true'/'false'/'nan'/'none'`` i ``None``/NaN, bo CSV
    często serializuje wszystko do stringa.
    """
    raw = match.get('sofascore_found')
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    try:
        if pd.isna(raw):  # type: ignore[arg-type]
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ('true', '1', 'yes'):
            return True
        if s in ('false', '0', 'no'):
            return False
        if s in ('', 'nan', 'none'):
            return None
    if isinstance(raw, (int, float)):
        try:
            if math.isnan(float(raw)):
                return None
        except (TypeError, ValueError):
            pass
        return bool(raw)
    return None


def _summarize_sofascore_coverage(matches: List[Dict[str, Any]]) -> Dict[str, int]:
    """Podlicz pokrycie SofaScore Fan Vote w paczce meczów wysyłanych mailem.

    Zwraca słownik z licznikami:
    - ``with_data``     — sekcja Fan Vote będzie wyrenderowana z liczbami,
    - ``placeholder``   — sekcja będzie pokazana jako "brak danych" (sofascore_found=False),
    - ``hidden``        — sekcja będzie cicho ukryta (legacy, brak sofascore_found).
    Plus rozbicie ``skip_reasons`` (np. ``not_found=12``).

    Logujemy to przed wysyłką, żeby od razu wiedzieć, czy problem leży w
    scraperze (mass ``placeholder``/``not_found``) czy w starym CSV bez
    flagi (mass ``hidden``).
    """
    counts = {"with_data": 0, "placeholder": 0, "hidden": 0}
    skip_reasons: Dict[str, int] = {}
    for m in matches:
        h, d, a, v = _sofascore_from_match(m)
        has_data = h is not None or d is not None or a is not None or v > 0
        if has_data:
            counts["with_data"] += 1
            continue
        status = _sofascore_status(m)
        if status is False:
            counts["placeholder"] += 1
            reason = m.get("sofascore_skip_reason") or "unknown"
            if isinstance(reason, float):
                try:
                    if math.isnan(reason):
                        reason = "unknown"
                except (TypeError, ValueError):
                    pass
            key = str(reason).split(":", 1)[0]
            skip_reasons[key] = skip_reasons.get(key, 0) + 1
        else:
            counts["hidden"] += 1
    if skip_reasons:
        counts["_skip_reasons"] = skip_reasons  # type: ignore[assignment]
    return counts


def _log_sofascore_coverage(matches: List[Dict[str, Any]], label: str = "") -> None:
    """Wypisz na stdout zwięzłe podsumowanie pokrycia SofaScore.

    Cel: gdy użytkownik raportuje "nie ma sofascore fan vote w mailu",
    od razu po logach widać, czy to problem braku danych (scraper) czy
    błędnego mapowania (legacy hidden).
    """
    if not matches:
        return
    summary = _summarize_sofascore_coverage(matches)
    total = len(matches)
    prefix = f"   🗳️ SofaScore Fan Vote{f' [{label}]' if label else ''}:"
    print(
        f"{prefix} {summary['with_data']}/{total} z danymi"
        f" | {summary['placeholder']} placeholder (próbowano, brak)"
        f" | {summary['hidden']} ukryte (legacy)"
    )
    skip = summary.get("_skip_reasons")
    if isinstance(skip, dict) and skip:
        parts = [f"{k}={v}" for k, v in sorted(skip.items())]
        print(f"      ↳ skip_reasons: {', '.join(parts)}")


def _sofascore_from_match(match: Dict[str, Any]) -> tuple:
    """Zwróć (home, draw, away, votes) dla bloku Fan Vote w mailu.

    Najpierw bierze płaskie pola (`sofascore_home_win_prob`, …), a w razie
    braku — sięga do zagnieżdżonego ``match['sofascore']`` (klucze ``home`` /
    ``draw`` / ``away`` / ``votes``), żeby zachować spójność z kontraktem
    używanym w :mod:`api_server` i artefaktach JSON. ``sofascore`` może być
    słownikiem albo stringiem JSON (po round-tripie przez CSV).
    """
    flat_home = match.get('sofascore_home_win_prob')
    if is_nan_or_none(flat_home):
        flat_home = match.get('sofascore_home')
    flat_draw = match.get('sofascore_draw_prob')
    if is_nan_or_none(flat_draw):
        flat_draw = match.get('sofascore_draw')
    flat_away = match.get('sofascore_away_win_prob')
    if is_nan_or_none(flat_away):
        flat_away = match.get('sofascore_away')
    flat_votes = match.get('sofascore_total_votes')
    if is_nan_or_none(flat_votes):
        flat_votes = match.get('sofascore_votes')

    nested_raw = match.get('sofascore')
    nested: Dict[str, Any] = {}
    if isinstance(nested_raw, dict):
        nested = nested_raw  # type: ignore[assignment]
    elif isinstance(nested_raw, str):
        s = nested_raw.strip()
        if s and s.lower() not in ('nan', 'none'):
            try:
                parsed = json.loads(s.replace("'", '"'))
                if isinstance(parsed, dict):
                    nested = parsed  # type: ignore[assignment]
            except (json.JSONDecodeError, ValueError):
                nested = {}

    def _coalesce(flat: Any, key: str) -> Any:
        if not is_nan_or_none(flat):
            return flat
        return nested.get(key) if nested else None

    home_raw = _coalesce(flat_home, 'home')
    draw_raw = _coalesce(flat_draw, 'draw')
    away_raw = _coalesce(flat_away, 'away')
    votes_raw = _coalesce(flat_votes, 'votes')

    home = safe_float(home_raw) if not is_nan_or_none(home_raw) else None
    draw = safe_float(draw_raw) if not is_nan_or_none(draw_raw) else None
    away = safe_float(away_raw) if not is_nan_or_none(away_raw) else None
    votes = int(safe_float(votes_raw)) if not is_nan_or_none(votes_raw) else 0
    return home, draw, away, votes


def _canonical_pick_code(raw: Any) -> Optional[str]:
    """
    Normalizuj surowy typ modelu/Forebet do kodu '1' / 'X' / '2'.

    Akceptuje warianty używane w różnych silnikach: '1'/'H'/'1X' → '1',
    '2'/'A'/'X2' → '2', 'X' → 'X'. Zwraca None gdy wartość jest pusta
    lub nieznana, żeby wywołujący mógł pominąć linię „Typ modelu".
    """
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if not s or s in ('NONE', 'NAN'):
        return None
    if s in ('1', 'H', '1X'):
        return '1'
    if s in ('2', 'A', 'X2'):
        return '2'
    if s == 'X':
        return 'X'
    return None


def _pick_odds_value(pick: Optional[str], home_odds: Optional[float],
                     draw_odds: Optional[float], away_odds: Optional[float]) -> Optional[float]:
    """Zwróć kurs odpowiadający znormalizowanemu pickowi ('1'/'X'/'2')."""
    if pick == '1':
        return home_odds if home_odds and home_odds > 0 else None
    if pick == '2':
        return away_odds if away_odds and away_odds > 0 else None
    if pick == 'X':
        return draw_odds if draw_odds and draw_odds > 0 else None
    return None


def _render_model_pick_section(match: Dict[str, Any],
                               home_odds: Optional[float],
                               draw_odds: Optional[float],
                               away_odds: Optional[float],
                               is_tennis: bool) -> str:
    """
    Renderuj wyraźną linię „Typ modelu" z pickiem i odpowiadającym mu kursem.

    Pick pochodzi ze `scoring_pick` (lub `forebet_prediction` jako fallback),
    znormalizowany przez :func:`_canonical_pick_code`. Dzięki temu użytkownik
    widzi jasną rekomendację zamiast domyślać się jej z kolorowania sekcji
    kursów (gdzie zielony = najniższy kurs, a nie typ modelu).
    """
    pick = _canonical_pick_code(match.get('scoring_pick'))
    source = 'Scoring'
    if pick is None:
        pick = _canonical_pick_code(match.get('forebet_prediction'))
        source = 'Forebet'
    if pick is None:
        return ''

    home = safe_value(match.get('home_team'), '')
    away = safe_value(match.get('away_team'), '')
    if is_tennis:
        pick_labels = {'1': f'Gracz 1 — {home}' if home else 'Gracz 1',
                       '2': f'Gracz 2 — {away}' if away else 'Gracz 2',
                       'X': 'Remis (X)'}
    else:
        pick_labels = {'1': f'Gospodarze (1) — {home}' if home else 'Gospodarze (1)',
                       '2': f'Goście (2) — {away}' if away else 'Goście (2)',
                       'X': 'Remis (X)'}
    label = pick_labels.get(pick, pick)

    odds_val = _pick_odds_value(pick, home_odds, draw_odds, away_odds)
    odds_str = f'@ {odds_val:.2f}' if odds_val else ''

    return f'''
    <div style="margin-bottom: 12px; padding: 12px; background: linear-gradient(135deg, #1b5e20 0%, #2e7d32 100%); border-radius: 8px; color: white;">
        <div style="font-size: 11px; color: rgba(255,255,255,0.75); margin-bottom: 4px;">🎯 Typ modelu ({source})</div>
        <div style="font-size: 18px; font-weight: 700;">{pick} — {label} <span style="color: #ffd740;">{odds_str}</span></div>
    </div>
    '''


def _render_odds_section(home_odds: Optional[float], draw_odds: Optional[float], away_odds: Optional[float]) -> str:
    """
    Renderuje sekcję kursów w HTML.
    """
    # 🔧 Czyść wartości przed renderowaniem - zamień string 'nan' na None
    home_odds = _clean_odds_for_render(home_odds)
    draw_odds = _clean_odds_for_render(draw_odds)
    away_odds = _clean_odds_for_render(away_odds)
    
    # Zbierz wszystkie ważne kursy
    valid_odds: List[float] = []
    if home_odds is not None and home_odds > 0:
        valid_odds.append(home_odds)
    if draw_odds is not None and draw_odds > 0:
        valid_odds.append(draw_odds)
    if away_odds is not None and away_odds > 0:
        valid_odds.append(away_odds)
    
    if not valid_odds:
        return ''
    
    min_odds = min(valid_odds)
    
    # Formatuj wartości
    home_str = f'{home_odds:.2f}' if home_odds and home_odds > 0 else '—'
    draw_str = f'{draw_odds:.2f}' if draw_odds and draw_odds > 0 else None
    away_str = f'{away_odds:.2f}' if away_odds and away_odds > 0 else '—'
    
    # Sprawdź które jest minimalne (faworytem)
    home_is_min = home_odds is not None and home_odds > 0 and home_odds == min_odds
    draw_is_min = draw_odds is not None and draw_odds > 0 and draw_odds == min_odds
    away_is_min = away_odds is not None and away_odds > 0 and away_odds == min_odds
    
    html = '''
    <div style="margin-bottom: 12px; padding: 10px; background: white; border-radius: 8px;">
        <div style="font-size: 11px; color: #666; margin-bottom: 4px;">💰 Kursy bukmacherskie</div>
        <div style="font-size: 10px; color: #999; margin-bottom: 8px;">Zielone podświetlenie = najniższy kurs (faworyt bukmachera), nie typ modelu</div>
        <div style="display: flex; justify-content: space-around;">
    '''
    
    # Home odds
    home_bg = '#4CAF50' if home_is_min else '#f5f5f5'
    home_color = 'white' if home_is_min else '#333'
    html += f'''
            <div style="text-align: center; padding: 5px 15px; background: {home_bg}; border-radius: 8px;">
                <div style="font-size: 16px; font-weight: bold; color: {home_color};">{home_str}</div>
                <div style="font-size: 10px; color: {home_color if home_is_min else '#888'};">1</div>
            </div>
    '''
    
    # Draw odds (tylko jeśli istnieje)
    if draw_str:
        draw_bg = '#4CAF50' if draw_is_min else '#f5f5f5'
        draw_color = 'white' if draw_is_min else '#333'
        html += f'''
            <div style="text-align: center; padding: 5px 15px; background: {draw_bg}; border-radius: 8px;">
                <div style="font-size: 16px; font-weight: bold; color: {draw_color};">{draw_str}</div>
                <div style="font-size: 10px; color: {draw_color if draw_is_min else '#888'};">X</div>
            </div>
        '''
    
    # Away odds
    away_bg = '#4CAF50' if away_is_min else '#f5f5f5'
    away_color = 'white' if away_is_min else '#333'
    html += f'''
            <div style="text-align: center; padding: 5px 15px; background: {away_bg}; border-radius: 8px;">
                <div style="font-size: 16px; font-weight: bold; color: {away_color};">{away_str}</div>
                <div style="font-size: 10px; color: {away_color if away_is_min else '#888'};">2</div>
            </div>
        </div>
    </div>
    '''
    
    return html


def _render_forebet_section(fb_pred: Optional[str], fb_prob: Optional[float], fb_exact: Optional[str]) -> str:
    """
    Renderuje sekcję predykcji Forebet w HTML.
    """
    # 🔧 Czyść wartości - zamień string 'nan' na None
    if isinstance(fb_pred, str) and fb_pred.lower() == 'nan':
        fb_pred = None
    if isinstance(fb_exact, str) and fb_exact.lower() == 'nan':
        fb_exact = None
    fb_prob = _clean_odds_for_render(fb_prob)  # Reuse helper function
    
    if not fb_pred or fb_prob is None or fb_prob <= 0:
        return ''
    
    html = f'''
    <div style="padding: 15px; background: linear-gradient(135deg, #FF9800, #FF5722); border-radius: 10px; box-shadow: 0 2px 8px rgba(255,87,34,0.3);">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <div style="font-size: 14px; font-weight: bold; color: rgba(255,255,255,0.9); text-shadow: 1px 1px 2px rgba(0,0,0,0.3);">🎯 Forebet</div>
                <div style="font-size: 32px; font-weight: bold; color: white; text-shadow: 1px 1px 3px rgba(0,0,0,0.3);">{fb_pred}</div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 14px; font-weight: bold; color: rgba(255,255,255,0.9); text-shadow: 1px 1px 2px rgba(0,0,0,0.3);">Prawdopodobieństwo</div>
                <div style="font-size: 36px; font-weight: bold; color: white; text-shadow: 1px 1px 3px rgba(0,0,0,0.3);">{fb_prob:.0f}%</div>
            </div>
    '''
    
    if fb_exact:
        html += f'''
            <div style="background: rgba(255,255,255,0.25); padding: 8px 14px; border-radius: 8px;">
                <div style="font-size: 12px; font-weight: bold; color: rgba(255,255,255,0.9); text-shadow: 1px 1px 2px rgba(0,0,0,0.3);">Wynik</div>
                <div style="font-size: 22px; font-weight: bold; color: white; text-shadow: 1px 1px 3px rgba(0,0,0,0.3);">{fb_exact}</div>
            </div>
        '''
    
    html += '''
        </div>
    </div>
    '''
    
    return html


# ============================================================================
# SORTED ODDS SECTIONS - Pre-posortowane kursy w emailu
# ============================================================================

def create_sorted_odds_sections(matches: List[Dict[str, Any]], limit: int = 15) -> str:
    """
    Tworzy HTML sekcje z meczami posortowanymi po kursach (od najwyższych).
    
    Args:
        matches: Lista meczów z kursami
        limit: Max liczba meczów w każdej sekcji (default 15)
    
    Returns:
        HTML string z trzema sekcjami: Home Odds, Draw Odds, Away Odds
    """
    # Filtruj mecze z kursami - używaj globalnej funkcji has_valid_odds
    matches_with_odds = [m for m in matches if has_valid_odds(m)]
    
    if not matches_with_odds:
        return ""
    
    def get_time_str(match: Dict[str, Any]) -> str:
        """Wyciąga godzinę meczu."""
        match_time = match.get('match_time', '')
        if match_time:
            time_match = re.search(r'(\d{1,2}:\d{2})', str(match_time))
            if time_match:
                return time_match.group(1)
        return ''
    
    # Sortuj po home_odds (malejąco)
    by_home = sorted(
        [m for m in matches_with_odds if safe_float(m.get('home_odds')) > 0],
        key=lambda x: safe_float(x.get('home_odds')),
        reverse=True
    )[:limit]
    
    # Sortuj po draw_odds (malejąco) - tylko dla sportów z remisami
    by_draw = sorted(
        [m for m in matches_with_odds if safe_float(m.get('draw_odds')) > 0],
        key=lambda x: safe_float(x.get('draw_odds')),
        reverse=True
    )[:limit]
    
    # Sortuj po away_odds (malejąco)
    by_away = sorted(
        [m for m in matches_with_odds if safe_float(m.get('away_odds')) > 0],
        key=lambda x: safe_float(x.get('away_odds')),
        reverse=True
    )[:limit]
    
    html = """
    <div class="odds-sections-container">
        <div class="odds-sections-header">
            💰 KURSY POSORTOWANE (od najwyższych) 💰
        </div>
    """
    
    # Sekcja HOME ODDS
    if by_home:
        html += """
        <div class="odds-section">
            <div class="odds-section-title">🏠 Kursy na GOSPODARZY (1)</div>
            <table class="odds-table">
                <tr class="odds-table-header">
                    <th>#</th>
                    <th>Mecz</th>
                    <th>Godz.</th>
                    <th>Kurs</th>
                </tr>
        """
        for i, m in enumerate(by_home, 1):
            home = m.get('home_team', 'N/A')
            away = m.get('away_team', 'N/A')
            odds = safe_float(m.get('home_odds'))
            time_str = get_time_str(m)
            html += f"""
                <tr>
                    <td class="rank">{i}</td>
                    <td class="teams">{home} vs {away}</td>
                    <td class="time">{time_str}</td>
                    <td class="odds-value">{odds:.2f}</td>
                </tr>
            """
        html += """
            </table>
        </div>
        """
    
    # Sekcja DRAW ODDS (tylko jeśli są remisy)
    if by_draw:
        html += """
        <div class="odds-section">
            <div class="odds-section-title">🤝 Kursy na REMIS (X)</div>
            <table class="odds-table">
                <tr class="odds-table-header">
                    <th>#</th>
                    <th>Mecz</th>
                    <th>Godz.</th>
                    <th>Kurs</th>
                </tr>
        """
        for i, m in enumerate(by_draw, 1):
            home = m.get('home_team', 'N/A')
            away = m.get('away_team', 'N/A')
            odds = safe_float(m.get('draw_odds'))
            time_str = get_time_str(m)
            html += f"""
                <tr>
                    <td class="rank">{i}</td>
                    <td class="teams">{home} vs {away}</td>
                    <td class="time">{time_str}</td>
                    <td class="odds-value">{odds:.2f}</td>
                </tr>
            """
        html += """
            </table>
        </div>
        """
    
    # Sekcja AWAY ODDS
    if by_away:
        html += """
        <div class="odds-section">
            <div class="odds-section-title">✈️ Kursy na GOŚCI (2)</div>
            <table class="odds-table">
                <tr class="odds-table-header">
                    <th>#</th>
                    <th>Mecz</th>
                    <th>Godz.</th>
                    <th>Kurs</th>
                </tr>
        """
        for i, m in enumerate(by_away, 1):
            home = m.get('home_team', 'N/A')
            away = m.get('away_team', 'N/A')
            odds = safe_float(m.get('away_odds'))
            time_str = get_time_str(m)
            html += f"""
                <tr>
                    <td class="rank">{i}</td>
                    <td class="teams">{home} vs {away}</td>
                    <td class="time">{time_str}</td>
                    <td class="odds-value">{odds:.2f}</td>
                </tr>
            """
        html += """
            </table>
        </div>
        """
    
    html += """
    </div>
    """
    
    return html


# CSS dla sekcji kursów
ODDS_SECTIONS_CSS = """
    .odds-sections-container {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 12px;
        padding: 25px;
        margin: 25px 0;
        box-shadow: 0 10px 30px rgba(0,0,0,0.3);
    }
    .odds-sections-header {
        color: #ffd700;
        font-size: 24px;
        font-weight: bold;
        text-align: center;
        margin-bottom: 25px;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
        letter-spacing: 1px;
    }
    .odds-section {
        background: rgba(255,255,255,0.05);
        border-radius: 8px;
        padding: 15px;
        margin: 15px 0;
        border: 1px solid rgba(255,255,255,0.1);
    }
    .odds-section-title {
        color: #00d4ff;
        font-size: 18px;
        font-weight: bold;
        margin-bottom: 15px;
        padding-bottom: 10px;
        border-bottom: 2px solid rgba(0,212,255,0.3);
    }
    .odds-table {
        width: 100%;
        border-collapse: collapse;
        color: #fff;
    }
    .odds-table-header th {
        background: rgba(0,212,255,0.2);
        color: #00d4ff;
        padding: 10px 8px;
        text-align: left;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .odds-table tr:nth-child(even) {
        background: rgba(255,255,255,0.03);
    }
    .odds-table tr:hover {
        background: rgba(0,212,255,0.1);
    }
    .odds-table td {
        padding: 10px 8px;
        border-bottom: 1px solid rgba(255,255,255,0.05);
    }
    .odds-table .rank {
        color: #ffd700;
        font-weight: bold;
        width: 30px;
        text-align: center;
    }
    .odds-table .teams {
        color: #fff;
        font-weight: 500;
    }
    .odds-table .time {
        color: #aaa;
        font-size: 13px;
        width: 60px;
    }
    .odds-table .odds-value {
        color: #00ff88;
        font-weight: bold;
        font-size: 16px;
        text-align: right;
        width: 70px;
    }
"""

# Konfiguracja SMTP
SMTP_CONFIG: Dict[str, Dict[str, Any]] = {
    'gmail': {
        'server': 'smtp.gmail.com',
        'port': 587,
        'use_tls': True
    },
    'outlook': {
        'server': 'smtp-mail.outlook.com',
        'port': 587,
        'use_tls': True
    },
    'yahoo': {
        'server': 'smtp.mail.yahoo.com',
        'port': 587,
        'use_tls': True
    }
}

def create_html_email(matches: List[Dict[str, Any]], date: str, sort_by: str = 'time', 
                      include_sorted_odds: bool = False, odds_limit: int = 15) -> str:
    """
    Tworzy ładny HTML email z listą meczów
    
    Args:
        matches: Lista meczów
        date: Data
        sort_by: 'time' (godzina), 'wins' (liczba wygranych), 'team' (alfabetycznie)
        include_sorted_odds: Parametr zachowany dla kompatybilności; sekcje kursów nie są już renderowane w mailu
        odds_limit: Parametr zachowany dla kompatybilności; nie wpływa już na HTML maila
    """
    
    # SORTOWANIE MECZÓW
    sorted_matches = matches.copy()
    
    if sort_by == 'time':
        # Sortuj po godzinie meczu
        def get_time_key(match: Dict[str, Any]) -> str:
            match_time = match.get('match_time', '')
            if not match_time:
                return '99:99'  # Mecze bez czasu na końcu
            
            # Wyciągnij godzinę z różnych formatów
            # Format: DD.MM.YYYY HH:MM lub HH:MM
            time_match = re.search(r'(\d{1,2}:\d{2})', match_time)
            if time_match:
                return time_match.group(1)
            return '99:99'
        
        sorted_matches = sorted(sorted_matches, key=get_time_key)
    
    elif sort_by == 'wins':
        # Sortuj po liczbie wygranych (malejąco) - uwzględnij tryb away_team_focus
        def get_wins(match: Dict[str, Any]) -> Any:
            focus_team = match.get('focus_team', 'home')
            if focus_team == 'away':
                return match.get('away_wins_in_h2h_last5', 0)
            else:
                return match.get('home_wins_in_h2h_last5', 0)
        sorted_matches = sorted(sorted_matches, key=get_wins, reverse=True)
    
    elif sort_by == 'team':
        # Sortuj alfabetycznie po nazwie gospodarzy
        sorted_matches = sorted(sorted_matches, key=lambda x: x.get('home_team', '').lower())
    
    html = f"""
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
            }}
            .header {{
                background-color: #4CAF50;
                color: white;
                padding: 20px;
                text-align: center;
            }}
            .content {{
                padding: 20px;
            }}
            .match {{
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 15px;
                margin: 10px 0;
                background-color: #f9f9f9;
            }}
            .match-title {{
                font-size: 18px;
                font-weight: bold;
                color: #2196F3;
            }}
            .match-details {{
                margin: 5px 0;
                color: #666;
            }}
            .match-time {{
                font-size: 20px;
                color: #FF5722;
                font-weight: bold;
            }}
            .stats {{
                background-color: #fff3cd;
                padding: 10px;
                border-radius: 3px;
                margin-top: 10px;
            }}
            .footer {{
                text-align: center;
                padding: 20px;
                color: #888;
                font-size: 12px;
            }}
            .h2h-record {{
                color: #4CAF50;
                font-weight: bold;
            }}
            .time-badge {{
                display: inline-block;
                background-color: #FF5722;
                color: white;
                padding: 5px 10px;
                border-radius: 3px;
                margin-right: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🏆 Kwalifikujące się mecze - {date}</h1>
            <p>🎾 Tennis: Advanced scoring (≥45/100) | ⚽ Drużynowe: Gospodarze wygrali ≥60% H2H</p>
            <p style="font-size: 14px; margin-top: 10px;">🤖 <strong>Gemini AI Analysis</strong> | ⏰ Posortowane chronologicznie</p>
        </div>
        
        <div class="content">
    """
    
    # ========================================================================
    # REGULAR MATCHES SECTION
    # ========================================================================
    html += f"""
            <p style="margin-top: 30px;">Znaleziono <strong>{len(sorted_matches)}</strong> kwalifikujących się meczów:</p>
    """
    
    for i, match in enumerate(sorted_matches, 1):
        home = match.get('home_team', 'N/A')
        away = match.get('away_team', 'N/A')
        
        focus_team = match.get('focus_team', 'home')
        match_time = match.get('match_time', 'Brak danych')
        match_url = match.get('match_url', '#')
        
        time_badge = ''
        if match_time and match_time != 'Brak danych':
            time_match = re.search(r'(\d{1,2}:\d{2})', match_time)
            if time_match:
                time_badge = time_match.group(1)
        
        # ========== KOMPAKTOWA KARTA MECZU Z IKONAMI ==========
        # Zbierz wszystkie dane w jednym miejscu - UŻYWAMY BEZPIECZNYCH FUNKCJI
        
        # FORMA - parsuj z różnych formatów (string/lista)
        home_form_overall = parse_form_list(match.get('home_form_overall', match.get('home_form', [])))
        home_form_home = parse_form_list(match.get('home_form_home', []))
        away_form_overall = parse_form_list(match.get('away_form_overall', match.get('away_form', [])))
        away_form_away = parse_form_list(match.get('away_form_away', []))
        form_advantage = bool(match.get('form_advantage', False))
        last_meeting_date = safe_value(match.get('last_meeting_date', match.get('last_h2h_date', '')), '—')
        last_h2h_score = safe_value(match.get('last_h2h_score', ''), '')
        last_h2h_home = safe_value(match.get('last_h2h_home', ''), '')
        last_h2h_away = safe_value(match.get('last_h2h_away', ''), '')
        
        def form_to_icons(form_list: List[str]) -> str:
            """Konwertuje listę wyników na ikony emoji."""
            icons = {'W': '🟢', 'L': '🔴', 'D': '🟡'}
            if not form_list:
                return '—'
            return ''.join([icons.get(str(r).upper(), '⚪') for r in form_list[:5]])
        
        # H2H - bezpieczne pobieranie liczb
        h2h_count = int(safe_float(match.get('h2h_count', 0)))
        win_rate = safe_float(match.get('win_rate', 0.0))
        if focus_team == 'away':
            wins = int(safe_float(match.get('away_wins_in_h2h_last5', 0)))
        else:
            wins = int(safe_float(match.get('home_wins_in_h2h_last5', 0)))
        
        # SofaScore - jednolita ekstrakcja z płaskich pól lub zagnieżdżonego dict
        ss_home, ss_draw, ss_away, ss_votes = _sofascore_from_match(match)
        # Flaga: pokaż SofaScore jeśli DOWOLNA wartość jest dostępna (home/away/draw/votes)
        has_sofascore = (ss_home is not None or ss_away is not None or 
                         ss_draw is not None or ss_votes > 0)
        _ss_draw_color = '#FFC107' if (ss_draw is not None and ss_draw >= max(ss_home or 0, ss_draw or 0, ss_away or 0)) else '#333'
        # Tri-state: rozróżnij "nie próbowano" vs "próbowano i nie znaleziono".
        # Gdy scraper jawnie zwrócił sofascore_found=False i nie mamy żadnej
        # wartości, pokazujemy mały placeholder zamiast cicho ukrywać sekcję
        # — żeby użytkownik widział, że SofaScore był sprawdzany, ale brak danych.
        ss_status = _sofascore_status(match)
        ss_skip_reason = match.get('sofascore_skip_reason')
        if isinstance(ss_skip_reason, float):
            try:
                if math.isnan(ss_skip_reason):
                    ss_skip_reason = None
            except (TypeError, ValueError):
                pass
        show_sofascore_placeholder = (not has_sofascore) and (ss_status is False)
        
        # Odds - bezpieczne pobieranie z obsługą NaN
        home_odds_raw = match.get('home_odds')
        draw_odds_raw = match.get('draw_odds')
        away_odds_raw = match.get('away_odds')
        
        home_odds = safe_float(home_odds_raw) if not is_nan_or_none(home_odds_raw) else None
        draw_odds = safe_float(draw_odds_raw) if not is_nan_or_none(draw_odds_raw) else None
        away_odds = safe_float(away_odds_raw) if not is_nan_or_none(away_odds_raw) else None
        
        # Sprawdź czy mamy ważne kursy do wyświetlenia
        has_odds = (home_odds is not None and home_odds > 0) or (away_odds is not None and away_odds > 0)
        
        # Forebet - bezpieczne pobieranie
        fb_pred = safe_value(match.get('forebet_prediction'), None)
        fb_prob_raw = match.get('forebet_probability')
        fb_prob = safe_float(fb_prob_raw) if not is_nan_or_none(fb_prob_raw) else None
        fb_exact = safe_value(match.get('forebet_exact_score'), None)
        
        # SCORING ENGINE - bezpieczne pobieranie
        sc_pick = safe_value(match.get('scoring_pick'), None)
        sc_prob_raw = match.get('scoring_prob')
        sc_prob = safe_float(sc_prob_raw) if not is_nan_or_none(sc_prob_raw) else None
        sc_ev_raw = match.get('scoring_ev')
        sc_ev = safe_float(sc_ev_raw) if not is_nan_or_none(sc_ev_raw) else None
        sc_edge_raw = match.get('scoring_edge')
        sc_edge = safe_float(sc_edge_raw) if not is_nan_or_none(sc_edge_raw) else None
        sc_kelly_raw = match.get('scoring_kelly')
        sc_kelly = safe_float(sc_kelly_raw) if not is_nan_or_none(sc_kelly_raw) else None
        sc_conf_raw = match.get('scoring_confidence')
        sc_conf = safe_float(sc_conf_raw) if not is_nan_or_none(sc_conf_raw) else None
        sc_ph_raw = match.get('scoring_prob_home')
        sc_ph = safe_float(sc_ph_raw) if not is_nan_or_none(sc_ph_raw) else None
        sc_pd_raw = match.get('scoring_prob_draw')
        sc_pd = safe_float(sc_pd_raw) if not is_nan_or_none(sc_pd_raw) else None
        sc_pa_raw = match.get('scoring_prob_away')
        sc_pa = safe_float(sc_pa_raw) if not is_nan_or_none(sc_pa_raw) else None
        # Tennis scoring: prob_a / prob_b (no draw)
        sc_tpa_raw = match.get('scoring_prob_a')
        sc_tpa = safe_float(sc_tpa_raw) if not is_nan_or_none(sc_tpa_raw) else None
        sc_tpb_raw = match.get('scoring_prob_b')
        sc_tpb = safe_float(sc_tpb_raw) if not is_nan_or_none(sc_tpb_raw) else None
        # Pokaż blok Scoring Engine, jeśli dostępny jest choć pick lub prob.
        # Brakujące pola renderują się jako "—", więc użytkownik nie widzi
        # dziury w miejsce promowanej rekomendacji.
        has_scoring = sc_pick is not None or sc_prob is not None
        sc_prob_str = f"{sc_prob:.0f}%" if sc_prob is not None else "—"
        sc_pick_str = sc_pick if sc_pick is not None else "—"
        
        # AI PREDICTION PRO - bezpieczne pobieranie
        ai_pred = ensure_ai_prediction_dict(match.get('ai_prediction'))
        ai_pick = ai_pred.get('pick')
        ai_pick_label = ai_pred.get('pickLabel', '')
        ai_conf = ai_pred.get('compositeConfidence')
        ai_tier = ai_pred.get('confidenceTier', '')
        ai_full_verdict = ai_pred.get('verdict', '')
        ai_consensus = ai_pred.get('consensus', {})
        ai_risk = ai_pred.get('risk', {})
        ai_value = ai_pred.get('valueRating', '')
        ai_ev = ai_pred.get('ev')
        ai_edge = ai_pred.get('edge')
        ai_args_for = ai_pred.get('keyArgumentsFor', [])
        ai_args_against = ai_pred.get('keyArgumentsAgainst', [])
        ai_dnb = ai_pred.get('doNotBetReasons', [])
        ai_dq = ai_pred.get('dataQualityLabel', '')
        has_ai_pred = ai_pick is not None and ai_conf is not None
        
        # AI Prediction tier color mapping
        _ai_tier_colors = {
            'VERY HIGH': ('#00e676', '#1b5e20'),
            'HIGH': ('#69f0ae', '#1b5e20'),
            'MEDIUM': ('#ffd740', '#4e3800'),
            'LOW': ('#ff9100', '#4e2600'),
            'VERY LOW': ('#ff5252', '#4a0000'),
        }
        _ai_risk_colors = {'LOW': '#69f0ae', 'MEDIUM': '#ffd740', 'HIGH': '#ff5252'}
        _ai_value_colors = {'EXCELLENT': '#00e676', 'GOOD': '#69f0ae', 'FAIR': '#ffd740', 'NONE': '#ff5252'}
        _ai_tc = _ai_tier_colors.get(ai_tier, ('#9e9e9e', '#333'))
        
        # TENNIS-SPECIFIC: Wykryj czy to tenis (po polu sport lub URL)
        is_tennis = (match.get('sport') == 'tennis' or 
                     '/tenis/' in str(match.get('match_url', '')).lower() or
                     '/tennis/' in str(match.get('match_url', '')).lower())
        
        # Tennis: Pobierz ranking i advanced score
        ranking_a = match.get('ranking_a')
        ranking_b = match.get('ranking_b')
        advanced_score = safe_float(match.get('advanced_score', 0))
        favorite = match.get('favorite', 'unknown')
        ranking_info = match.get('ranking_info', '')
        
        html += f"""
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; margin: 15px 0; box-shadow: 0 4px 15px rgba(0,0,0,0.2); overflow: hidden;">
                <!-- HEADER -->
                <div style="padding: 15px 20px; background: rgba(255,255,255,0.1); display: flex; justify-content: space-between; align-items: center;">
                    <div style="color: white; font-size: 12px;">
                        <span style="background: #FF5722; padding: 5px 12px; border-radius: 15px; font-weight: bold;">🕐 {time_badge.replace('<span class="time-badge">', '').replace('</span>', '') if time_badge else 'TBD'}</span>
                    </div>
                    <div style="color: white; font-size: 11px; opacity: 0.8;">
                        #{i}
                    </div>
                </div>
                
                <!-- DRUŻYNY -->
                <div style="background: white; padding: 20px; text-align: center;">
                    {_render_team_logos_row(match.get('home_logo_url', ''), match.get('away_logo_url', ''), home, away)}
                    <div style="font-size: 22px; font-weight: bold; color: #333;">
                        {'🎾' if is_tennis else '🏠'} {home} <span style="color: #999; font-size: 16px;">vs</span> {away} {'🎾' if is_tennis else '✈️'}
                    </div>
                    {f'<div style="margin-top: 5px;"><span style="background: #FFD700; color: #333; padding: 3px 8px; border-radius: 10px; font-size: 11px; font-weight: bold;">🔥 Przewaga { "gości" if focus_team == "away" else "gospodarzy" }!</span></div>' if form_advantage and not is_tennis else ''}
                    {f'<div style="margin-top: 8px;"><span style="background: #4CAF50; color: white; padding: 4px 12px; border-radius: 15px; font-size: 12px; font-weight: bold;">🏆 Advanced Score: {advanced_score:.0f}/100</span></div>' if is_tennis and advanced_score > 0 else ''}
                    {f'<div style="margin-top: 5px; font-size: 12px; color: #666;">{ranking_info}</div>' if is_tennis and ranking_info else ''}
                </div>
                
                <!-- DANE MECZU - GRID -->
                <div style="background: #f8f9fa; padding: 15px 20px;">
                    
                    <!-- FORMA DRUŻYN -->
                    <div style="display: flex; justify-content: space-between; margin-bottom: 12px; padding: 10px; background: white; border-radius: 8px;">
                        <div style="flex: 1; text-align: center; border-right: 1px solid #eee;">
                            <div style="font-size: 11px; color: #666; margin-bottom: 5px;">📊 {home} (ogólna)</div>
                            <div style="font-size: 16px;">{form_to_icons(home_form_overall)}</div>
                            {f'<div style="font-size: 10px; color: #888; margin-top: 3px;">🏠 U siebie: {form_to_icons(home_form_home)}</div>' if home_form_home else ''}
                        </div>
                        <div style="flex: 1; text-align: center;">
                            <div style="font-size: 11px; color: #666; margin-bottom: 5px;">📊 {away} (ogólna)</div>
                            <div style="font-size: 16px;">{form_to_icons(away_form_overall)}</div>
                            {f'<div style="font-size: 10px; color: #888; margin-top: 3px;">✈️ Na wyjeździe: {form_to_icons(away_form_away)}</div>' if away_form_away else ''}
                        </div>
                    </div>
                    
                    <!-- TENNIS: RANKING SECTION -->
                    {f'''
                    <div style="display: flex; justify-content: space-between; margin-bottom: 12px; padding: 10px; background: linear-gradient(135deg, #2196F3 0%, #21CBF3 100%); border-radius: 8px;">
                        <div style="flex: 1; text-align: center; border-right: 1px solid rgba(255,255,255,0.3);">
                            <div style="font-size: 11px; color: rgba(255,255,255,0.8);">🏆 Ranking {home}</div>
                            <div style="font-size: 22px; font-weight: bold; color: white;">#{ranking_a if ranking_a else "?"}</div>
                        </div>
                        <div style="flex: 1; text-align: center;">
                            <div style="font-size: 11px; color: rgba(255,255,255,0.8);">🏆 Ranking {away}</div>
                            <div style="font-size: 22px; font-weight: bold; color: white;">#{ranking_b if ranking_b else "?"}</div>
                        </div>
                    </div>
                    ''' if is_tennis and (ranking_a or ranking_b) else ''}
                    
                    <!-- H2H + OSTATNI MECZ -->
                    <div style="display: flex; justify-content: space-between; margin-bottom: 12px; padding: 10px; background: white; border-radius: 8px;">
                        <div style="flex: 1; text-align: center; border-right: 1px solid #eee;">
                            <div style="font-size: 11px; color: #666;">🔄 H2H</div>
                            <div style="font-size: 18px; font-weight: bold; color: {'#4CAF50' if win_rate >= 0.6 else '#FF9800'};">
                                {f'{wins}/{h2h_count}' if h2h_count > 0 else '—'}
                            </div>
                            <div style="font-size: 12px; color: #888;">{f'{win_rate*100:.0f}%' if h2h_count > 0 else ''}</div>
                        </div>
                        <div style="flex: 1; text-align: center;">
                            <div style="font-size: 11px; color: #666;">{'🎾 Faworytem' if is_tennis else '📅 Ostatni mecz'}</div>
                            <div style="font-size: 14px; font-weight: bold; color: #333;">
                                {(home if favorite == 'player_a' else (away if favorite == 'player_b' else 'Równi')) if is_tennis else (f'{last_meeting_date} — {last_h2h_score}' if last_h2h_score else (last_meeting_date if last_meeting_date else '—'))}
                            </div>
                            {f'<div style="font-size: 10px; color: #888; margin-top: 2px;">🏠 {last_h2h_home} vs {last_h2h_away} ✈️</div>' if last_h2h_score and last_h2h_home and not is_tennis else ''}
                        </div>
                    </div>
                    
                    <!-- SOFASCORE FAN VOTES -->
                    {f'''
                    <div style="margin-bottom: 12px; padding: 10px; background: white; border-radius: 8px;">
                        <div style="font-size: 11px; color: #666; margin-bottom: 8px;">🗳️ SofaScore Fan Vote {f'({ss_votes} głosów)' if ss_votes else ''}</div>
                        <div style="display: flex; justify-content: space-around;">
                            <div style="text-align: center;">
                                <div style="font-size: 18px; font-weight: bold; color: {'#4CAF50' if ss_home and ss_home >= max(ss_home or 0, ss_draw or 0, ss_away or 0) else '#333'};">{ss_home}%</div>
                                <div style="font-size: 10px; color: #888;">🏠</div>
                            </div>
                            {f'<div style="text-align: center;"><div style="font-size: 18px; font-weight: bold; color: {_ss_draw_color};">{ss_draw}%</div><div style="font-size: 10px; color: #888;">🤝</div></div>' if ss_draw is not None else ''}
                            <div style="text-align: center;">
                                <div style="font-size: 18px; font-weight: bold; color: {'#F44336' if ss_away and ss_away >= max(ss_home or 0, ss_draw or 0, ss_away or 0) else '#333'};">{ss_away}%</div>
                                <div style="font-size: 10px; color: #888;">✈️</div>
                            </div>
                        </div>
                    </div>
                    ''' if has_sofascore else (f'''
                    <div style="margin-bottom: 12px; padding: 10px; background: #fff8e1; border: 1px dashed #ffc107; border-radius: 8px;">
                        <div style="font-size: 11px; color: #8a6d3b;">🗳️ SofaScore Fan Vote: brak danych{f" ({ss_skip_reason})" if ss_skip_reason else ""}</div>
                    </div>
                    ''' if show_sofascore_placeholder else '')}
                    
                    <!-- TYP MODELU (wyraźna rekomendacja) -->
                    {_render_model_pick_section(match, home_odds, draw_odds, away_odds, is_tennis)}

                    <!-- KURSY -->
                    {_render_odds_section(home_odds, draw_odds, away_odds) if has_odds else ''}
                    
                    <!-- FOREBET PREDICTION -->
                    {_render_forebet_section(fb_pred, fb_prob, fb_exact) if fb_pred and fb_prob is not None and fb_prob > 0 else ''}
                    
                    <!-- SCORING ENGINE -->
                    {f'''
                    <div style="margin-bottom: 12px; padding: 12px; background: linear-gradient(135deg, #1a237e 0%, #283593 100%); border-radius: 8px; color: white;">
                        <div style="font-size: 11px; color: rgba(255,255,255,0.8); margin-bottom: 8px;">{"🎾 Tennis Engine (5-factor)" if is_tennis else "🧠 Scoring Engine (7-source model)"}</div>
                        <div style="display: flex; justify-content: space-around; flex-wrap: wrap;">
                            <div style="text-align: center; min-width: 60px;">
                                <div style="font-size: 20px; font-weight: bold; color: #ffd740;">{sc_pick_str}</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.6);">TYP</div>
                            </div>
                            <div style="text-align: center; min-width: 60px;">
                                <div style="font-size: 20px; font-weight: bold;">{sc_prob_str}</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.6);">PROB</div>
                            </div>
                            <div style="text-align: center; min-width: 60px;">
                                <div style="font-size: 20px; font-weight: bold; color: {"#69f0ae" if sc_ev and sc_ev > 0 else "#ff5252"};">{f"+{sc_ev:.3f}" if sc_ev and sc_ev > 0 else f"{sc_ev:.3f}" if sc_ev else "—"}</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.6);">EV</div>
                            </div>
                            <div style="text-align: center; min-width: 60px;">
                                <div style="font-size: 20px; font-weight: bold; color: {"#69f0ae" if sc_edge and sc_edge > 0 else "#ff5252"};">{f"+{sc_edge:.1f}" if sc_edge and sc_edge > 0 else f"{sc_edge:.1f}" if sc_edge else "—"}%</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.6);">EDGE</div>
                            </div>
                            <div style="text-align: center; min-width: 60px;">
                                <div style="font-size: 20px; font-weight: bold;">{(sc_conf or 0):.0f}</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.6);">CONF</div>
                            </div>
                        </div>
                        <div style="margin-top: 8px; text-align: center; font-size: 10px; color: rgba(255,255,255,0.5);">
                            {f"A: {sc_tpa:.0f}% | B: {sc_tpb:.0f}%" if is_tennis and sc_tpa is not None and sc_tpb is not None else f"1: {sc_ph:.0f}% | X: {sc_pd:.0f}% | 2: {sc_pa:.0f}%" if sc_ph is not None and sc_pd is not None and sc_pa is not None else ""}
                            {f" | Kelly: {sc_kelly:.1f}%" if sc_kelly and sc_kelly > 0 else ""}
                        </div>
                        {f'<div style="margin-top: 6px; text-align: center;"><span style="background: #69f0ae; color: #1a237e; padding: 3px 10px; border-radius: 10px; font-size: 11px; font-weight: bold;">✅ VALUE BET</span></div>' if sc_ev and sc_ev > 0 else ""}
                    </div>
                    ''' if has_scoring else ''}
                    
                    {f'''
                    <!-- AI PREDICTION PRO -->
                    <div style="margin-top: 10px; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-radius: 12px; padding: 16px; border: 1px solid {_ai_tc[0]}33;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                            <div style="font-size: 11px; font-weight: 700; color: {_ai_tc[0]}; letter-spacing: 1px;">🤖 AI PREDICTION PRO</div>
                            <span style="background: {_ai_tc[0]}; color: {_ai_tc[1]}; padding: 2px 10px; border-radius: 10px; font-size: 10px; font-weight: 700;">{ai_tier}</span>
                        </div>
                        <div style="display: flex; justify-content: space-around; text-align: center; margin-bottom: 12px;">
                            <div>
                                <div style="font-size: 28px; font-weight: 800; color: {_ai_tc[0]};">{ai_pick}</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.5);">{ai_pick_label}</div>
                            </div>
                            <div>
                                <div style="font-size: 28px; font-weight: 800; color: white;">{ai_conf:.0f}%</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.5);">CONFIDENCE</div>
                            </div>
                            <div>
                                <div style="font-size: 28px; font-weight: 800; color: {_ai_risk_colors.get(ai_risk.get("level",""), "#999")};">{ai_risk.get("score", "?")}/10</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.5);">RISK</div>
                            </div>
                        </div>
                        <div style="display: flex; justify-content: space-around; text-align: center; margin-bottom: 10px; padding: 8px 0; border-top: 1px solid rgba(255,255,255,0.08); border-bottom: 1px solid rgba(255,255,255,0.08);">
                            <div>
                                <div style="font-size: 14px; font-weight: 700; color: white;">{ai_consensus.get("sources",0)}/{ai_consensus.get("total",0)}</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.5);">CONSENSUS</div>
                            </div>
                            <div>
                                <div style="font-size: 14px; font-weight: 700; color: {_ai_value_colors.get(ai_value, "#999")};">{ai_value}</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.5);">VALUE</div>
                            </div>
                            <div>
                                <div style="font-size: 14px; font-weight: 700; color: {"#69f0ae" if ai_ev and ai_ev > 0 else "#ff5252"};">{f"+{ai_ev:.2f}" if ai_ev and ai_ev > 0 else f"{ai_ev:.2f}" if ai_ev else "—"}</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.5);">EV</div>
                            </div>
                            <div>
                                <div style="font-size: 14px; font-weight: 700; color: {"#69f0ae" if ai_edge and ai_edge > 0 else "#ff5252"};">{f"+{ai_edge:.1f}%" if ai_edge and ai_edge > 0 else f"{ai_edge:.1f}%" if ai_edge else "—"}</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.5);">EDGE</div>
                            </div>
                        </div>
                        {('<div style="margin-bottom: 8px; padding: 10px; background: rgba(255,255,255,0.04); border-radius: 8px; font-size: 12px; color: rgba(255,255,255,0.85); line-height: 1.5;">' + ai_full_verdict + '</div>') if ai_full_verdict else ''}
                        {('<div style="margin-bottom: 6px;"><div style="font-size: 9px; color: #69f0ae; font-weight: 600; margin-bottom: 4px;">KEY ARGUMENTS</div>' + ''.join('<div style="font-size: 11px; color: rgba(255,255,255,0.7); padding: 2px 0;">&bull; ' + a + '</div>' for a in ai_args_for[:3]) + '</div>') if ai_args_for else ''}
                        {('<div style="margin-bottom: 6px;"><div style="font-size: 9px; color: #ff5252; font-weight: 600; margin-bottom: 4px;">COUNTER ARGUMENTS</div>' + ''.join('<div style="font-size: 11px; color: rgba(255,255,255,0.7); padding: 2px 0;">&bull; ' + a + '</div>' for a in ai_args_against[:2]) + '</div>') if ai_args_against else ''}
                        {('<div style="margin-top: 8px; padding: 8px; background: rgba(255,82,82,0.15); border: 1px solid rgba(255,82,82,0.3); border-radius: 8px;"><div style="font-size: 9px; color: #ff5252; font-weight: 700; margin-bottom: 4px;">DO NOT BET</div>' + ''.join('<div style="font-size: 11px; color: #ff8a80; padding: 1px 0;">&bull; ' + r + '</div>' for r in ai_dnb) + '</div>') if ai_dnb else ''}
                        <div style="margin-top: 6px; text-align: right; font-size: 9px; color: rgba(255,255,255,0.3);">Data Quality: {ai_dq} | {ai_consensus.get("strength", "")}</div>
                    </div>
                    ''' if has_ai_pred else ''}
                    
                </div>
                
                <!-- FOOTER -->
                <div style="background: rgba(0,0,0,0.1); padding: 10px 20px; text-align: center;">"""

        # Model explanation: prediction grade + primary factors
        grade = match.get('prediction_grade', '')
        explanation = match.get('explanation')
        grade_colors = {'A': '#00e676', 'B': '#69f0ae', 'C': '#ffd740', 'D': '#ff9100', 'F': '#ff5252'}
        if grade and grade in grade_colors:
            gc = grade_colors[grade]
            html += f"""
                    <div style="margin-bottom: 6px;">
                        <span style="display: inline-block; background: {gc}; color: #111; font-weight: 700; font-size: 11px; padding: 2px 8px; border-radius: 4px;">Grade {grade}</span>
                    </div>"""
        if isinstance(explanation, dict):
            factors = explanation.get('primary_factors', [])
            risks = explanation.get('risk_factors', [])
            if factors:
                html += f"""
                    <div style="font-size: 10px; color: rgba(255,255,255,0.6); margin-bottom: 3px;">✅ {' · '.join(str(f) for f in factors[:3])}</div>"""
            if risks:
                html += f"""
                    <div style="font-size: 10px; color: #ff8a80; margin-bottom: 3px;">⚠️ {' · '.join(str(r) for r in risks[:2])}</div>"""
        html += f"""
                    <a href="{match_url}" style="color: white; text-decoration: none; font-size: 12px;">🔗 Zobacz szczegóły meczu →</a>
                </div>
            </div>
        """
    
    html += """
        </div>
        
        <div class="footer">
            <p>📧 Wygenerowano automatycznie przez Livesport H2H Scraper v6.1</p>
            <p>🔔 <strong>Kryteria kwalifikacji:</strong></p>
            <p>🎾 <strong>Tennis:</strong> Multi-factor scoring (H2H + ranking + forma + powierzchnia + kursy) ≥ 45/100</p>
            <p>⚽ <strong>Sporty drużynowe:</strong></p>
            <p style="margin-left: 20px;">
                1️⃣ Gospodarze wygrali ≥60% H2H<br>
                2️⃣ <strong>ZAAWANSOWANA ANALIZA FORMY (3 źródła):</strong><br>
                &nbsp;&nbsp;&nbsp;&nbsp;• Forma ogólna (ostatnie 5 meczów)<br>
                &nbsp;&nbsp;&nbsp;&nbsp;• Forma gospodarzy U SIEBIE<br>
                &nbsp;&nbsp;&nbsp;&nbsp;• Forma gości NA WYJEŹDZIE<br>
                3️⃣ Gospodarze w dobrej formie + Goście w słabej = 🔥 Przewaga!
            </p>
        </div>
    </body>
    </html>
    """
    
    return html


def send_email_notification(
    csv_file: str,
    to_email: str,
    from_email: str,
    password: str,
    provider: str = 'gmail',
    subject: Optional[str] = None,
    sort_by: str = 'time',
    only_form_advantage: bool = False,
    skip_no_odds: bool = True,
    include_sorted_odds: bool = True,
    odds_limit: int = 15,
    min_odds_threshold: float = 0.0,
    grade_filter: Optional[set] = None,
    date: Optional[str] = None,
):
    """
    Wysyła email z powiadomieniem o kwalifikujących się meczach
    
    Args:
        csv_file: Ścieżka do pliku CSV z wynikami
        to_email: Email odbiorcy
        from_email: Email nadawcy
        password: Hasło do email (lub App Password dla Gmail)
        provider: 'gmail', 'outlook', lub 'yahoo'
        subject: Opcjonalny tytuł emaila
        sort_by: Sortowanie: 'time' (godzina), 'wins' (wygrane), 'team' (alfabetycznie)
        only_form_advantage: Wysyłaj tylko mecze z przewagą formy gospodarzy (🔥)
        skip_no_odds: Pomijaj mecze bez kursów bukmacherskich
        include_sorted_odds: Parametr zachowany dla kompatybilności; sekcje kursów nie są już renderowane
        odds_limit: Parametr zachowany dla kompatybilności; nie wpływa już na HTML maila
        min_odds_threshold: Minimalny kurs (np. 1.19) — mecze z jakimkolwiek kursem poniżej są pomijane
        grade_filter: Optional set of allowed prediction_grade values (e.g. {'A','B'}).
                      None = send all grades (legacy behavior).
    """
    
    # Wczytaj dane
    print(f"Wczytuje dane z: {csv_file}")
    df = pd.read_csv(csv_file, encoding='utf-8')
    
    # 🔧 Czyść DataFrame po wczytaniu z CSV - zamień string 'nan' na None
    def clean_dataframe_for_email(df_in: pd.DataFrame) -> pd.DataFrame:
        """Czyści DataFrame po wczytaniu z CSV - zamienia string 'nan' na None"""
        # Zamień stringi 'nan' na None
        df_in = df_in.replace({'nan': None, 'NaN': None, 'None': None})

        # Dla kolumn numerycznych (kursy, prawdopodobieństwa) - zamień NaN na None
        numeric_cols = ['home_odds', 'draw_odds', 'away_odds',
                        'forebet_probability', 'sofascore_home_win_prob',
                        'sofascore_draw_prob', 'sofascore_away_win_prob',
                        'sofascore_total_votes', 'gemini_confidence']
        for col in numeric_cols:
            if col in df_in.columns:
                df_in[col] = df_in[col].apply(
                    lambda x: None if pd.isna(x) or (isinstance(x, str) and x.lower() == 'nan') else x  # type: ignore[arg-type]
                )

        # `sofascore_found` po round-tripie przez CSV bywa stringiem "True"/"False" /"nan".
        # Normalizujemy do bool/None, by renderer maila mógł odróżnić
        # "nie próbowano" (None) od "próbowano i brak danych" (False).
        if 'sofascore_found' in df_in.columns:
            def _norm_found(v: Any) -> Any:
                if v is None:
                    return None
                try:
                    if pd.isna(v):
                        return None
                except (TypeError, ValueError):
                    pass
                if isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    s = v.strip().lower()
                    if s in ('true', '1', 'yes'):
                        return True
                    if s in ('false', '0', 'no'):
                        return False
                    if s in ('', 'nan', 'none'):
                        return None
                return v
            df_in['sofascore_found'] = df_in['sofascore_found'].apply(_norm_found)

        return df_in
    
    df = clean_dataframe_for_email(df)
    print(f"   🔧 Wyczyszczono dane z 'nan' stringów")
    
    # Filtruj kwalifikujące się mecze — use centralized qualification gate if available
    _gate_used = 'channel_qualifies' in df.columns and df['channel_qualifies'].notna().any()
    if _gate_used:
        qualified = df[df['channel_qualifies'] == True]
        print(f"   🚦 Unified qualification gate: {len(qualified)} matches")
    else:
        qualified = df[df['qualifies'] == True]
    
    # OPCJA 1: Filtruj tylko mecze z przewagą formy
    if only_form_advantage:
        print("🔥 TRYB: Tylko mecze z PRZEWAGĄ FORMY (gospodarzy/gości)")
        if 'form_advantage' in qualified.columns:
            qualified = qualified[qualified['form_advantage'] == True]
            print(f"   Przefiltrowano do meczów z przewagą formy")
        else:
            print("   ⚠️ Brak kolumny 'form_advantage' w danych - pokazuję wszystkie kwalifikujące")
    
    # OPCJA 2: Pomijaj mecze bez kursów
    if skip_no_odds:
        print("💰 TRYB: Pomijam mecze BEZ KURSÓW bukmacherskich")
        before_count = len(qualified)
        # Filtruj mecze, które mają OBA kursy (home_odds i away_odds)
        if 'home_odds' in qualified.columns and 'away_odds' in qualified.columns:
            qualified = qualified[(qualified['home_odds'].notna()) & (qualified['away_odds'].notna())]
            skipped = before_count - len(qualified)
            print(f"   Pominięto {skipped} meczów bez kursów")
        else:
            print("   ⚠️ Brak kolumn z kursami w danych - pokazuję wszystkie mecze")

    # OPCJA 3: Filtr progów kursowych per sport (AND — oba kursy >= progu)
    # Skip when qualification gate already applied odds filtering
    if _gate_used:
        print("📉 Progi kursowe: pomijam (już zastosowane w qualification gate)")
    else:
        print("📉 TRYB: Progi kursowe per sport (AND)")
        before_count = len(qualified)
        if 'home_odds' in qualified.columns and 'away_odds' in qualified.columns:
            sport_col = 'sport' if 'sport' in qualified.columns else None

            def _sport_odds_ok(row: pd.Series) -> bool:  # type: ignore[type-arg]
                sp = row[sport_col] if sport_col else 'football'
                return _passes_sport_odds_threshold(sp, row.get('home_odds'), row.get('away_odds'), min_odds_threshold)

            qualified = qualified[qualified.apply(_sport_odds_ok, axis=1)]
            skipped = before_count - len(qualified)
            print(f"   Pominięto {skipped} meczów poniżej progu kursowego per sport")

    # OPCJA 4: Filtr po grade (A/B vs C-F tier split)
    if grade_filter is not None:
        before_count = len(qualified)
        if 'prediction_grade' in qualified.columns:
            qualified = qualified[qualified['prediction_grade'].apply(
                lambda g: (g if isinstance(g, str) else 'F') in grade_filter
            )]
        else:
            # No grade column — if filtering for premium only, skip all
            if grade_filter == {'A', 'B'}:
                qualified = qualified.iloc[0:0]
        skipped = before_count - len(qualified)
        grade_label = '/'.join(sorted(grade_filter))
        print(f"🏅 Grade filter [{grade_label}]: {len(qualified)} matches (pominięto {skipped})")

    if len(qualified) == 0:
        messages: List[str] = []
        if only_form_advantage:
            messages.append("PRZEWAGĄ FORMY")
        if skip_no_odds:
            messages.append("KURSAMI")
        
        if messages:
            print(f"Brak kwalifikujacych sie meczow z {' i '.join(messages)} do wyslania")
        else:
            print("Brak kwalifikujacych sie meczow do wyslania")
        return

    # Policz mecze z kursami i bez (tylko jeśli nie pomijamy meczów bez kursów)
    if not skip_no_odds:
        with_odds = qualified[(qualified['home_odds'].notna()) & (qualified['away_odds'].notna())]
        without_odds = len(qualified) - len(with_odds)
    else:
        without_odds = 0  # Wszystkie mają kursy, bo filtrujemy

    # Komunikat o znalezionych meczach
    msg_parts: List[str] = []
    if only_form_advantage:
        msg_parts.append("z PRZEWAGĄ FORMY 🔥")
    if skip_no_odds:
        msg_parts.append("z KURSAMI 💰")
    
    if msg_parts:
        print(f"Znaleziono {len(qualified)} kwalifikujacych sie meczow {' i '.join(msg_parts)}")
    else:
        print(f"Znaleziono {len(qualified)} kwalifikujacych sie meczow")
    
    if without_odds > 0 and not skip_no_odds:
        print(f"   W tym {without_odds} meczow bez kursow bukmacherskich")
    
    # Przygotuj dane
    matches = qualified.to_dict('records')
    for m in matches:
        m['ai_prediction'] = ensure_ai_prediction_dict(m.get('ai_prediction'))
    _log_sofascore_coverage(matches)
    # Spójność z `send_split_emails_by_sport`: bierzemy `--date` z wołającego
    # zamiast `datetime.now()`, żeby manifest pasował do scrapingu.
    if not date:
        date = datetime.now().strftime('%Y-%m-%d')

    # Zapisz manifest meczów wysłanych mailem (źródło prawdy dla rozliczenia)
    if matches:
        _save_mailed_manifest(list(matches), date)  # type: ignore[arg-type]
    
    if subject is None:
        subject_parts: List[str] = []
        if only_form_advantage:
            subject_parts.append("🔥 PRZEWAGA FORMY")
        if skip_no_odds:
            subject_parts.append("💰 Z KURSAMI")
        
        if subject_parts:
            subject = f"{len(qualified)} meczów ({' + '.join(subject_parts)}) - {date}"
        else:
            subject = f"{len(qualified)} kwalifikujacych sie meczow - {date}"
    
    # Utwórz wiadomość
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email
    
    # Dodaj treść HTML
    html_content = create_html_email(
        matches, date,  # type: ignore[arg-type]
        sort_by=sort_by,
        include_sorted_odds=include_sorted_odds,
        odds_limit=odds_limit
    )
    html_part = MIMEText(html_content, 'html')
    msg.attach(html_part)
    
    # Wyślij email
    try:
        print(f"\nWysylam email do: {to_email}")
        print(f"   Provider: {provider}")
        
        smtp_config = SMTP_CONFIG[provider]
        
        with smtplib.SMTP(smtp_config['server'], smtp_config['port']) as server:
            if smtp_config['use_tls']:
                server.starttls()
            
            server.login(from_email, password)
            server.send_message(msg)
        
        print("Email wyslany pomyslnie!")
        
    except Exception as e:
        print(f"Blad wysylania emaila: {e}")
        print("\nWSKAZOWKI:")
        print("   - Dla Gmail: uzyj App Password (nie zwyklego hasla)")
        print("     Jak uzyskac: https://myaccount.google.com/apppasswords")
        print("   - Sprawdz czy SMTP jest wlaczony w ustawieniach konta")
        print("   - Sprawdz dane logowania")


# ---------------------------------------------------------------------------
# Split emails: 2 maile na każdy sport (form_advantage vs zwykłe)
# ---------------------------------------------------------------------------

SPORT_EMOJI = {
    'football': '⚽', 'basketball': '🏀', 'handball': '🤾',
    'volleyball': '🏐', 'tennis': '🎾', 'hockey': '🏒', 'rugby': '🏉',
}

SPORT_LABEL = {
    'football': 'Piłka nożna', 'basketball': 'Koszykówka', 'handball': 'Piłka ręczna',
    'volleyball': 'Siatkówka', 'tennis': 'Tenis', 'hockey': 'Hokej', 'rugby': 'Rugby',
}

# ---------------------------------------------------------------------------
# Per-sport minimum odds thresholds
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Manifest: snapshot of matches that actually made it into the email
# ---------------------------------------------------------------------------

_MANIFEST_FIELDS = [
    'match_url', 'match_date', 'match_time', 'sport', 'league',
    'home_team', 'away_team', 'home_odds', 'draw_odds', 'away_odds',
    'win_rate', 'h2h_count', 'home_wins_in_h2h_last5', 'away_wins_in_h2h_last5',
    'form_advantage', 'forebet_prediction', 'forebet_probability',
    'gemini_prediction', 'gemini_recommendation', 'gemini_confidence',
    'scoring_pick', 'scoring_prob', 'scoring_ev', 'scoring_edge',
    'qualifies', 'focus_team',
]


def _save_mailed_manifest(matches: List[Dict[str, Any]], date: str, tag: str = '') -> str:
    """Save a JSON manifest of matches that were actually emailed.

    Returns the path of the written file.
    """
    os.makedirs('outputs', exist_ok=True)
    suffix = f'_{tag}' if tag else ''
    path = f'outputs/mailed_manifest_{date}{suffix}.json'

    # Keep only stable fields (drop huge HTML blobs etc.)
    records: List[Dict[str, Any]] = []
    for m in matches:
        rec: Dict[str, Any] = {}
        for field in _MANIFEST_FIELDS:
            val = m.get(field)
            # Convert pandas NaN / numpy NaN to None for clean JSON
            if val is not None:
                try:
                    if isinstance(val, float) and math.isnan(val):
                        val = None
                except (TypeError, ValueError):
                    pass
            rec[field] = val
        records.append(rec)

    # Append-safe: if a manifest already exists for this date+tag, merge
    existing: List[Dict[str, Any]] = []
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = []

    # Deduplicate by match_url
    seen_urls = {r.get('match_url') for r in existing if r.get('match_url')}
    for rec in records:
        if rec.get('match_url') not in seen_urls:
            existing.append(rec)
            seen_urls.add(rec.get('match_url'))

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    print(f"📋 Manifest mailed events zapisany: {path} ({len(existing)} meczów)")
    return path


def _save_empty_manifest_marker(date: str, reason: str) -> str:
    """Zapisz pusty/diagnostyczny manifest, gdy żaden mecz nie kwalifikuje się
    do wysyłki.

    Plik trafia do `outputs/mailed_manifest_{date}_empty.json` i ma kształt
    listy z jednym opisowym rekordem, dzięki czemu `check_results.py`
    rozpoznaje "scraping ok, ale brak meczów do wysyłki" zamiast pokazywać
    twardy błąd "brak manifestów" (z którym nie wiadomo co zrobić).
    """
    os.makedirs('outputs', exist_ok=True)
    path = f'outputs/mailed_manifest_{date}_empty.json'
    payload = [{
        'match_url': None,
        'home_team': None,
        'away_team': None,
        'sport': None,
        'qualifies': False,
        'channel_qualifies': False,
        'empty_reason': reason,
        'note': 'Pipeline run finished but no matches qualified for delivery.',
    }]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"📋 Empty manifest marker zapisany: {path} (reason={reason})")
    return path


SPORT_MIN_ODDS: Dict[str, float] = {
    'football': 1.50,
    'basketball': 1.30,
    'handball': 1.45,
    'volleyball': 1.30,
    'hockey': 1.50,
    'tennis': 1.35,
}
SPORT_MIN_ODDS_FALLBACK: float = 1.35


def _passes_sport_odds_threshold(sport: str, home_odds: Any, away_odds: Any,
                                  min_odds_threshold: float = 0.0) -> bool:
    """Return True when BOTH home AND away odds meet the sport's threshold.

    Rules:
      - threshold is looked up per sport; unknown sports use SPORT_MIN_ODDS_FALLBACK
      - if min_odds_threshold > 0, effective threshold = max(sport_threshold, min_odds_threshold)
      - condition is AND: float(home_odds) >= threshold AND float(away_odds) >= threshold
      - if either odds is missing / unparseable the match is rejected
    """
    threshold = SPORT_MIN_ODDS.get(sport, SPORT_MIN_ODDS_FALLBACK)
    if min_odds_threshold > 0:
        threshold = max(threshold, min_odds_threshold)
    ho_ok = False
    ao_ok = False
    try:
        if home_odds is not None and not (isinstance(home_odds, float) and math.isnan(home_odds)):
            ho_ok = float(home_odds) >= threshold
    except (ValueError, TypeError):
        pass
    try:
        if away_odds is not None and not (isinstance(away_odds, float) and math.isnan(away_odds)):
            ao_ok = float(away_odds) >= threshold
    except (ValueError, TypeError):
        pass
    return ho_ok and ao_ok


def send_split_emails_by_sport(
    csv_file: str,
    to_email: str,
    from_email: str,
    password: str,
    provider: str = 'gmail',
    sort_by: str = 'time',
    include_sorted_odds: bool = True,
    odds_limit: int = 15,
    min_odds_threshold: float = 0.0,
    date: Optional[str] = None,
):
    """
    Wysyła 1 mail dla każdego sportu ze wszystkimi kwalifikującymi
    się meczami (Grade A-F) w jednej wiadomości.

    Filtry:
      - brak kursów → pominięty
      - per-sport progi kursowe (AND — oba kursy >= progu sportu)
    """
    print("=" * 70)
    print("📧 TRYB: 1 mail na każdy sport (all grades)")
    print("   Progi kursowe per sport (AND)")
    print("=" * 70)

    # --- wczytaj i wyczyść ---
    df = pd.read_csv(csv_file, encoding='utf-8')
    df = df.replace({'nan': None, 'NaN': None, 'None': None})
    numeric_cols = ['home_odds', 'draw_odds', 'away_odds',
                    'forebet_probability', 'sofascore_home_win_prob',
                    'sofascore_draw_prob', 'sofascore_away_win_prob',
                    'sofascore_total_votes', 'gemini_confidence']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: None if pd.isna(x) or (isinstance(x, str) and x.lower() == 'nan') else x  # type: ignore[arg-type]
            )

    # Normalizuj `sofascore_found` (string po round-tripie CSV) do bool/None,
    # tak jak w `send_email_notification` — żeby placeholder "brak danych
    # SofaScore" w mailu zachowywał się spójnie w obu ścieżkach.
    if 'sofascore_found' in df.columns:
        def _norm_found_split(v: Any) -> Any:
            if v is None:
                return None
            try:
                if pd.isna(v):
                    return None
            except (TypeError, ValueError):
                pass
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                s = v.strip().lower()
                if s in ('true', '1', 'yes'):
                    return True
                if s in ('false', '0', 'no'):
                    return False
                if s in ('', 'nan', 'none'):
                    return None
            return v
        df['sofascore_found'] = df['sofascore_found'].apply(_norm_found_split)

    # --- filtruj kwalifikujące ---
    _gate_used = 'channel_qualifies' in df.columns and df['channel_qualifies'].notna().any()
    if _gate_used:
        qualified = df[df['channel_qualifies'] == True].copy()
        print(f"   🚦 Unified qualification gate: {len(qualified)} matches")
    else:
        qualified = df[df['qualifies'] == True].copy()
        print(f"   Kwalifikujące się: {len(qualified)}")

    # --- filtr: brak kursów ---
    if 'home_odds' in qualified.columns and 'away_odds' in qualified.columns:
        before = len(qualified)
        qualified = qualified[(qualified['home_odds'].notna()) & (qualified['away_odds'].notna())]
        print(f"   Pominięto {before - len(qualified)} meczów bez kursów")

    # --- filtr: progi kursowe per sport (AND) — skip when gate already ran ---
    if _gate_used:
        print(f"   📉 Progi kursowe: pomijam (już zastosowane w qualification gate)")
    elif 'home_odds' in qualified.columns:
        before = len(qualified)
        sport_col = 'sport' if 'sport' in qualified.columns else None

        def _above(row: pd.Series) -> bool:  # type: ignore[type-arg]
            sp = row[sport_col] if sport_col else 'football'
            return _passes_sport_odds_threshold(sp, row.get('home_odds'), row.get('away_odds'), min_odds_threshold)

        qualified = qualified[qualified.apply(_above, axis=1)]
        print(f"   Pominięto {before - len(qualified)} meczów poniżej progu kursowego per sport")

    # Data dla nazewnictwa manifestu MUSI być spójna z `--date` użytym przy
    # scrapowaniu — `Check Results` szuka plików po tej dacie. Wcześniej brana
    # była z `datetime.now()`, co przy uruchomieniach o północy / w innej
    # strefie potrafiło zapisać manifest pod inną datą niż folder `results/`.
    if not date:
        date = datetime.now().strftime('%Y-%m-%d')

    if len(qualified) == 0:
        print("   ⚠️ Brak meczów po filtrach — żaden email nie zostanie wysłany")
        # Zapisujemy diagnostyczną notatkę, żeby `check_results` mógł odróżnić
        # "manifest zaginął" od "świadomie nie wysłano nic".
        try:
            _save_empty_manifest_marker(date, reason='no_qualified_after_filters')
        except Exception:
            pass
        return 0

    # --- podział po sporcie ---
    if 'sport' not in qualified.columns:
        qualified['sport'] = 'football'  # fallback

    sports = qualified['sport'].unique()
    sent_count = 0

    # ── Najpierw zapisz manifesty per sport (PRZED SMTP) ──
    # Zapis manifestu przed wysyłką sprawia, że `check_results` ma z czego
    # liczyć skuteczność predykcji nawet jeśli SMTP padnie (np. zła konfiguracja
    # serwera, hasło, baseballowy workflow z dummy SMTP). Manifest opisuje co
    # było *zakwalifikowane* do wysłania, a nie co dotarło do skrzynki — to
    # jest oczekiwana semantyka dla raportu accuracy.
    sport_payloads: Dict[str, List[Dict[str, Any]]] = {}
    for sport in sorted(sports):
        sport_df: pd.DataFrame = qualified[qualified['sport'] == sport]  # type: ignore[assignment]
        if len(sport_df) == 0:  # type: ignore[arg-type]
            continue
        matches_list: List[Dict[str, Any]] = sport_df.to_dict('records')  # type: ignore[assignment]
        for m in matches_list:
            m['ai_prediction'] = ensure_ai_prediction_dict(m.get('ai_prediction'))
        _log_sofascore_coverage(matches_list, label=sport)
        _save_mailed_manifest(matches_list, date, tag=sport)
        sport_payloads[sport] = matches_list

    smtp_config = SMTP_CONFIG[provider]

    # ── Krótki preflight: dummy SMTP credentials = nie próbuj logować się ──
    # Baseballowy workflow z `--send-email false` przekazuje `noreply@localhost`
    # / `dummy`, więc próba SMTP jest gwarantowanym błędem. Manifest jest już
    # zapisany powyżej, więc po prostu nie próbujemy logować się i raportujemy
    # to jasno w logach.
    is_dummy_smtp = (
        not from_email
        or 'noreply@localhost' in str(from_email).lower()
        or str(password).strip().lower() in ('', 'dummy')
    )
    if is_dummy_smtp:
        print("   ℹ️ Dummy SMTP credentials — pomijam realną wysyłkę "
              "(manifest został zapisany dla raportu accuracy).")
        return 0

    try:
        with smtplib.SMTP(smtp_config['server'], smtp_config['port']) as server:
            if smtp_config['use_tls']:
                server.starttls()
            server.login(from_email, password)

            for sport, matches_list in sport_payloads.items():
                emoji = SPORT_EMOJI.get(sport, '🏆')
                label = SPORT_LABEL.get(sport, sport.capitalize())
                subj = f"{emoji} {label}: {len(matches_list)} meczów — {date}"
                html = create_html_email(matches_list, date, sort_by=sort_by,
                                         include_sorted_odds=include_sorted_odds,
                                         odds_limit=odds_limit)
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subj
                msg['From'] = from_email
                msg['To'] = to_email
                msg.attach(MIMEText(html, 'html'))
                server.send_message(msg)
                sent_count += 1
                print(f"   ✅ Wysłano: {subj}")

    except Exception as e:
        print(f"   ❌ Błąd wysyłania: {e}")

    print(f"\n📧 Wysłano łącznie {sent_count} maili")
    return sent_count


def main():
    """Przykład użycia"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Wyślij powiadomienie email o kwalifikujących się meczach')
    parser.add_argument('--csv', required=True, help='Plik CSV z wynikami')
    parser.add_argument('--to', required=True, help='Email odbiorcy')
    parser.add_argument('--from-email', required=True, help='Email nadawcy')
    parser.add_argument('--password', required=True, help='Hasło email (lub App Password)')
    parser.add_argument('--provider', default='gmail', choices=['gmail', 'outlook', 'yahoo'], 
                       help='Provider email')
    parser.add_argument('--subject', help='Opcjonalny tytuł emaila')
    parser.add_argument('--sort', default='time', choices=['time', 'wins', 'team'],
                       help='Sortowanie: time (godzina), wins (wygrane), team (alfabetycznie)')
    parser.add_argument('--only-form-advantage', action='store_true',
                       help='🔥 Wyślij tylko mecze z PRZEWAGĄ FORMY gospodarzy')
    parser.add_argument('--skip-no-odds', action='store_true',
                       help='💰 Pomijaj mecze BEZ KURSÓW bukmacherskich')
    parser.add_argument('--min-odds', type=float, default=0.0,
                       help='📉 Minimalny kurs — mecze z kursem poniżej są pomijane (np. 1.19)')
    parser.add_argument('--split-emails', action='store_true',
                       help='📧 Wyślij 2 osobne maile na każdy sport (forma vs zwykłe)')
    
    args = parser.parse_args()
    
    if args.split_emails:
        send_split_emails_by_sport(
            csv_file=args.csv,
            to_email=args.to,
            from_email=args.from_email,
            password=args.password,
            provider=args.provider,
            sort_by=args.sort,
            min_odds_threshold=args.min_odds if args.min_odds > 0 else 1.19,
        )
    else:
        send_email_notification(
            csv_file=args.csv,
            to_email=args.to,
            from_email=args.from_email,
            password=args.password,
            provider=args.provider,
            subject=args.subject,
            sort_by=args.sort,
            only_form_advantage=args.only_form_advantage,
            skip_no_odds=args.skip_no_odds,
            min_odds_threshold=args.min_odds,
        )


if __name__ == '__main__':
    main()

