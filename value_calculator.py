"""
Value Calculator - Obliczanie Expected Value i Value Bets
==========================================================

Identyfikuje zakłady z dodatnim expected value (EV).
Porównuje prawdopodobieństwa z kursami bukmacherskimi.

Użycie:
    python value_calculator.py --analyze --date 2025-12-16
    python value_calculator.py --top 5
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class ValueBet:
    """Reprezentuje value bet"""
    match_id: str
    home_team: str
    away_team: str
    prediction: str  # 1, X, 2
    probability: float  # nasza szacowana prawdopodobnienstwo
    odds: float  # kurs bukmacherski
    implied_prob: float  # prawdopodobienstwo wg kursu
    expected_value: float  # EV
    edge: float  # nasza przewaga w %
    confidence: float  # pewnosc predykcji
    sport: str
    league: str
    
    @property
    def is_value(self) -> bool:
        return self.expected_value > 0
    
    @property
    def kelly_fraction(self) -> float:
        """Oblicza optymalny stake wg Kelly Criterion"""
        if self.odds <= 1:
            return 0
        q = 1 - self.probability
        return max(0, (self.probability * self.odds - 1) / (self.odds - 1))
    
    def to_dict(self) -> Dict:
        return {
            "match_id": self.match_id,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "prediction": self.prediction,
            "probability": round(self.probability * 100, 1),
            "odds": self.odds,
            "implied_prob": round(self.implied_prob * 100, 1),
            "expected_value": round(self.expected_value, 3),
            "edge": round(self.edge, 2),
            "kelly": round(self.kelly_fraction * 100, 1),
            "is_value": self.is_value,
            "sport": self.sport,
            "league": self.league
        }


class ValueCalculator:
    """
    Kalkulator value bets.
    Identyfikuje zakłady z dodatnim EV.
    """
    
    # Minimalna przewaga do uznania za value bet
    MIN_EDGE = 0.02  # 2%
    
    # Wagi źródeł do obliczania prawdopodobieństwa
    SOURCE_WEIGHTS = {
        'forebet': 0.25,
        'sofascore': 0.20,
        'h2h': 0.25,
        'gemini': 0.20,
        'consensus': 0.10
    }
    
    def __init__(self, min_edge: float = 0.02):
        self.min_edge = min_edge
    
    def calculate_probability(self, match: Dict) -> Tuple[float, float, float]:
        """
        Oblicza prawdopodobieństwa dla każdego wyniku.
        
        Returns:
            Tuple (prob_home, prob_draw, prob_away)
        """
        probs = {'1': [], 'X': [], '2': []}
        weights = []
        
        # Forebet
        forebet = match.get('forebet', {})
        if forebet.get('prediction'):
            prob = forebet.get('probability', 50) / 100
            pred = forebet['prediction']
            if pred == '1':
                probs['1'].append(prob)
                probs['X'].append((1 - prob) * 0.4)
                probs['2'].append((1 - prob) * 0.6)
            elif pred == '2':
                probs['2'].append(prob)
                probs['X'].append((1 - prob) * 0.4)
                probs['1'].append((1 - prob) * 0.6)
            else:
                probs['X'].append(prob)
                probs['1'].append((1 - prob) * 0.5)
                probs['2'].append((1 - prob) * 0.5)
        
        # SofaScore community vote
        sofascore = match.get('sofascore', {})
        ss_home = sofascore.get('home', 0) / 100 if sofascore.get('home') else None
        ss_draw = sofascore.get('draw', 0) / 100 if sofascore.get('draw') else None
        ss_away = sofascore.get('away', 0) / 100 if sofascore.get('away') else None
        
        if ss_home is not None:
            probs['1'].append(ss_home)
            probs['X'].append(ss_draw or 0.25)
            probs['2'].append(ss_away or 0.35)
        
        # H2H win rate
        h2h = match.get('h2h', {})
        win_rate = h2h.get('winRate', 50) / 100
        if win_rate > 0:
            focus = match.get('focusTeam', 'home')
            if focus == 'home':
                probs['1'].append(win_rate)
                probs['2'].append(1 - win_rate - 0.1)
            else:
                probs['2'].append(win_rate)
                probs['1'].append(1 - win_rate - 0.1)
            probs['X'].append(0.25)
        
        # Oblicz średnie ważone
        def avg_prob(prob_list):
            if not prob_list:
                return 0.33
            return sum(prob_list) / len(prob_list)
        
        p1 = avg_prob(probs['1'])
        pX = avg_prob(probs['X'])
        p2 = avg_prob(probs['2'])
        
        # Normalizuj do 100%
        total = p1 + pX + p2
        if total > 0:
            p1, pX, p2 = p1/total, pX/total, p2/total
        
        return p1, pX, p2
    
    def odds_to_probability(self, odds: float) -> float:
        """Konwertuje kurs na implied probability"""
        if odds <= 0:
            return 0
        return 1 / odds
    
    def calculate_ev(self, probability: float, odds: float) -> float:
        """
        Oblicza Expected Value.
        
        EV = (prob * odds) - 1
        EV > 0 oznacza value bet
        """
        if odds <= 0:
            return -1
        return (probability * odds) - 1
    
    def analyze_match(self, match: Dict) -> List[ValueBet]:
        """
        Analizuje mecz pod kątem value bets.
        
        Returns:
            Lista ValueBet dla wszystkich wyników z dodatnim EV
        """
        value_bets = []
        
        # Oblicz prawdopodobieństwa
        p1, pX, p2 = self.calculate_probability(match)
        
        # Pobierz kursy
        odds = match.get('odds', {})
        odds_1 = odds.get('home', 0)
        odds_X = odds.get('draw', 0)
        odds_2 = odds.get('away', 0)
        
        outcomes = [
            ('1', p1, odds_1),
            ('X', pX, odds_X),
            ('2', p2, odds_2)
        ]
        
        for prediction, probability, odds_value in outcomes:
            if odds_value <= 0 or odds_value > 100:
                continue
            
            implied_prob = self.odds_to_probability(odds_value)
            ev = self.calculate_ev(probability, odds_value)
            edge = probability - implied_prob
            
            if edge >= self.min_edge:
                value_bet = ValueBet(
                    match_id=str(match.get('id', '')),
                    home_team=match.get('homeTeam', match.get('home_team', '')),
                    away_team=match.get('awayTeam', match.get('away_team', '')),
                    prediction=prediction,
                    probability=probability,
                    odds=odds_value,
                    implied_prob=implied_prob,
                    expected_value=ev,
                    edge=edge * 100,
                    confidence=match.get('confidence', 50),
                    sport=match.get('sport', 'football'),
                    league=match.get('league', '')
                )
                value_bets.append(value_bet)
        
        return value_bets
    
    def analyze_matches(self, matches: List[Dict]) -> List[ValueBet]:
        """Analizuje wiele meczów"""
        all_value_bets = []
        
        for match in matches:
            value_bets = self.analyze_match(match)
            all_value_bets.extend(value_bets)
        
        # Sortuj po EV malejąco
        all_value_bets.sort(key=lambda x: x.expected_value, reverse=True)
        
        return all_value_bets
    
    def load_matches(self, date: str = None) -> List[Dict]:
        """Wczytuje mecze z plików"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        matches = []
        outputs_dir = os.path.join(os.path.dirname(__file__), 'outputs')
        
        for sport in ['football', 'basketball', 'volleyball', 'handball', 'hockey']:
            filepath = os.path.join(outputs_dir, f'matches_{date}_{sport}.json')
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for m in data.get('matches', []):
                            m['sport'] = sport
                            matches.append(m)
                except Exception:
                    pass
        
        return matches
    
    def print_value_bets(self, value_bets: List[ValueBet], limit: int = 10):
        """Wyświetla value bets"""
        print("\n" + "="*70)
        print("VALUE BETS")
        print("="*70)
        
        if not value_bets:
            print("Nie znaleziono value bets")
            return
        
        for i, vb in enumerate(value_bets[:limit], 1):
            print(f"\n{i}. {vb.home_team} vs {vb.away_team}")
            print(f"   Predykcja: {vb.prediction} @ {vb.odds}")
            print(f"   Probability: {vb.probability*100:.1f}% vs Implied: {vb.implied_prob*100:.1f}%")
            print(f"   EV: {vb.expected_value:+.3f} | Edge: {vb.edge:+.1f}%")
            print(f"   Kelly: {vb.kelly_fraction*100:.1f}% | Sport: {vb.sport}")
        
        print("\n" + "="*70)
        print(f"Znaleziono {len(value_bets)} value bets")


