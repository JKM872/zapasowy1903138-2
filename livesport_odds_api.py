"""
🎯 Livesport Odds API Client
=============================
Pobiera kursy bukmacherskie bezpośrednio z GraphQL API Livesport.
Obsługuje wszystkie sporty: football, basketball, volleyball, handball, hockey, tennis, rugby.

Endpoint: https://global.ds.lsapp.eu/odds/pq_graphql

Bukmacherzy:
- 165: Nordic Bet (domyślny)
- 16: bet365
- 8: Unibet
- 43: William Hill
- 14: Bwin
- 24: Betfair
- 3: Pinnacle
"""

import re
import requests
from typing import Dict, Optional, List
import time

# Mapowanie bukmacherów ID
BOOKMAKER_IDS = {
    'pinnacle': '3',
    'nordic_bet': '165',
    'nordicbet': '165',
    'bet365': '16',
    'unibet': '8',
    'william_hill': '43',
    'bwin': '14',
    'betfair': '24',
    '1xbet': '1',
    'betway': '10',
}

# Sporty i ich typy zakładów
SPORT_BET_TYPES = {
    # Sporty z remisem (1X2)
    'football': {'betType': 'HOME_DRAW_AWAY', 'has_draw': True},
    'soccer': {'betType': 'HOME_DRAW_AWAY', 'has_draw': True},
    'handball': {'betType': 'HOME_DRAW_AWAY', 'has_draw': True},
    'hockey': {'betType': 'HOME_DRAW_AWAY', 'has_draw': True},
    'ice-hockey': {'betType': 'HOME_DRAW_AWAY', 'has_draw': True},
    'rugby': {'betType': 'HOME_DRAW_AWAY', 'has_draw': True},
    
    # Sporty bez remisu (1X2 ale draw jest rzadki/nie ma)
    'basketball': {'betType': 'HOME_DRAW_AWAY', 'has_draw': False},
    
    # Sporty tylko 1 lub 2
    'volleyball': {'betType': 'HOME_AWAY', 'has_draw': False},
    'tennis': {'betType': 'HOME_AWAY', 'has_draw': False},
    'badminton': {'betType': 'HOME_AWAY', 'has_draw': False},
    'table_tennis': {'betType': 'HOME_AWAY', 'has_draw': False},
}


