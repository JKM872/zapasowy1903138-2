"""
Discord Webhook dla BigOne - Powiadomienia o predykcjach sportowych
===================================================================

Wysyła embed z predykcjami do kanału Discord przez webhook.

Konfiguracja:
    Ustaw zmienną środowiskową:
    - DISCORD_WEBHOOK_URL: URL webhooka Discord

Użycie:
    python discord_webhook.py --today
    python discord_webhook.py --summary
"""

import os
import sys
import json
import requests
from datetime import datetime
from typing import List, Dict, Optional

# Konfiguracja
WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'outputs')

# Kolory embedów
COLORS = {
    'green': 0x2EA043,
    'red': 0xF85149,
    'yellow': 0xD29922,
    'blue': 0x58A6FF,
    'purple': 0xA371F7,
    'orange': 0xD18616
}


class DiscordNotifier:
    """
    Wysyła powiadomienia do Discord przez webhook.
    Obsługuje embedy z formatowaniem.
    """
    
    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url or WEBHOOK_URL
    
    def send_embed(
        self,
        title: str,
        description: str = "",
        color: int = COLORS['blue'],
        fields: List[Dict] = None,
        footer: str = None,
        thumbnail_url: str = None
    ) -> bool:
        """
        Wysyła embed do Discord.
        
        Args:
            title: Tytuł embeda
            description: Opis
            color: Kolor (hex int)
            fields: Lista pól [{name, value, inline}]
            footer: Stopka
            thumbnail_url: URL miniatury
            
        Returns:
            True jeśli sukces
        """
        if not self.webhook_url:
            print("❌ Brak DISCORD_WEBHOOK_URL")
            return False
        
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if fields:
            embed["fields"] = fields
        
        if footer:
            embed["footer"] = {"text": footer}
        
        if thumbnail_url:
            embed["thumbnail"] = {"url": thumbnail_url}
        
        payload = {
            "embeds": [embed]
        }
        
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code in [200, 204]:
                print(f"✅ Discord: Wysłano embed '{title}'")
                return True
            else:
                print(f"❌ Discord: Błąd {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Discord: {e}")
            return False
    
    def send_match(self, match: Dict) -> bool:
        """Wysyła informacje o pojedynczym meczu"""
        home = match.get('homeTeam', '?')
        away = match.get('awayTeam', '?')
        time = match.get('time', '?')
        league = match.get('league', '')
        sport = match.get('sport', 'football')
        
        # Wybierz kolor według sportu
        sport_colors = {
            'football': COLORS['green'],
            'basketball': COLORS['orange'],
            'volleyball': COLORS['blue'],
            'handball': COLORS['purple'],
            'hockey': COLORS['blue'],
            'tennis': COLORS['yellow']
        }
        color = sport_colors.get(sport, COLORS['blue'])
        
        # H2H
        h2h = match.get('h2h', {})
        h2h_str = f"{h2h.get('home', 0)} - {h2h.get('draw', 0)} - {h2h.get('away', 0)}"
        win_rate = h2h.get('winRate', 0)
        
        # Kursy
        odds = match.get('odds', {})
        odds_home = odds.get('home', '-')
        odds_away = odds.get('away', '-')
        
        # Forebet
        forebet = match.get('forebet', {})
        pred = forebet.get('prediction', '')
        pred_map = {'1': '🏠 HOME', 'X': '🤝 DRAW', '2': '✈️ AWAY'}
        forebet_str = f"{pred_map.get(pred, pred)} ({forebet.get('probability', '?')}%)" if pred else "N/A"
        
        # Forma
        home_form = ''.join(['🟢' if f == 'W' else '🟡' if f == 'D' else '🔴' for f in match.get('homeForm', [])[:5]])
        away_form = ''.join(['🟢' if f == 'W' else '🟡' if f == 'D' else '🔴' for f in match.get('awayForm', [])[:5]])
        
        # Status
        qualifies = "✅ Kwalifikuje" if match.get('qualifies') else ""
        form_adv = "🔥 Przewaga formy" if match.get('formAdvantage') else ""
        status = f"{qualifies} {form_adv}".strip() or "⏳ Oczekujący"
        
        fields = [
            {"name": "🕐 Czas", "value": time, "inline": True},
            {"name": "🏆 Liga", "value": league or "N/A", "inline": True},
            {"name": "📊 H2H", "value": f"{h2h_str} ({win_rate}%)", "inline": True},
            {"name": "💰 Kursy", "value": f"🏠 {odds_home} | ✈️ {odds_away}", "inline": True},
            {"name": "🎯 Forebet", "value": forebet_str, "inline": True},
            {"name": "📈 Status", "value": status, "inline": True},
            {"name": f"🏠 {home}", "value": home_form or "N/A", "inline": True},
            {"name": f"✈️ {away}", "value": away_form or "N/A", "inline": True},
        ]
        
        return self.send_embed(
            title=f"⚽ {home} vs {away}",
            color=color,
            fields=fields,
            footer=f"BigOne • {sport.capitalize()}"
        )
    
    def send_daily_summary(self, matches: List[Dict]) -> bool:
        """Wysyła podsumowanie dnia"""
        if not matches:
            return self.send_embed(
                title="📭 Brak meczów na dziś",
                description="Nie znaleziono meczów spełniających kryteria.",
                color=COLORS['yellow']
            )
        
        qualifying = [m for m in matches if m.get('qualifies')]
        form_adv = [m for m in matches if m.get('formAdvantage')]
        
        # Sporty
        sports_count = {}
        for m in matches:
            sport = m.get('sport', 'other')
            sports_count[sport] = sports_count.get(sport, 0) + 1
        
        sports_str = " | ".join([f"{s}: {c}" for s, c in sports_count.items()])
        
        fields = [
            {"name": "📌 Wszystkich meczów", "value": str(len(matches)), "inline": True},
            {"name": "✅ Kwalifikujących", "value": str(len(qualifying)), "inline": True},
            {"name": "🔥 Z przewagą formy", "value": str(len(form_adv)), "inline": True},
            {"name": "🏅 Sporty", "value": sports_str, "inline": False},
        ]
        
        # Top 3 mecze
        top_matches = sorted(
            qualifying,
            key=lambda x: x.get('h2h', {}).get('winRate', 0),
            reverse=True
        )[:3]
        
        if top_matches:
            top_str = "\n".join([
                f"• {m.get('homeTeam')} vs {m.get('awayTeam')} ({m.get('h2h', {}).get('winRate', 0)}%)"
                for m in top_matches
            ])
            fields.append({"name": "🏆 Top 3", "value": top_str, "inline": False})
        
        return self.send_embed(
            title=f"📊 Podsumowanie - {datetime.now().strftime('%d.%m.%Y')}",
            description="Dzienne zestawienie predykcji sportowych",
            color=COLORS['green'] if qualifying else COLORS['yellow'],
            fields=fields,
            footer="BigOne Sports Predictions"
        )
    
    def send_roi_update(self, stats: Dict) -> bool:
        """Wysyła aktualizację ROI"""
        profit = stats.get('total_profit', 0)
        color = COLORS['green'] if profit >= 0 else COLORS['red']
        
        fields = [
            {"name": "📈 Zakłady", "value": str(stats.get('total_bets', 0)), "inline": True},
            {"name": "✅ Wygrane", "value": f"{stats.get('wins', 0)} ({stats.get('win_rate', 0):.1f}%)", "inline": True},
            {"name": "❌ Przegrane", "value": str(stats.get('losses', 0)), "inline": True},
            {"name": "💰 Postawiono", "value": f"{stats.get('total_staked', 0):.2f} PLN", "inline": True},
            {"name": "📊 Profit", "value": f"{profit:+.2f} PLN", "inline": True},
            {"name": "📈 ROI", "value": f"{stats.get('roi_percent', 0):+.2f}%", "inline": True},
        ]
        
        return self.send_embed(
            title="📊 ROI Update",
            description="Statystyki z ostatnich 30 dni",
            color=color,
            fields=fields,
            footer="BigOne ROI Tracker"
        )