def main():
    """Główna funkcja CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Value Calculator dla BigOne')
    parser.add_argument('--analyze', action='store_true', help='Analizuj mecze')
    parser.add_argument('--date', type=str, help='Data (YYYY-MM-DD)')
    parser.add_argument('--top', type=int, default=10, help='Ilosc top value bets')
    parser.add_argument('--min-edge', type=float, default=2.0, help='Minimalny edge w %')
    parser.add_argument('--json', action='store_true', help='Output JSON')
    
    args = parser.parse_args()
    
    calculator = ValueCalculator(min_edge=args.min_edge / 100)
    
    matches = calculator.load_matches(args.date)
    print(f"Wczytano {len(matches)} meczow")
    
    if not matches:
        # Demo data
        matches = [
            {
                'id': '1',
                'homeTeam': 'Manchester United',
                'awayTeam': 'Liverpool',
                'odds': {'home': 2.10, 'draw': 3.50, 'away': 3.20},
                'forebet': {'prediction': '1', 'probability': 55},
                'h2h': {'winRate': 60},
                'sofascore': {'home': 52, 'draw': 24, 'away': 24},
                'sport': 'football',
                'league': 'Premier League'
            }
        ]
        print("Uzywam demo danych")
    
    value_bets = calculator.analyze_matches(matches)
    
    if args.json:
        print(json.dumps([vb.to_dict() for vb in value_bets[:args.top]], indent=2))
    else:
        calculator.print_value_bets(value_bets, args.top)


if __name__ == '__main__':
    main()