class LivesportOddsAPI:
    """
    Klient API do pobierania kursów z Livesport GraphQL.
    
    Przykład użycia:
        api = LivesportOddsAPI()
        odds = api.get_odds_for_match('https://www.livesport.com/pl/mecz/...', sport='basketball')
    """
    
    def __init__(self, bookmaker_id: str = "3", geo_ip_code: str = "PL", geo_subdivision: str = "PL10"):
        """
        Args:
            bookmaker_id: ID bukmachera (domyślnie 3 = Pinnacle)
            geo_ip_code: Kod kraju
            geo_subdivision: Podregion
        """
        self.bookmaker_id = bookmaker_id
        self.api_url = "https://global.ds.lsapp.eu/odds/pq_graphql"
        self.geo_ip_code = geo_ip_code
        self.geo_subdivision = geo_subdivision
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9,pl;q=0.8',
            'Origin': 'https://www.livesport.com',
            'Referer': 'https://www.livesport.com/',
            'x-geoip-code': geo_ip_code,
            'x-geoip-subdivision': geo_subdivision,
        })
    
    def extract_event_id_from_url(self, url: str) -> Optional[str]:
        """
        Wydobywa Event ID z URL Livesport.
        
        Formaty:
        - ?mid=KQAaF7d2
        - &mid=KQAaF7d2
        - #id/KQAaF7d2
        - /mecz/.../KQAaF7d2/
        - /mecz/.../KQAaF7d2/h2h/ogolem/
        - /match/.../KQAaF7d2/
        """
        if not url:
            return None
        
        # Oczyszczenie URL
        url = url.strip()
            
        # Metoda 1: Parametr ?mid= lub &mid=
        match = re.search(r'[?&]mid=([a-zA-Z0-9]+)', url)
        if match:
            return match.group(1)
        
        # Metoda 2: Hash #id/
        match = re.search(r'#id/([a-zA-Z0-9]+)', url)
        if match:
            return match.group(1)
        
        # Metoda 3: Format URL /mecz/.../EventID/ lub /mecz/.../EventID/h2h/...
        # https://www.livesport.com/pl/mecz/pilka-nozna/...team1-team2/KQAaF7d2/
        # https://www.livesport.com/pl/mecz/pilka-nozna/...team1-team2/KQAaF7d2/h2h/ogolem/
        
        # Lista słów które NIE są Event ID
        excluded_words = [
            'szczegoly', 'h2h', 'statystyki', 'kursy', 'mecz', 'match', 
            'ogolem', 'overall', 'wyniki', 'results', 'live', 'lineup', 
            'sklad', 'odds', 'video', 'news', 'draw', 'pilka-nozna', 
            'koszykowka', 'siatkowka', 'pilka-reczna', 'hokej', 'tenis',
            'football', 'basketball', 'volleyball', 'handball', 'hockey', 'tennis',
            'rugby', 'pl', 'en', 'de', 'es', 'fr', 'it'
        ]
        
        parts = url.rstrip('/').split('/')
        for part in reversed(parts):
            # Event ID ma typowo 6-10 znaków alfanumerycznych
            if re.match(r'^[a-zA-Z0-9]{6,10}$', part):
                # Nie może być fragmentem URL
                if part.lower() not in excluded_words:
                    return part
        
        return None
    
    def get_odds_for_event(self, event_id: str, sport: str = 'football') -> Optional[Dict]:
        """
        Pobiera kursy dla wydarzenia z API GraphQL.
        
        Args:
            event_id: ID wydarzenia (np. 'KQAaF7d2')
            sport: Typ sportu dla określenia formatu zakładu
            
        Returns:
            Dict z kursami lub None
        """
        sport_config = SPORT_BET_TYPES.get(sport.lower(), SPORT_BET_TYPES['football'])
        bet_type = sport_config['betType']
        has_draw = sport_config['has_draw']
        
        # Debug logging dla volleyball/tennis (sporty bez remisu)
        is_no_draw_sport = sport.lower() in ['volleyball', 'tennis', 'badminton', 'table_tennis']
        if is_no_draw_sport:
            print(f"   🔍 {sport.title()} API: event_id={event_id}, betType={bet_type}, has_draw={has_draw}")
        
        result = {
            'home_odds': None,
            'draw_odds': None,
            'away_odds': None,
            'bookmaker_id': self.bookmaker_id,
            'event_id': event_id,
            'success': False
        }
        
        try:
            # GraphQL query parameters
            params = {
                '_hash': 'ope2',
                'eventId': event_id,
                'bookmakerId': self.bookmaker_id,
                'betType': bet_type,
                'betScope': 'FULL_TIME'
            }
            
            response = self.session.get(
                self.api_url, 
                params=params, 
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"   ⚠️ Livesport API: HTTP {response.status_code}")
                return result
            
            data = response.json()
            
            # Parsuj odpowiedź GraphQL
            if 'data' in data and 'findPrematchOddsForBookmaker' in data['data']:
                odds_data = data['data']['findPrematchOddsForBookmaker']
                
                if odds_data:
                    # Home odds
                    if 'home' in odds_data and odds_data['home']:
                        try:
                            result['home_odds'] = float(odds_data['home']['value'])
                        except (KeyError, ValueError, TypeError):
                            pass
                    
                    # Draw odds (jeśli sport ma remis)
                    if has_draw and 'draw' in odds_data and odds_data['draw']:
                        try:
                            result['draw_odds'] = float(odds_data['draw']['value'])
                        except (KeyError, ValueError, TypeError):
                            pass
                    
                    # Away odds
                    if 'away' in odds_data and odds_data['away']:
                        try:
                            result['away_odds'] = float(odds_data['away']['value'])
                        except (KeyError, ValueError, TypeError):
                            pass
                    
                    if result['home_odds'] or result['away_odds']:
                        result['success'] = True
            
            # Alternatywna struktura odpowiedzi
            elif 'data' in data and isinstance(data['data'], dict):
                for key, value in data['data'].items():
                    if isinstance(value, dict):
                        if 'home' in value or 'away' in value:
                            if 'home' in value and value['home']:
                                try:
                                    result['home_odds'] = float(value['home'].get('value', value['home']))
                                except:
                                    pass
                            if 'away' in value and value['away']:
                                try:
                                    result['away_odds'] = float(value['away'].get('value', value['away']))
                                except:
                                    pass
                            if has_draw and 'draw' in value and value['draw']:
                                try:
                                    result['draw_odds'] = float(value['draw'].get('value', value['draw']))
                                except:
                                    pass
                            
                            if result['home_odds'] or result['away_odds']:
                                result['success'] = True
                                break
                    
        except requests.exceptions.Timeout:
            print(f"   ⚠️ Livesport API: Timeout")
        except requests.exceptions.RequestException as e:
            print(f"   ⚠️ Livesport API error: {e}")
        except Exception as e:
            print(f"   ⚠️ Livesport API parsing error: {e}")
        
        # 🔧 Zawsze ustaw draw_odds na None dla sportów bez remisu
        if not has_draw:
            result['draw_odds'] = None
        
        # Debug logging dla volleyball/tennis gdy brak kursów
        if is_no_draw_sport and not result['success']:
            print(f"   ⚠️ {sport.title()} API: Brak kursów dla event {event_id}")
        
        return result
    
    def get_odds_from_multiple_bookmakers(self, event_id: str, sport: str = 'football', 
                                          bookmakers: List[str] = None) -> Dict:
        """
        Pobiera kursy od wielu bukmacherów i wybiera najlepsze.
        
        Args:
            event_id: ID wydarzenia
            sport: Typ sportu
            bookmakers: Lista nazw bukmacherów do sprawdzenia
            
        Returns:
            Dict z najlepszymi kursami i źródłem
        """
        if bookmakers is None:
            # OPTYMALIZACJA: Tylko 2 bukmacherów (zamiast 6) — osczędza ~40s/mecz
            bookmakers = ['pinnacle', 'bet365']
        
        best_result = {
            'home_odds': None,
            'draw_odds': None,
            'away_odds': None,
            'bookmaker': None,
            'success': False
        }
        
        for bookmaker_name in bookmakers:
            bookmaker_id = BOOKMAKER_IDS.get(bookmaker_name.lower())
            if not bookmaker_id:
                continue
            
            # Ustaw tymczasowo innego bukmachera
            original_id = self.bookmaker_id
            self.bookmaker_id = bookmaker_id
            
            try:
                result = self.get_odds_for_event(event_id, sport)
                
                if result and result.get('success'):
                    best_result['home_odds'] = result.get('home_odds')
                    best_result['draw_odds'] = result.get('draw_odds')
                    best_result['away_odds'] = result.get('away_odds')
                    best_result['bookmaker'] = bookmaker_name.replace('_', ' ').title()
                    best_result['success'] = True
                    break  # Znaleziono, przerwij szukanie
                    
            finally:
                self.bookmaker_id = original_id
        
        return best_result
    
    def get_odds_for_match(self, match_url: str, sport: str = 'football') -> Dict:
        """
        Główna metoda - pobiera kursy dla meczu na podstawie URL.
        
        Args:
            match_url: URL strony meczu Livesport
            sport: Typ sportu
            
        Returns:
            Dict z kursami
        """
        result = {
            'home_odds': None,
            'draw_odds': None,
            'away_odds': None,
            'bookmaker': None,
            'odds_found': False,
            'event_id': None
        }
        
        # Wydobądź event ID z URL
        event_id = self.extract_event_id_from_url(match_url)
        
        if not event_id:
            print(f"   ⚠️ Livesport API: Nie można wydobyć Event ID z URL")
            return result
        
        result['event_id'] = event_id
        
        # Pobierz kursy od wielu bukmacherów
        odds = self.get_odds_from_multiple_bookmakers(event_id, sport)
        
        if odds.get('success'):
            result['home_odds'] = odds.get('home_odds')
            result['draw_odds'] = odds.get('draw_odds')
            result['away_odds'] = odds.get('away_odds')
            result['bookmaker'] = odds.get('bookmaker')
            result['odds_found'] = True
            
            print(f"   ✅ Livesport API: {odds.get('bookmaker')} - {result['home_odds']}/{result.get('draw_odds', '-')}/{result['away_odds']}")
        else:
            print(f"   ⚠️ Livesport API: Brak kursów dla event {event_id}")
        
        return result