def get_today_matches() -> List[Dict]:
    """Pobiera mecze na dziś"""
    today = datetime.now().strftime('%Y-%m-%d')
    matches = []
    
    for sport in ['football', 'basketball', 'volleyball', 'handball', 'hockey', 'tennis']:
        filepath = os.path.join(DATA_DIR, f'matches_{today}_{sport}.json')
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    matches.extend(data.get('matches', []))
            except Exception:
                pass
    
    return matches


def main():
    """Główna funkcja CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Discord Webhook dla BigOne')
    parser.add_argument('--today', action='store_true', help='Wyślij mecze na dziś')
    parser.add_argument('--summary', action='store_true', help='Wyślij podsumowanie')
    parser.add_argument('--top', type=int, default=0, help='Wyślij top N meczów')
    parser.add_argument('--test', action='store_true', help='Test webhook')
    
    args = parser.parse_args()
    
    notifier = DiscordNotifier()
    
    if args.test:
        notifier.send_embed(
            title="🧪 Test BigOne",
            description="Webhook działa poprawnie!",
            color=COLORS['green'],
            footer="BigOne Test"
        )
        return
    
    if args.summary:
        matches = get_today_matches()
        notifier.send_daily_summary(matches)
        return
    
    if args.today or args.top > 0:
        matches = get_today_matches()
        qualifying = [m for m in matches if m.get('qualifies')]
        
        top_n = args.top if args.top > 0 else 5
        top_matches = sorted(
            qualifying,
            key=lambda x: x.get('h2h', {}).get('winRate', 0),
            reverse=True
        )[:top_n]
        
        for match in top_matches:
            notifier.send_match(match)
        
        print(f"✅ Wysłano {len(top_matches)} meczów")


if __name__ == '__main__':
    main()
