"""
Streak Analyzer - Analiza serii wyników drużyn
==============================================

Wykrywa hot/cold teams, trendy i serie wyników.
Pomocne przy identyfikacji drużyn w dobrej/złej formie.

Użycie:
    python streak_analyzer.py --team "Manchester United"
    python streak_analyzer.py --hot --sport football
"""

import os
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


class StreakType(Enum):
    HOT = "hot"      # Seria wygranych
    COLD = "cold"    # Seria przegranych
    NEUTRAL = "neutral"


@dataclass
class TeamStreak:
    """Informacje o serii wyników drużyny"""
    team_name: str
    sport: str
    current_streak: int  # Dodatnia = wygrane, ujemna = przegrane
    streak_type: StreakType
    last_5_results: List[str]  # W, D, L
    last_10_results: List[str]
    win_rate_5: float
    win_rate_10: float
    goals_scored_avg: float = 0.0
    goals_conceded_avg: float = 0.0
    trend: str = "stable"  # improving, declining, stable
    
    @property
    def form_rating(self) -> int:
        """Ocena formy 0-100"""
        # Waga: ostatnie 5 meczów = 60%, ostatnie 10 = 40%
        rating = (self.win_rate_5 * 0.6 + self.win_rate_10 * 0.4) * 100
        
        # Bonus za streak
        if self.streak_type == StreakType.HOT:
            rating += min(self.current_streak * 3, 15)
        elif self.streak_type == StreakType.COLD:
            rating -= min(abs(self.current_streak) * 3, 15)
        
        return max(0, min(100, int(rating)))
    
    def to_dict(self) -> Dict:
        return {
            "team_name": self.team_name,
            "sport": self.sport,
            "current_streak": self.current_streak,
            "streak_type": self.streak_type.value,
            "last_5": self.last_5_results,
            "last_10": self.last_10_results,
            "win_rate_5": round(self.win_rate_5, 3),
            "win_rate_10": round(self.win_rate_10, 3),
            "form_rating": self.form_rating,
            "trend": self.trend
        }