def get_livesport_odds(match_url: str, sport: str = 'football') -> Dict:
    """
    Funkcja pomocnicza do szybkiego pobierania kursów.
    
    Przykład:
        odds = get_livesport_odds('https://www.livesport.com/pl/mecz/...', 'basketball')
    """
    api = LivesportOddsAPI()
    return api.get_odds_for_match(match_url, sport)


# ============================================================================
# TESTING / CLI
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) >= 2:
        url = sys.argv[1]
        sport = sys.argv[2] if len(sys.argv) > 2 else 'football'
        
        print(f"\n🔍 Pobieranie kursów z Livesport API")
        print(f"URL: {url}")
        print(f"Sport: {sport}")
        print()
        
        api = LivesportOddsAPI()
        
        # Test wydobywania ID
        event_id = api.extract_event_id_from_url(url)
        print(f"Event ID: {event_id}")
        
        if event_id:
            # Test pobierania kursów
            result = api.get_odds_for_match(url, sport)
            
            print(f"\n📊 Wyniki:")
            print(f"Home odds: {result.get('home_odds', 'N/A')}")
            print(f"Draw odds: {result.get('draw_odds', 'N/A')}")
            print(f"Away odds: {result.get('away_odds', 'N/A')}")
            print(f"Bookmaker: {result.get('bookmaker', 'N/A')}")
            print(f"Success: {result.get('odds_found', False)}")
    else:
        print("Usage: python livesport_odds_api.py <match_url> [sport]")
        print("Example: python livesport_odds_api.py 'https://www.livesport.com/pl/mecz/...' basketball")
