"""
Moduł do wysyłania powiadomień email o kwalifikujących się meczach

NOWE: Sekcje pre-posortowanych kursów (home/draw/away) - od najwyższych do najniższych
"""

import smtplib
import math
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional, Any, Union
import pandas as pd
from datetime import datetime


# ============================================================================
# GLOBAL HELPER FUNCTIONS - Obsługa NaN, None i różnych formatów danych
# ============================================================================

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


def parse_form_list(form_data: Any) -> list:
    """
    Parsuje dane formy z różnych formatów (string, lista, etc.) do listy.
    Obsługuje formaty: ['W', 'L', 'D'], "['W', 'L', 'D']", "W-L-D", "WLD", etc.
    """
    if is_nan_or_none(form_data):
        return []
    
    # Już jest listą
    if isinstance(form_data, list):
        return [str(x).strip().upper() for x in form_data if x]
    
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
                    return [str(x).strip().upper() for x in parsed if x]
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


def has_valid_odds(match: Dict) -> bool:
    """
    Sprawdza czy mecz ma przynajmniej jeden ważny kurs.
    """
    home = safe_float(match.get('home_odds'))
    away = safe_float(match.get('away_odds'))
    return home > 0 or away > 0


def _clean_odds_for_render(val) -> Optional[float]:
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
    valid_odds = []
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
    <div style="padding: 10px; background: linear-gradient(135deg, #FF9800, #FF5722); border-radius: 8px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <div style="font-size: 11px; color: rgba(255,255,255,0.8);">🎯 Forebet</div>
                <div style="font-size: 20px; font-weight: bold; color: white;">{fb_pred}</div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 11px; color: rgba(255,255,255,0.8);">Prawdopodobieństwo</div>
                <div style="font-size: 24px; font-weight: bold; color: white;">{fb_prob:.0f}%</div>
            </div>
    '''
    
    if fb_exact:
        html += f'''
            <div style="background: rgba(255,255,255,0.2); padding: 5px 10px; border-radius: 5px;">
                <div style="font-size: 10px; color: rgba(255,255,255,0.8);">Wynik</div>
                <div style="font-size: 14px; font-weight: bold; color: white;">{fb_exact}</div>
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