class StreakAnalyzer:
    """
    Analizuje serie wyników drużyn.
    """
    
    def __init__(self, data_dir: str = "outputs"):
        self.data_dir = data_dir
        self.team_data: Dict[str, List[Dict]] = {}
    
    def analyze_team(self, team_name: str, matches: List[Dict]) -> TeamStreak:
        """
        Analizuje formę konkretnej drużyny.
        
        Args:
            team_name: Nazwa drużyny
            matches: Lista meczów z wynikami
            
        Returns:
            TeamStreak z analizą
        """
        # Filtruj mecze tej drużyny
        team_matches = []
        for match in matches:
            home = match.get('home_team', '').lower()
            away = match.get('away_team', '').lower()
            team_lower = team_name.lower()
            
            if team_lower in home or team_lower in away:
                is_home = team_lower in home
                result = match.get('result') or match.get('actual_result')
                
                if result:
                    # Przelicz wynik z perspektywy drużyny
                    if is_home:
                        team_result = 'W' if result == '1' else 'D' if result == 'X' else 'L'
                    else:
                        team_result = 'W' if result == '2' else 'D' if result == 'X' else 'L'
                    
                    team_matches.append({
                        'date': match.get('date', match.get('match_date', '')),
                        'result': team_result,
                        'goals_for': match.get('home_score' if is_home else 'away_score', 0),
                        'goals_against': match.get('away_score' if is_home else 'home_score', 0)
                    })
        
        # Sortuj po dacie (najnowsze najpierw)
        team_matches.sort(key=lambda x: x['date'], reverse=True)
        
        # Ostatnie 5 i 10 wyników
        last_5 = [m['result'] for m in team_matches[:5]]
        last_10 = [m['result'] for m in team_matches[:10]]
        
        # Win rates
        def calc_win_rate(results: List[str]) -> float:
            if not results:
                return 0.5
            wins = results.count('W')
            draws = results.count('D')
            return (wins + draws * 0.5) / len(results)
        
        win_rate_5 = calc_win_rate(last_5)
        win_rate_10 = calc_win_rate(last_10)
        
        # Oblicz streak
        streak = 0
        if last_5:
            first_result = last_5[0]
            for r in last_5:
                if r == first_result:
                    streak += 1 if first_result == 'W' else -1 if first_result == 'L' else 0
                else:
                    break
        
        # Określ typ streaka
        if streak >= 3:
            streak_type = StreakType.HOT
        elif streak <= -3:
            streak_type = StreakType.COLD
        else:
            streak_type = StreakType.NEUTRAL
        
        # Trend (porównaj ostatnie 5 z poprzednimi 5)
        if len(last_10) >= 10:
            prev_5 = last_10[5:10]
            prev_rate = calc_win_rate(prev_5)
            if win_rate_5 > prev_rate + 0.15:
                trend = "improving"
            elif win_rate_5 < prev_rate - 0.15:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "stable"
        
        # Średnia bramek
        goals_for = [m['goals_for'] for m in team_matches[:10] if m.get('goals_for') is not None]
        goals_against = [m['goals_against'] for m in team_matches[:10] if m.get('goals_against') is not None]
        
        return TeamStreak(
            team_name=team_name,
            sport=matches[0].get('sport', 'football') if matches else 'football',
            current_streak=streak,
            streak_type=streak_type,
            last_5_results=last_5,
            last_10_results=last_10,
            win_rate_5=win_rate_5,
            win_rate_10=win_rate_10,
            goals_scored_avg=sum(goals_for) / len(goals_for) if goals_for else 0,
            goals_conceded_avg=sum(goals_against) / len(goals_against) if goals_against else 0,
            trend=trend
        )
    
    def find_hot_teams(self, matches: List[Dict], min_streak: int = 3) -> List[TeamStreak]:
        """Znajduje drużyny w serii wygranych"""
        teams = self._extract_teams(matches)
        hot_teams = []
        
        for team in teams:
            streak = self.analyze_team(team, matches)
            if streak.streak_type == StreakType.HOT and streak.current_streak >= min_streak:
                hot_teams.append(streak)
        
        return sorted(hot_teams, key=lambda x: x.current_streak, reverse=True)
    
    def find_cold_teams(self, matches: List[Dict], min_streak: int = 3) -> List[TeamStreak]:
        """Znajduje drużyny w serii przegranych"""
        teams = self._extract_teams(matches)
        cold_teams = []
        
        for team in teams:
            streak = self.analyze_team(team, matches)
            if streak.streak_type == StreakType.COLD and abs(streak.current_streak) >= min_streak:
                cold_teams.append(streak)
        
        return sorted(cold_teams, key=lambda x: x.current_streak)
    
    def compare_teams(self, team1: str, team2: str, matches: List[Dict]) -> Dict:
        """Porównuje formę dwóch drużyn"""
        streak1 = self.analyze_team(team1, matches)
        streak2 = self.analyze_team(team2, matches)
        
        advantage = None
        advantage_score = 0
        
        rating_diff = streak1.form_rating - streak2.form_rating
        if abs(rating_diff) >= 10:
            advantage = team1 if rating_diff > 0 else team2
            advantage_score = abs(rating_diff)
        
        return {
            "team1": streak1.to_dict(),
            "team2": streak2.to_dict(),
            "advantage": advantage,
            "advantage_score": advantage_score,
            "rating_diff": rating_diff
        }
    
    def _extract_teams(self, matches: List[Dict]) -> List[str]:
        """Wyodrębnia unikalne nazwy drużyn"""
        teams = set()
        for match in matches:
            if match.get('home_team'):
                teams.add(match['home_team'])
            if match.get('away_team'):
                teams.add(match['away_team'])
        return list(teams)
    
    def load_matches_from_files(self, days: int = 30) -> List[Dict]:
        """Wczytuje mecze z plików JSON"""
        matches = []
        
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            
            for sport in ['football', 'basketball', 'volleyball', 'handball', 'hockey']:
                filepath = os.path.join(self.data_dir, f'results_{date}_{sport}.json')
                if not os.path.exists(filepath):
                    filepath = os.path.join(self.data_dir, f'matches_{date}_{sport}.json')
                
                if os.path.exists(filepath):
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            for m in data.get('results', data.get('matches', [])):
                                m['sport'] = sport
                                matches.append(m)
                    except Exception:
                        pass
        
        return matches
    
    def print_analysis(self, team_name: str, matches: List[Dict]):
        """Wyświetla analizę drużyny"""
        streak = self.analyze_team(team_name, matches)
        
        print("\n" + "="*50)
        print(f"ANALIZA: {team_name.upper()}")
        print("="*50)
        
        # Forma wizualna
        form_visual = ''.join([
            '🟢' if r == 'W' else '🟡' if r == 'D' else '🔴' 
            for r in streak.last_5_results
        ])
        print(f"\nOstatnie 5: {form_visual}")
        print(f"Win rate (5): {streak.win_rate_5*100:.0f}%")
        print(f"Win rate (10): {streak.win_rate_10*100:.0f}%")
        
        # Streak
        streak_emoji = '🔥' if streak.streak_type == StreakType.HOT else '❄️' if streak.streak_type == StreakType.COLD else '➖'
        print(f"\nStreak: {streak_emoji} {abs(streak.current_streak)} {'wygranych' if streak.current_streak > 0 else 'przegranych' if streak.current_streak < 0 else ''}")
        
        # Trend
        trend_map = {'improving': '📈 Rosnący', 'declining': '📉 Malejący', 'stable': '➡️ Stabilny'}
        print(f"Trend: {trend_map.get(streak.trend, streak.trend)}")
        
        # Rating
        print(f"\nForm Rating: {streak.form_rating}/100")
        
        print("="*50)


