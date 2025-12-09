"""
Moduł do wysyłania powiadomień email o kwalifikujących się meczach
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict
import pandas as pd
from datetime import datetime

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

def create_html_email(matches: List[Dict], date: str, sort_by: str = 'time') -> str:
    """
    Tworzy ładny HTML email z listą meczów
    
    Args:
        matches: Lista meczów
        date: Data
        sort_by: 'time' (godzina), 'wins' (liczba wygranych), 'team' (alfabetycznie)
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
        # Zbierz wszystkie dane w jednym miejscu
        
        # FORMA
        home_form_overall = match.get('home_form_overall', match.get('home_form', []))
        home_form_home = match.get('home_form_home', [])
        away_form_overall = match.get('away_form_overall', match.get('away_form', []))
        away_form_away = match.get('away_form_away', [])
        form_advantage = match.get('form_advantage', False)
        last_meeting_date = match.get('last_meeting_date', '')
        
        def form_to_icons(form_list):
            icons = {'W': '🟢', 'L': '🔴', 'D': '🟡'}
            return ''.join([icons.get(r, '⚪') for r in form_list[:5]]) if form_list else '—'
        
        # H2H
        h2h_count = match.get('h2h_count', 0)
        win_rate = match.get('win_rate', 0.0)
        if focus_team == 'away':
            wins = match.get('away_wins_in_h2h_last5', 0)
        else:
            wins = match.get('home_wins_in_h2h_last5', 0)
        
        # Helper: sanitize NaN values (pandas float NaN → None)
        import math
        def safe_float(val):
            if val is None:
                return None
            try:
                f = float(val)
                if math.isnan(f):
                    return None
                return f
            except (ValueError, TypeError):
                return None
        
        # SofaScore (sanitized)
        ss_home = safe_float(match.get('sofascore_home_win_prob') or match.get('sofascore_home'))
        ss_draw = safe_float(match.get('sofascore_draw_prob') or match.get('sofascore_draw'))
        ss_away = safe_float(match.get('sofascore_away_win_prob') or match.get('sofascore_away'))
        ss_votes = safe_float(match.get('sofascore_total_votes') or match.get('sofascore_votes', 0)) or 0
        
        # Odds (sanitized)
        home_odds = safe_float(match.get('home_odds'))
        draw_odds = safe_float(match.get('draw_odds'))
        away_odds = safe_float(match.get('away_odds'))
        
        # Forebet
        fb_pred = match.get('forebet_prediction')
        fb_prob = match.get('forebet_probability')
        fb_exact = match.get('forebet_exact_score')
        fb_prob_clean = safe_float(fb_prob)
        
        # Kolory podświetlenia
        advantage_icon = '🔥' if form_advantage else ''
        
        # ========== TABLE-BASED LAYOUT (works in Gmail/Outlook) ==========
        html += f"""
            <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; margin: 15px 0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                <!-- HEADER: Czas i numer -->
                <tr>
                    <td colspan="2" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 12px 20px;">
                        <table width="100%">
                            <tr>
                                <td style="color: white;">
                                    <span style="background: #FF5722; padding: 4px 10px; border-radius: 12px; font-weight: bold; font-size: 12px;">🕐 {time_badge if time_badge else 'TBD'}</span>
                                </td>
                                <td align="right" style="color: rgba(255,255,255,0.7); font-size: 11px;">
                                    #{i}
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
                
                <!-- DRUŻYNY -->
                <tr>
                    <td colspan="2" style="background: white; padding: 20px; text-align: center;">
                        <div style="font-size: 20px; font-weight: bold; color: #333;">
                            🏠 {home} <span style="color: #999; font-size: 14px;">vs</span> {away} ✈️
                        </div>
                        {f'<div style="margin-top: 8px;"><span style="background: #FFD700; color: #333; padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: bold;">🔥 Przewaga gospodarzy!</span></div>' if form_advantage else ''}
                    </td>
                </tr>
                
                <!-- H2H - w stylu ze screenshotu -->
                <tr>
                    <td colspan="2" style="background: #f8f9fa; padding: 12px; border-bottom: 1px solid #eee;">
                        <div style="font-size: 12px; color: #333;">
                            🔄 <strong>H2H:</strong> 
                            {f'<span style="color: #4CAF50; font-weight: bold;">{home if focus_team != "away" else away} wygrał {wins}/{h2h_count} ({win_rate*100:.0f}%)</span> 🏠' if h2h_count > 0 else '—'}
                            {f' | 📅 Ost. mecz: <strong>{last_meeting_date}</strong>' if last_meeting_date else ''}
                        </div>
                    </td>
                </tr>
                
                <!-- ANALIZA FORMY - header -->
                <tr>
                    <td colspan="2" style="background: #e8f5e9; padding: 10px 12px; border-bottom: 1px solid #c8e6c9;">
                        <div style="font-size: 11px; color: #2e7d32; font-weight: bold;">
                            📊 Analiza Formy (ostatnie 5 meczów):
                        </div>
                    </td>
                </tr>
                
                <!-- FORMA DRUŻYN - GOSPODARZE -->
                <tr>
                    <td colspan="2" style="background: white; padding: 10px 12px; border-bottom: 1px solid #eee;">
                        <div style="margin-bottom: 8px;">
                            <strong style="color: #333;">{home}:</strong>
                        </div>
                        <table width="100%" style="font-size: 11px;">
                            <tr>
                                <td style="color: #666; width: 80px;">🌍 Ogółem:</td>
                                <td style="font-size: 14px;">{form_to_icons(home_form_overall)}</td>
                            </tr>
                            {f'<tr><td style="color: #666;">🏠 U siebie:</td><td style="font-size: 14px;">{form_to_icons(home_form_home)}</td></tr>' if home_form_home else ''}
                        </table>
                    </td>
                </tr>
                
                <!-- FORMA DRUŻYN - GOŚCIE -->
                <tr>
                    <td colspan="2" style="background: white; padding: 10px 12px; border-bottom: 1px solid #eee;">
                        <div style="margin-bottom: 8px;">
                            <strong style="color: #333;">{away}:</strong>
                        </div>
                        <table width="100%" style="font-size: 11px;">
                            <tr>
                                <td style="color: #666; width: 80px;">🌍 Ogółem:</td>
                                <td style="font-size: 14px;">{form_to_icons(away_form_overall)}</td>
                            </tr>
                            {f'<tr><td style="color: #666;">✈️ Na wyjeździe:</td><td style="font-size: 14px;">{form_to_icons(away_form_away)}</td></tr>' if away_form_away else ''}
                        </table>
                    </td>
                </tr>
                
                <!-- PRZEWAGA W FORMIE -->
                {f'''
                <tr>
                    <td colspan="2" style="background: #fff3e0; padding: 10px 12px; border-bottom: 1px solid #ffe0b2;">
                        <div style="font-size: 12px; color: #e65100; font-weight: bold; text-align: center;">
                            🔥 {home if focus_team != "away" else away} ma przewagę w formie!
                        </div>
                    </td>
                </tr>
                ''' if form_advantage else ''}
                
                <!-- SOFASCORE (tylko gdy dane są dostępne) -->
                {f'''
                <tr>
                    <td colspan="2" style="background: #f0f4f8; padding: 12px;">
                        <div style="font-size: 10px; color: #666; margin-bottom: 6px;">🗳️ SofaScore Fan Vote {f'({int(ss_votes)} głosów)' if ss_votes > 0 else ''}</div>
                        <table width="100%">
                            <tr>
                                <td align="center" style="font-size: 16px; font-weight: bold; color: {'#4CAF50' if ss_home and ss_home >= max(ss_home or 0, ss_draw or 0, ss_away or 0) else '#333'};">🏠 {int(ss_home)}%</td>
                                {'<td align="center" style="font-size: 16px; font-weight: bold; color: #666;">🤝 ' + str(int(ss_draw)) + '%</td>' if ss_draw else ''}
                                <td align="center" style="font-size: 16px; font-weight: bold; color: {'#F44336' if ss_away and ss_away >= max(ss_home or 0, ss_draw or 0, ss_away or 0) else '#333'};">✈️ {int(ss_away)}%</td>
                            </tr>
                        </table>
                    </td>
                </tr>
                ''' if ss_home and ss_away else ''}
                
                <!-- KURSY (pokazuj gdy jest jakiekolwiek dane) -->
                {f'''
                <tr>
                    <td colspan="2" style="background: white; padding: 12px;">
                        <div style="font-size: 10px; color: #666; margin-bottom: 6px;">💰 Kursy bukmacherskie</div>
                        <table width="100%">
                            <tr>
                                <td align="center" style="padding: 5px;">
                                    <div style="background: {'#4CAF50' if home_odds and away_odds and home_odds < away_odds else '#f5f5f5'}; padding: 8px 12px; border-radius: 6px;">
                                        <div style="font-size: 16px; font-weight: bold; color: {'white' if home_odds and away_odds and home_odds < away_odds else '#333'};">{f"{home_odds:.2f}" if home_odds else "N/A"}</div>
                                        <div style="font-size: 10px; color: {'white' if home_odds and away_odds and home_odds < away_odds else '#888'};">1</div>
                                    </div>
                                </td>
                                {f'<td align="center" style="padding: 5px;"><div style="background: #f5f5f5; padding: 8px 12px; border-radius: 6px;"><div style="font-size: 16px; font-weight: bold; color: #333;">' + f'{draw_odds:.2f}' + '</div><div style="font-size: 10px; color: #888;">X</div></div></td>' if draw_odds else ''}
                                <td align="center" style="padding: 5px;">
                                    <div style="background: {'#4CAF50' if home_odds and away_odds and away_odds < home_odds else '#f5f5f5'}; padding: 8px 12px; border-radius: 6px;">
                                        <div style="font-size: 16px; font-weight: bold; color: {'white' if home_odds and away_odds and away_odds < home_odds else '#333'};">{f"{away_odds:.2f}" if away_odds else "N/A"}</div>
                                        <div style="font-size: 10px; color: {'white' if home_odds and away_odds and away_odds < home_odds else '#888'};">2</div>
                                    </div>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
                ''' if home_odds or away_odds or draw_odds else ''}
                
                <!-- FOREBET (pokazuj gdy jest jakiekolwiek dane) -->
                {f'''
                <tr>
                    <td colspan="2" style="background: linear-gradient(135deg, #FF9800, #FF5722); padding: 12px;">
                        <table width="100%">
                            <tr>
                                <td style="color: white;">
                                    <div style="font-size: 10px; opacity: 0.8;">🎯 Forebet</div>
                                    <div style="font-size: 18px; font-weight: bold;">{fb_pred if fb_pred else 'N/A'}</div>
                                </td>
                                <td align="right" style="color: white;">
                                    <div style="font-size: 10px; opacity: 0.8;">Prawdopodobieństwo</div>
                                    <div style="font-size: 22px; font-weight: bold;">{f"{fb_prob_clean:.0f}%" if fb_prob_clean else 'N/A'}</div>
                                </td>
                                {f'<td align="right" style="color: white;"><div style="background: rgba(255,255,255,0.2); padding: 6px 10px; border-radius: 6px;"><div style="font-size: 10px; opacity: 0.8;">Wynik</div><div style="font-size: 14px; font-weight: bold;">' + str(fb_exact) + '</div></div></td>' if fb_exact else ''}
                            </tr>
                        </table>
                    </td>
                </tr>
                ''' if fb_pred or fb_prob_clean or fb_exact else ''}
                
                <!-- FOOTER -->
                <tr>
                    <td colspan="2" style="background: #764ba2; padding: 10px; text-align: center;">
                        <a href="{match_url}" style="color: white; text-decoration: none; font-size: 12px;">🔗 Zobacz szczegóły meczu →</a>
                    </td>
                </tr>
            </table>
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
    skip_no_odds: bool = False
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
    """
    
    # Wczytaj dane
    print(f"Wczytuje dane z: {csv_file}")
    df = pd.read_csv(csv_file, encoding='utf-8')
    
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
    html_content = create_html_email(matches, date, sort_by=sort_by)
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