def create_sorted_odds_sections(matches: List[Dict], limit: int = 15) -> str:
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
    
    def get_time_str(match):
        """Wyciąga godzinę meczu."""
        import re
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
SMTP_CONFIG = {
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

def create_html_email(matches: List[Dict], date: str, sort_by: str = 'time', 
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
        def get_time_key(match):
            match_time = match.get('match_time', '')
            if not match_time:
                return '99:99'  # Mecze bez czasu na końcu
            
            # Wyciągnij godzinę z różnych formatów
            import re
            # Format: DD.MM.YYYY HH:MM lub HH:MM
            time_match = re.search(r'(\d{1,2}:\d{2})', match_time)
            if time_match:
                return time_match.group(1)
            return '99:99'
        
        sorted_matches = sorted(sorted_matches, key=get_time_key)
    
    elif sort_by == 'wins':
        # Sortuj po liczbie wygranych (malejąco) - uwzględnij tryb away_team_focus
        def get_wins(match):
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
            <p>🎾 Tennis: Advanced scoring (≥50/100) | ⚽ Drużynowe: Gospodarze wygrali ≥60% H2H</p>
            <p style="font-size: 14px; margin-top: 10px;">🤖 <strong>Gemini AI Analysis</strong> | ⏰ Posortowane chronologicznie</p>
        </div>
        
        <div class="content">
    """
    
    # ========================================================================
    # TOP PICKS SECTION - Mecze z HIGH recommendation i wysokim confidence
    # ========================================================================
    top_picks = [m for m in sorted_matches if m.get('gemini_recommendation') == 'HIGH' and m.get('gemini_confidence', 0) >= 85]
    
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
            confidence = pick.get('gemini_confidence', 0)
            prediction = pick.get('gemini_prediction', 'N/A')
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
                focused_team = away
                team_emoji = '🚀'
            else:
                wins = pick.get('home_wins_in_h2h_last5', 0)
                h2h_count = pick.get('h2h_count', pick.get('h2h_last5', 0))
                focused_team = home
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
            
            html += f"""
            <div class="top-pick-card">
                <div class="top-pick-team">
                    {team_emoji} {home} <span style="color: #999;">vs</span> {away}
                </div>
                <div style="font-size: 14px; color: #FF5722; font-weight: bold; margin: 5px 0;">
                    🕐 {match_time}
                </div>
                
                <div class="top-pick-stats">
                    <div class="top-pick-stat">
                        <div class="top-pick-stat-value">{confidence:.0f}%</div>
                        <div class="top-pick-stat-label">AI Confidence</div>
                    </div>
                    <div class="top-pick-stat">
                        <div class="top-pick-stat-value">{win_rate:.0f}%</div>
                        <div class="top-pick-stat-label">H2H Win Rate</div>
                    </div>
                    <div class="top-pick-stat">
                        <div class="top-pick-stat-value" style="{forebet_style}">{forebet_prob}</div>
                        <div class="top-pick-stat-label">Forebet</div>
                    </div>
                </div>
                
                <div style="margin: 10px 0; padding: 10px; background: #e3f2fd; border-radius: 5px;">
                    <strong style="color: #1976d2;">🎯 Prognoza:</strong> {prediction}
                </div>
                
                <div class="top-pick-reasoning">
                    <strong>🤖 Analiza AI:</strong><br>{reasoning}...
                </div>
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
        
        import re
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
        
        def form_to_icons(form_list):
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
        # Flaga: pokaż SofaScore nawet gdy wartości = 0 (ale nie gdy None)
        has_sofascore = ss_home is not None or ss_away is not None
        
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
        
        # Kolory podświetlenia
        advantage_icon = '🔥' if form_advantage else ''
        
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
                            {f'<div style="font-size: 10px; color: #888; margin-top: 2px;">{last_h2h_home} vs {last_h2h_away}</div>' if last_h2h_score and last_h2h_home and not is_tennis else ''}
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
                            {f'<div style="text-align: center;"><div style="font-size: 18px; font-weight: bold; color: {chr(39)}#FFC107{chr(39) if ss_draw and ss_draw >= max(ss_home or 0, ss_draw or 0, ss_away or 0) else chr(39)}#333{chr(39)};">{ss_draw}%</div><div style="font-size: 10px; color: #888;">🤝</div></div>' if ss_draw else ''}
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
            <p>🎾 <strong>Tennis:</strong> Multi-factor scoring (H2H + ranking + forma + powierzchnia) ≥ 50/100</p>
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
    subject: str = None,
    sort_by: str = 'time',
    only_form_advantage: bool = False,
    skip_no_odds: bool = False,
    include_sorted_odds: bool = True,
    odds_limit: int = 15
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
    """
    
    # Wczytaj dane
    print(f"Wczytuje dane z: {csv_file}")
    df = pd.read_csv(csv_file, encoding='utf-8')
    
    # 🔧 Czyść DataFrame po wczytaniu z CSV - zamień string 'nan' na None
    def clean_dataframe_for_email(df_in):
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
                    lambda x: None if pd.isna(x) or (isinstance(x, str) and x.lower() == 'nan') else x
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
    
    if len(qualified) == 0:
        messages = []
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
    msg_parts = []
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
    date = datetime.now().strftime('%Y-%m-%d')
    
    if subject is None:
        subject_parts = []
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
        matches, date, 
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
    
    args = parser.parse_args()
    
    send_email_notification(
        csv_file=args.csv,
        to_email=args.to,
        from_email=args.from_email,
        password=args.password,
        provider=args.provider,
        subject=args.subject,
        sort_by=args.sort,
        only_form_advantage=args.only_form_advantage,
        skip_no_odds=args.skip_no_odds
    )


if __name__ == '__main__':
    main()