def main():
    """Główna funkcja CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Streak Analyzer dla BigOne')
    parser.add_argument('--team', type=str, help='Nazwa drużyny do analizy')
    parser.add_argument('--hot', action='store_true', help='Pokaż hot teams')
    parser.add_argument('--cold', action='store_true', help='Pokaż cold teams')
    parser.add_argument('--compare', nargs=2, help='Porównaj dwie drużyny')
    parser.add_argument('--days', type=int, default=30, help='Okres w dniach')
    
    args = parser.parse_args()
    
    analyzer = StreakAnalyzer()
    matches = analyzer.load_matches_from_files(args.days)
    
    print(f"Wczytano {len(matches)} meczów")
    
    if not matches:
        # Demo data
        matches = [
            {'home_team': 'Manchester United', 'away_team': 'Liverpool', 'result': '1', 'date': '2025-12-15', 'sport': 'football'},
            {'home_team': 'Manchester United', 'away_team': 'Chelsea', 'result': '1', 'date': '2025-12-10', 'sport': 'football'},
            {'home_team': 'Arsenal', 'away_team': 'Manchester United', 'result': '2', 'date': '2025-12-05', 'sport': 'football'},
            {'home_team': 'Manchester United', 'away_team': 'Tottenham', 'result': '1', 'date': '2025-12-01', 'sport': 'football'},
            {'home_team': 'Newcastle', 'away_team': 'Manchester United', 'result': '2', 'date': '2025-11-25', 'sport': 'football'},
        ]
        print("Używam demo danych")
    
    if args.team:
        analyzer.print_analysis(args.team, matches)
    
    if args.hot:
        hot = analyzer.find_hot_teams(matches)
        print("\n🔥 HOT TEAMS:")
        for t in hot[:10]:
            print(f"  {t.team_name}: {t.current_streak}W streak, rating {t.form_rating}")
    
    if args.cold:
        cold = analyzer.find_cold_teams(matches)
        print("\n❄️ COLD TEAMS:")
        for t in cold[:10]:
            print(f"  {t.team_name}: {abs(t.current_streak)}L streak, rating {t.form_rating}")
    
    if args.compare:
        result = analyzer.compare_teams(args.compare[0], args.compare[1], matches)
        print(f"\n📊 PORÓWNANIE: {args.compare[0]} vs {args.compare[1]}")
        if result['advantage']:
            print(f"   Przewaga: {result['advantage']} (+{result['advantage_score']} pkt)")


if __name__ == '__main__':
    main()
