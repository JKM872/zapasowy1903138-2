"""
Moduł do wysyłania powiadomień email o kwalifikujących się meczach

NOWE: Sekcje pre-posortowanych kursów (home/draw/away) - od najwyższych do najniższych
"""

import smtplib
import math
import json
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
        <div style="font-size: 11px; color: #666; margin-bottom: 8px;">💰 Kursy bukmacherskie</div>
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
        include_sorted_odds: Czy dodać sekcje z kursami posortowanymi od najwyższych
        odds_limit: Max liczba meczów w każdej sekcji kursów
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
    
    # Dodaj CSS dla sorted odds jeśli włączone
    extra_css = ODDS_SECTIONS_CSS if include_sorted_odds else ''
    
    html = f"""
    <html>
    <head>
        <style>
            {extra_css}
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
            .top-picks-section {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                border-radius: 10px;
                padding: 25px;
                margin: 20px 0;
                box-shadow: 0 8px 16px rgba(0,0,0,0.2);
            }}
            .top-picks-header {{
                color: #fff;
                font-size: 26px;
                font-weight: bold;
                text-align: center;
                margin-bottom: 20px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
            }}
            .top-pick-card {{
                background: white;
                border-radius: 8px;
                padding: 20px;
                margin: 15px 0;
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                border-left: 6px solid #ffd700;
            }}
            .top-pick-team {{
                font-size: 20px;
                font-weight: bold;
                color: #2196F3;
                margin-bottom: 10px;
            }}
            .top-pick-stats {{
                display: flex;
                justify-content: space-around;
                margin: 15px 0;
                flex-wrap: wrap;
            }}
            .top-pick-stat {{
                text-align: center;
                padding: 10px;
                min-width: 100px;
            }}
            .top-pick-stat-value {{
                font-size: 24px;
                font-weight: bold;
                color: #4CAF50;
            }}
            .top-pick-stat-label {{
                font-size: 12px;
                color: #666;
                text-transform: uppercase;
            }}
            .top-pick-reasoning {{
                background: #f8f9fa;
                border-left: 4px solid #667eea;
                padding: 12px;
                margin: 10px 0;
                font-style: italic;
                color: #333;
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
    # TOP PICKS SECTION - Mecze z HIGH recommendation i wysokim confidence
    # ========================================================================
    top_picks = [m for m in sorted_matches
                 if (m.get('gemini_recommendation') == 'HIGH' and m.get('gemini_confidence', 0) >= 85)
                 or (ensure_ai_prediction_dict(m.get('ai_prediction')).get('confidenceTier') in ('VERY HIGH', 'HIGH')
                     and ensure_ai_prediction_dict(m.get('ai_prediction')).get('compositeConfidence', 0) >= 75)]
    # Deduplicate (a match might qualify via both gemini and ai_prediction)
    seen_tp: set[tuple[Any, ...]] = set()
    unique_top_picks: List[Dict[str, Any]] = []
    for _tp in top_picks:
        _tp_key = (_tp.get('home_team', ''), _tp.get('away_team', ''), _tp.get('match_time', ''))
        if _tp_key not in seen_tp:
            seen_tp.add(_tp_key)
            unique_top_picks.append(_tp)
    top_picks = unique_top_picks
    
    if top_picks:
        html += f"""
        <div class="top-picks-section">
            <div class="top-picks-header">
                ⭐ TOP PICKS - Najlepsze Typy AI ({len(top_picks)}) ⭐
            </div>
    """
        
        for pick in top_picks:
            home = pick.get('home_team', 'N/A')
            away = pick.get('away_team', 'N/A')
            confidence: float = pick.get('gemini_confidence') or 0
            prediction = pick.get('gemini_prediction', 'N/A')
            tp_ai = ensure_ai_prediction_dict(pick.get('ai_prediction'))
            # Pre-compute AI Pro color values (avoids {{dict}} syntax errors inside f-strings)
            _tp_tc = {'VERY HIGH': '#00e676', 'HIGH': '#69f0ae', 'MEDIUM': '#ffd740'}.get(tp_ai.get('confidenceTier', ''), '#555')
            _tp_tc2 = {'VERY HIGH': '#00e676', 'HIGH': '#69f0ae', 'MEDIUM': '#ffd740'}.get(tp_ai.get('confidenceTier', ''), '#999')
            _tp_risk: Dict[str, Any] = tp_ai.get('risk') or {}
            _tp_rc: str = {'LOW': '#69f0ae', 'MEDIUM': '#ffd740', 'HIGH': '#ff5252'}.get(str(_tp_risk.get('level', '')), '#999')
            _tp_rs: Any = _tp_risk.get('score', '?')
            # Bezpieczne pobieranie reasoning (może być NaN/float z pandas)
            raw_reasoning = pick.get('gemini_reasoning', '')
            if raw_reasoning is None or (isinstance(raw_reasoning, float) and str(raw_reasoning) == 'nan'):
                reasoning = ''
            else:
                reasoning = str(raw_reasoning)[:300]  # First 300 chars
            
            # Calculate stats
            focus_team = pick.get('focus_team', 'home')
            if focus_team == 'away':
                wins = pick.get('away_wins_in_h2h_last5', 0)
                h2h_count = pick.get('h2h_count', pick.get('h2h_last5', 0))
                team_emoji = '🚀'
            else:
                wins = pick.get('home_wins_in_h2h_last5', 0)
                h2h_count = pick.get('h2h_count', pick.get('h2h_last5', 0))
                team_emoji = '🏠'
            
            win_rate = (wins / h2h_count * 100) if h2h_count > 0 else 0
            
            # Forebet data - obsługa braku danych
            raw_forebet_prob = pick.get('forebet_probability')
            if raw_forebet_prob is None or (isinstance(raw_forebet_prob, float) and str(raw_forebet_prob) == 'nan'):
                forebet_prob = 'Brak'
                forebet_style = 'color: #999; font-size: 12px;'
            else:
                forebet_prob = f"{raw_forebet_prob}%" if isinstance(raw_forebet_prob, (int, float)) else str(raw_forebet_prob)
                forebet_style = ''
            match_time = pick.get('match_time', 'Brak danych')
            
            # Logos for top picks
            _home_logo = pick.get('home_logo_url', '')
            _away_logo = pick.get('away_logo_url', '')
            _home_badge = f'<img src="{_home_logo}" alt="{home}" width="28" height="28" style="vertical-align:middle;border-radius:50%;margin-right:6px;" onerror="this.style.display=\'none\'">' if _home_logo else ''
            _away_badge = f'<img src="{_away_logo}" alt="{away}" width="28" height="28" style="vertical-align:middle;border-radius:50%;margin-left:6px;" onerror="this.style.display=\'none\'">' if _away_logo else ''
            _tp_kaf: List[str] = [str(x) for x in (tp_ai.get('keyArgumentsFor') or [])]  # type: ignore[misc]

            html += f"""
            <div class="top-pick-card">
                {(
                '<div style="margin-top: 12px; background: linear-gradient(135deg, #0d1117 0%, #161b22 100%); border-radius: 10px; padding: 14px; border: 1px solid ' + _tp_tc + '33;">'
                '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">'
                '<span style="font-size: 10px; font-weight: 700; color: ' + _tp_tc2 + '; letter-spacing: 1px;">AI PRO VERDICT</span>'
                '<span style="background: ' + _tp_tc2 + '; color: #000; padding: 2px 8px; border-radius: 8px; font-size: 10px; font-weight: 700;">' + tp_ai.get("confidenceTier", "") + '</span>'
                '</div>'
                '<div style="display: flex; justify-content: space-around; text-align: center; margin-bottom: 10px;">'
                '<div><div style="font-size: 22px; font-weight: 800; color: white;">' + tp_ai.get("pick", "") + '</div>'
                '<div style="font-size: 8px; color: #aaa;">' + tp_ai.get("pickLabel", "") + '</div></div>'
                '<div><div style="font-size: 22px; font-weight: 800; color: white;">' + f'{(tp_ai.get("compositeConfidence") or 0):.0f}' + '%</div>'
                '<div style="font-size: 8px; color: #aaa;">AI CONF</div></div>'
                '<div><div style="font-size: 22px; font-weight: 800; color: ' + _tp_rc + ';">' + str(_tp_rs) + '/10</div>'
                '<div style="font-size: 8px; color: #aaa;">RISK</div></div>'
                '</div>'
                '<div style="font-size: 12px; color: rgba(255,255,255,0.8); line-height: 1.4; padding: 8px; background: rgba(255,255,255,0.04); border-radius: 6px;">' + tp_ai.get("shortVerdict", "") + '</div>'
                + ('<div style="margin-top: 8px;">' + ''.join('<span style="display:inline-block;font-size:10px;color:#69f0ae;margin-right:8px;">+ ' + a + '</span>' for a in _tp_kaf[:2]) + '</div>' if _tp_kaf else '')
                + '</div>'
                ) if tp_ai.get("pick") else ''}
            </div>
    """
        
        html += """
        </div>
        """
    
    # ========================================================================
    # SORTED ODDS SECTIONS (jeśli włączone) - zawsze przed REGULAR MATCHES
    # ========================================================================
    if include_sorted_odds:
        odds_sections_html = create_sorted_odds_sections(sorted_matches, limit=odds_limit)
        if odds_sections_html:
            html += odds_sections_html
    
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
        
        # SofaScore - bezpieczne pobieranie z obsługą NaN i wartości 0
        ss_home_raw = match.get('sofascore_home_win_prob')
        if is_nan_or_none(ss_home_raw):
            ss_home_raw = match.get('sofascore_home')
        ss_draw_raw = match.get('sofascore_draw_prob')
        if is_nan_or_none(ss_draw_raw):
            ss_draw_raw = match.get('sofascore_draw')
        ss_away_raw = match.get('sofascore_away_win_prob')
        if is_nan_or_none(ss_away_raw):
            ss_away_raw = match.get('sofascore_away')
        ss_votes_raw = match.get('sofascore_total_votes')
        if is_nan_or_none(ss_votes_raw):
            ss_votes_raw = match.get('sofascore_votes', 0)
        
        ss_home = safe_float(ss_home_raw) if not is_nan_or_none(ss_home_raw) else None
        ss_draw = safe_float(ss_draw_raw) if not is_nan_or_none(ss_draw_raw) else None
        ss_away = safe_float(ss_away_raw) if not is_nan_or_none(ss_away_raw) else None
        ss_votes = int(safe_float(ss_votes_raw))
        # Flaga: pokaż SofaScore jeśli DOWOLNA wartość jest dostępna (home/away/draw/votes)
        has_sofascore = (ss_home is not None or ss_away is not None or 
                         ss_draw is not None or ss_votes > 0)
        _ss_draw_color = '#FFC107' if (ss_draw is not None and ss_draw >= max(ss_home or 0, ss_draw or 0, ss_away or 0)) else '#333'
        
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
        has_scoring = sc_pick is not None and sc_prob is not None
        
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
                    {f'<div style="margin-top: 5px;"><span style="background: #FFD700; color: #333; padding: 3px 8px; border-radius: 10px; font-size: 11px; font-weight: bold;">🔥 Przewaga gospodarzy!</span></div>' if form_advantage and not is_tennis else ''}
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
                    ''' if has_sofascore else ''}
                    
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
                                <div style="font-size: 20px; font-weight: bold; color: #ffd740;">{sc_pick}</div>
                                <div style="font-size: 9px; color: rgba(255,255,255,0.6);">TYP</div>
                            </div>
                            <div style="text-align: center; min-width: 60px;">
                                <div style="font-size: 20px; font-weight: bold;">{sc_prob:.0f}%</div>
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
                <div style="background: rgba(0,0,0,0.1); padding: 10px 20px; text-align: center;">
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
    min_odds_threshold: float = 0.0
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
        include_sorted_odds: Dodaj sekcje z kursami posortowanymi od najwyższych (domyślnie True)
        odds_limit: Max liczba meczów w każdej sekcji kursów (domyślnie 15)
        min_odds_threshold: Minimalny kurs (np. 1.19) — mecze z jakimkolwiek kursem poniżej są pomijane
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
        
        return df_in
    
    df = clean_dataframe_for_email(df)
    print(f"   🔧 Wyczyszczono dane z 'nan' stringów")
    
    # Filtruj kwalifikujące się mecze
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

    # OPCJA 3: Filtr progów kursowych per sport (OR — wystarczy jeden kurs >= progu)
    print("📉 TRYB: Progi kursowe per sport (OR)")
    before_count = len(qualified)
    if 'home_odds' in qualified.columns and 'away_odds' in qualified.columns:
        sport_col = 'sport' if 'sport' in qualified.columns else None

        def _sport_odds_ok(row: pd.Series) -> bool:  # type: ignore[type-arg]
            sp = row[sport_col] if sport_col else 'football'
            return _passes_sport_odds_threshold(sp, row.get('home_odds'), row.get('away_odds'))

        qualified = qualified[qualified.apply(_sport_odds_ok, axis=1)]
        skipped = before_count - len(qualified)
        print(f"   Pominięto {skipped} meczów poniżej progu kursowego per sport")

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
    date = datetime.now().strftime('%Y-%m-%d')
    
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
SPORT_MIN_ODDS: Dict[str, float] = {
    'football': 1.50,
    'basketball': 1.30,
    'handball': 1.45,
    'volleyball': 1.30,
    'hockey': 1.50,
    'tennis': 1.35,
}
SPORT_MIN_ODDS_FALLBACK: float = 1.35


def _passes_sport_odds_threshold(sport: str, home_odds: Any, away_odds: Any) -> bool:
    """Return True when at least ONE of home/away odds meets the sport's threshold.

    Rules:
      - threshold is looked up per sport; unknown sports use SPORT_MIN_ODDS_FALLBACK
      - condition is OR: float(home_odds) >= threshold OR float(away_odds) >= threshold
      - if both odds are missing / unparseable the match is rejected
    """
    threshold = SPORT_MIN_ODDS.get(sport, SPORT_MIN_ODDS_FALLBACK)
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
    return ho_ok or ao_ok


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
):
    """
    Wysyła 2 osobne maile dla każdego sportu:
      Mail 1 — 🔥 mecze z przewagą formy + dane
      Mail 2 — 📋 mecze zwykłe (bez przewagi formy)

    Filtry:
      - brak kursów → pominięty
      - per-sport progi kursowe (OR — wystarczy jeden kurs >= progu sportu)
    """
    print("=" * 70)
    print("📧 TRYB SPLIT: 2 maile na każdy sport")
    print("   Progi kursowe per sport (OR)")
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

    # --- filtruj kwalifikujące ---
    qualified = df[df['qualifies'] == True].copy()
    print(f"   Kwalifikujące się: {len(qualified)}")

    # --- filtr: brak kursów ---
    if 'home_odds' in qualified.columns and 'away_odds' in qualified.columns:
        before = len(qualified)
        qualified = qualified[(qualified['home_odds'].notna()) & (qualified['away_odds'].notna())]
        print(f"   Pominięto {before - len(qualified)} meczów bez kursów")

    # --- filtr: progi kursowe per sport (OR) ---
    if 'home_odds' in qualified.columns:
        before = len(qualified)
        sport_col = 'sport' if 'sport' in qualified.columns else None

        def _above(row: pd.Series) -> bool:  # type: ignore[type-arg]
            sp = row[sport_col] if sport_col else 'football'
            return _passes_sport_odds_threshold(sp, row.get('home_odds'), row.get('away_odds'))

        qualified = qualified[qualified.apply(_above, axis=1)]
        print(f"   Pominięto {before - len(qualified)} meczów poniżej progu kursowego per sport")

    if len(qualified) == 0:
        print("   ⚠️ Brak meczów po filtrach — żaden email nie zostanie wysłany")
        return 0

    # --- podział po sporcie ---
    if 'sport' not in qualified.columns:
        qualified['sport'] = 'football'  # fallback

    sports = qualified['sport'].unique()
    date = datetime.now().strftime('%Y-%m-%d')
    sent_count = 0

    smtp_config = SMTP_CONFIG[provider]

    try:
        with smtplib.SMTP(smtp_config['server'], smtp_config['port']) as server:
            if smtp_config['use_tls']:
                server.starttls()
            server.login(from_email, password)

            for sport in sorted(sports):
                sport_df: pd.DataFrame = qualified[qualified['sport'] == sport]  # type: ignore[assignment]
                emoji = SPORT_EMOJI.get(sport, '🏆')
                label = SPORT_LABEL.get(sport, sport.capitalize())

                # grupa A: przewaga formy
                if 'form_advantage' in sport_df.columns:  # type: ignore[union-attr]
                    group_form: pd.DataFrame = sport_df[sport_df['form_advantage'] == True]  # type: ignore[assignment]
                    group_normal: pd.DataFrame = sport_df[sport_df['form_advantage'] != True]  # type: ignore[assignment]
                else:
                    group_form = sport_df.iloc[0:0]  # type: ignore[assignment]  # pusty
                    group_normal = sport_df  # type: ignore[assignment]

                # --- Mail 1: forma ---
                if len(group_form) > 0:  # type: ignore[arg-type]
                    matches_form: List[Dict[str, Any]] = group_form.to_dict('records')  # type: ignore[assignment]
                    for m in matches_form:
                        m['ai_prediction'] = ensure_ai_prediction_dict(m.get('ai_prediction'))
                    subj = f"🔥 {emoji} {label}: {len(group_form)} meczów z PRZEWAGĄ FORMY — {date}"  # type: ignore[arg-type]
                    html = create_html_email(matches_form, date, sort_by=sort_by,  # type: ignore[arg-type]
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

                # --- Mail 2: zwykłe ---
                if len(group_normal) > 0:  # type: ignore[arg-type]
                    matches_normal: List[Dict[str, Any]] = group_normal.to_dict('records')  # type: ignore[assignment]
                    for m in matches_normal:
                        m['ai_prediction'] = ensure_ai_prediction_dict(m.get('ai_prediction'))
                    subj = f"📋 {emoji} {label}: {len(group_normal)} meczów zwykłych — {date}"  # type: ignore[arg-type]
                    html = create_html_email(matches_normal, date, sort_by=sort_by,  # type: ignore[arg-type]
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

