"""
ESPN API Client - Alternatywne źródło danych sportowych
========================================================

Backup dla SofaScore API. Pobiera:
- Live scores
- Scheduled events
- Team standings

Użycie:
    python espn_api_client.py --live
    python espn_api_client.py --schedule --sport football
"""

import os
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


@dataclass
class ESPNMatch:
    """Reprezentacja meczu z ESPN"""
    id: str
    home_team: str
    away_team: str
    home_score: int = 0
    away_score: int = 0
    status: str = "scheduled"  # scheduled, live, finished
    start_time: str = ""
    league: str = ""
    sport: str = "football"
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "homeTeam": self.home_team,
            "awayTeam": self.away_team,
            "homeScore": self.home_score,
            "awayScore": self.away_score,
            "status": self.status,
            "time": self.start_time,
            "league": self.league,
            "sport": self.sport
        }


class ESPNAPIClient:
    """
    Klient dla ESPN API.
    Obsługuje wiele sportów jako backup dla SofaScore.
    """
    
    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
    
    SPORT_PATHS = {
        'football': 'soccer/eng.1',        # Premier League
        'basketball': 'basketball/nba',
        'hockey': 'hockey/nhl',
        'baseball': 'baseball/mlb',
        'american_football': 'football/nfl'
    }
    
    SOCCER_LEAGUES = {
        'premier_league': 'soccer/eng.1',
        'la_liga': 'soccer/esp.1',
        'bundesliga': 'soccer/ger.1',
        'serie_a': 'soccer/ita.1',
        'ligue_1': 'soccer/fra.1',
        'champions_league': 'soccer/uefa.champions',
        'europa_league': 'soccer/uefa.europa'
    }
    
    def __init__(self):
        self.session = requests.Session() if REQUESTS_AVAILABLE else None
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }) if self.session else None
    
    def _make_request(self, url: str) -> Optional[Dict]:
        """Wykonuje request do ESPN API"""
        if not self.session:
            return None
        
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"ESPN API error: {response.status_code}")
                return None
        except Exception as e:
            print(f"ESPN API request failed: {e}")
            return None
    
    def get_live_scores(self, sport: str = 'football') -> List[ESPNMatch]:
        """
        Pobiera wyniki na żywo.
        
        Args:
            sport: Typ sportu (football, basketball, hockey)
            
        Returns:
            Lista ESPNMatch
        """
        path = self.SPORT_PATHS.get(sport, 'soccer/eng.1')
        url = f"{self.BASE_URL}/{path}/scoreboard"
        
        data = self._make_request(url)
        if not data:
            return []
        
        matches = []
        events = data.get('events', [])
        
        for event in events:
            try:
                competition = event.get('competitions', [{}])[0]
                competitors = competition.get('competitors', [])
                
                if len(competitors) < 2:
                    continue
                
                # ESPN uses home/away in competitors
                home = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
                away = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1])
                
                status_info = event.get('status', {})
                status_type = status_info.get('type', {}).get('name', 'STATUS_SCHEDULED')
                
                # Map ESPN status to our format
                if status_type == 'STATUS_IN_PROGRESS':
                    status = 'live'
                elif status_type == 'STATUS_FINAL':
                    status = 'finished'
                elif status_type == 'STATUS_HALFTIME':
                    status = 'halftime'
                else:
                    status = 'scheduled'
                
                match = ESPNMatch(
                    id=event.get('id', ''),
                    home_team=home.get('team', {}).get('displayName', ''),
                    away_team=away.get('team', {}).get('displayName', ''),
                    home_score=int(home.get('score', 0) or 0),
                    away_score=int(away.get('score', 0) or 0),
                    status=status,
                    start_time=status_info.get('displayClock', ''),
                    league=event.get('season', {}).get('type', {}).get('name', ''),
                    sport=sport
                )
                matches.append(match)
                
            except Exception as e:
                print(f"Error parsing ESPN event: {e}")
                continue
        
        return matches
    
    def get_scheduled_events(self, sport: str = 'football', date: str = None) -> List[ESPNMatch]:
        """
        Pobiera zaplanowane mecze.
        
        Args:
            sport: Typ sportu
            date: Data w formacie YYYYMMDD (optional)
            
        Returns:
            Lista ESPNMatch
        """
        path = self.SPORT_PATHS.get(sport, 'soccer/eng.1')
        
        if date:
            url = f"{self.BASE_URL}/{path}/scoreboard?dates={date}"
        else:
            url = f"{self.BASE_URL}/{path}/scoreboard"
        
        data = self._make_request(url)
        if not data:
            return []
        
        matches = []
        events = data.get('events', [])
        
        for event in events:
            try:
                competition = event.get('competitions', [{}])[0]
                competitors = competition.get('competitors', [])
                
                if len(competitors) < 2:
                    continue
                
                home = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
                away = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1])
                
                # Parse start time
                start_time = event.get('date', '')
                if start_time:
                    try:
                        dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                        start_time = dt.strftime('%H:%M')
                    except Exception:
                        pass
                
                match = ESPNMatch(
                    id=event.get('id', ''),
                    home_team=home.get('team', {}).get('displayName', ''),
                    away_team=away.get('team', {}).get('displayName', ''),
                    status='scheduled',
                    start_time=start_time,
                    league=event.get('season', {}).get('type', {}).get('name', ''),
                    sport=sport
                )
                matches.append(match)
                
            except Exception as e:
                continue
        
        return matches
    
    def get_soccer_scores(self, league: str = 'premier_league') -> List[ESPNMatch]:
        """
        Pobiera wyniki dla konkretnej ligi piłkarskiej.
        
        Args:
            league: Nazwa ligi (premier_league, la_liga, etc.)
            
        Returns:
            Lista ESPNMatch
        """
        path = self.SOCCER_LEAGUES.get(league, 'soccer/eng.1')
        url = f"{self.BASE_URL}/{path}/scoreboard"
        
        data = self._make_request(url)
        if not data:
            return []
        
        matches = []
        events = data.get('events', [])
        
        for event in events:
            try:
                competition = event.get('competitions', [{}])[0]
                competitors = competition.get('competitors', [])
                
                if len(competitors) < 2:
                    continue
                
                home = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
                away = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1])
                
                status_info = event.get('status', {})
                status_type = status_info.get('type', {}).get('name', '')
                
                status = 'live' if 'PROGRESS' in status_type else 'finished' if 'FINAL' in status_type else 'scheduled'
                
                match = ESPNMatch(
                    id=event.get('id', ''),
                    home_team=home.get('team', {}).get('displayName', ''),
                    away_team=away.get('team', {}).get('displayName', ''),
                    home_score=int(home.get('score', 0) or 0),
                    away_score=int(away.get('score', 0) or 0),
                    status=status,
                    start_time=status_info.get('displayClock', ''),
                    league=league.replace('_', ' ').title(),
                    sport='football'
                )
                matches.append(match)
                
            except Exception:
                continue
        
        return matches
    
    def print_scores(self, matches: List[ESPNMatch]):
        """Wyświetla wyniki w czytelnym formacie"""
        print("\n" + "="*60)
        print("ESPN LIVE SCORES")
        print("="*60)
        
        for match in matches:
            status_icon = "LIVE" if match.status == 'live' else "FT" if match.status == 'finished' else match.start_time
            print(f"\n[{status_icon}] {match.home_team} {match.home_score} - {match.away_score} {match.away_team}")
            print(f"      {match.league}")
        
        print("\n" + "="*60)


def main():
    """Główna funkcja CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='ESPN API Client dla BigOne')
    parser.add_argument('--live', action='store_true', help='Pobierz live scores')
    parser.add_argument('--schedule', action='store_true', help='Pobierz scheduled events')
    parser.add_argument('--sport', type=str, default='football', help='Sport (football, basketball, hockey)')
    parser.add_argument('--league', type=str, help='Liga piłkarska (premier_league, la_liga, etc.)')
    parser.add_argument('--date', type=str, help='Data (YYYYMMDD)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    args = parser.parse_args()
    
    client = ESPNAPIClient()
    
    if args.league:
        matches = client.get_soccer_scores(args.league)
    elif args.live:
        matches = client.get_live_scores(args.sport)
    elif args.schedule:
        matches = client.get_scheduled_events(args.sport, args.date)
    else:
        matches = client.get_live_scores(args.sport)
    
    if args.json:
        print(json.dumps([m.to_dict() for m in matches], indent=2, ensure_ascii=False))
    else:
        client.print_scores(matches)
        print(f"\nZnaleziono {len(matches)} meczow")


if __name__ == '__main__':
    main()
