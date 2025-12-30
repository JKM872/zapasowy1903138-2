"""
ROI Tracker - Śledzenie zwrotu z inwestycji dla predykcji sportowych
========================================================================

Automatyczne obliczanie ROI dla różnych strategii zakładów.
Obsługuje: flat betting, Kelly criterion, proporcjonalne stawki.

Użycie:
    python roi_tracker.py --days 30 --stake 100
    python roi_tracker.py --simulate --strategy kelly
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


class BettingStrategy(Enum):
    FLAT = "flat"  # Stała stawka
    KELLY = "kelly"  # Kelly Criterion
    PROPORTIONAL = "proportional"  # Proporcjonalna do pewności


@dataclass
class Bet:
    """Reprezentuje pojedynczy zakład"""
    match_id: str
    home_team: str
    away_team: str
    date: str
    prediction: str  # '1', 'X', '2'
    odds: float
    stake: float
    result: Optional[str] = None  # '1', 'X', '2', None (pending)
    source: str = "consensus"
    confidence: float = 0.5
    
    @property
    def is_settled(self) -> bool:
        return self.result is not None
    
    @property
    def is_win(self) -> bool:
        return self.is_settled and self.prediction == self.result
    
    @property
    def profit(self) -> float:
        if not self.is_settled:
            return 0.0
        if self.is_win:
            return self.stake * (self.odds - 1)
        return -self.stake


@dataclass
class ROIStats:
    """Statystyki ROI"""
    total_bets: int = 0
    settled_bets: int = 0
    wins: int = 0
    losses: int = 0
    pending: int = 0
    total_staked: float = 0.0
    total_profit: float = 0.0
    roi_percent: float = 0.0
    win_rate: float = 0.0
    average_odds: float = 0.0
    best_day: str = ""
    worst_day: str = ""
    streak_current: int = 0
    streak_best: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "total_bets": self.total_bets,
            "settled_bets": self.settled_bets,
            "wins": self.wins,
            "losses": self.losses,
            "pending": self.pending,
            "total_staked": round(self.total_staked, 2),
            "total_profit": round(self.total_profit, 2),
            "roi_percent": round(self.roi_percent, 2),
            "win_rate": round(self.win_rate, 2),
            "average_odds": round(self.average_odds, 2),
            "best_day": self.best_day,
            "worst_day": self.worst_day,
            "streak_current": self.streak_current,
            "streak_best": self.streak_best
        }


class ROITracker:
    """
    Główna klasa do śledzenia ROI.
    Zapisuje historię zakładów i oblicza statystyki.
    """
    
    def __init__(self, data_dir: str = "outputs"):
        self.data_dir = data_dir
        self.bets_file = os.path.join(data_dir, "roi_bets_history.json")
        self.bets: List[Bet] = []
        self._load_bets()
    
    def _load_bets(self):
        """Wczytuje historię zakładów z pliku"""
        if os.path.exists(self.bets_file):
            try:
                with open(self.bets_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.bets = [Bet(**bet) for bet in data.get('bets', [])]
                print(f"📂 Wczytano {len(self.bets)} zakładów z historii")
            except Exception as e:
                print(f"⚠️ Błąd wczytywania historii: {e}")
                self.bets = []
    
    def _save_bets(self):
        """Zapisuje historię zakładów do pliku"""
        os.makedirs(self.data_dir, exist_ok=True)
        data = {
            'bets': [
                {
                    'match_id': b.match_id,
                    'home_team': b.home_team,
                    'away_team': b.away_team,
                    'date': b.date,
                    'prediction': b.prediction,
                    'odds': b.odds,
                    'stake': b.stake,
                    'result': b.result,
                    'source': b.source,
                    'confidence': b.confidence
                }
                for b in self.bets
            ],
            'last_updated': datetime.now().isoformat()
        }
        with open(self.bets_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"💾 Zapisano {len(self.bets)} zakładów")
    
    def add_bet(self, bet: Bet) -> bool:
        """Dodaje nowy zakład"""
        # Sprawdź czy zakład już istnieje
        if any(b.match_id == bet.match_id for b in self.bets):
            print(f"⚠️ Zakład na mecz {bet.match_id} już istnieje")
            return False
        
        self.bets.append(bet)
        self._save_bets()
        print(f"✅ Dodano zakład: {bet.home_team} vs {bet.away_team} ({bet.prediction} @ {bet.odds})")
        return True
    
    def update_result(self, match_id: str, result: str) -> bool:
        """Aktualizuje wynik zakładu"""
        for bet in self.bets:
            if bet.match_id == match_id:
                bet.result = result
                self._save_bets()
                status = "✅ WYGRANA" if bet.is_win else "❌ PRZEGRANA"
                print(f"{status}: {bet.home_team} vs {bet.away_team} - Profit: {bet.profit:.2f}")
                return True
        print(f"⚠️ Nie znaleziono zakładu {match_id}")
        return False
    
    def calculate_stake(
        self, 
        odds: float, 
        confidence: float, 
        base_stake: float = 100,
        strategy: BettingStrategy = BettingStrategy.FLAT
    ) -> float:
        """
        Oblicza optymalną stawkę według wybranej strategii.
        
        Args:
            odds: Kurs bukmacherski
            confidence: Pewność predykcji (0.0 - 1.0)
            base_stake: Bazowa stawka (dla FLAT) lub bankroll (dla KELLY)
            strategy: Strategia zakładów
            
        Returns:
            Obliczona stawka
        """
        if strategy == BettingStrategy.FLAT:
            return base_stake
        
        elif strategy == BettingStrategy.KELLY:
            # Kelly Criterion: f* = (bp - q) / b
            # b = odds - 1, p = probability, q = 1 - p
            b = odds - 1
            p = confidence
            q = 1 - p
            kelly = (b * p - q) / b if b > 0 else 0
            # Ograniczenie do max 10% bankrollu
            kelly = max(0, min(kelly, 0.1))
            return base_stake * kelly
        
        elif strategy == BettingStrategy.PROPORTIONAL:
            # Stawka proporcjonalna do pewności
            # Wyższa pewność = większa stawka
            multiplier = 0.5 + confidence  # 0.5x - 1.5x bazowej stawki
            return base_stake * multiplier
        
        return base_stake
    
    def get_stats(self, days: int = 30) -> ROIStats:
        """
        Oblicza statystyki ROI dla podanego okresu.
        
        Args:
            days: Liczba dni wstecz
            
        Returns:
            ROIStats z obliczonymi statystykami
        """
        stats = ROIStats()
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        filtered_bets = [b for b in self.bets if b.date >= cutoff_date]
        
        if not filtered_bets:
            return stats
        
        stats.total_bets = len(filtered_bets)
        stats.settled_bets = sum(1 for b in filtered_bets if b.is_settled)
        stats.pending = stats.total_bets - stats.settled_bets
        stats.wins = sum(1 for b in filtered_bets if b.is_win)
        stats.losses = stats.settled_bets - stats.wins
        
        settled_bets = [b for b in filtered_bets if b.is_settled]
        
        if settled_bets:
            stats.total_staked = sum(b.stake for b in settled_bets)
            stats.total_profit = sum(b.profit for b in settled_bets)
            stats.roi_percent = (stats.total_profit / stats.total_staked) * 100 if stats.total_staked > 0 else 0
            stats.win_rate = (stats.wins / stats.settled_bets) * 100 if stats.settled_bets > 0 else 0
            stats.average_odds = sum(b.odds for b in settled_bets) / len(settled_bets)
            
            # Oblicz streak
            current_streak = 0
            best_streak = 0
            for bet in sorted(settled_bets, key=lambda x: x.date, reverse=True):
                if bet.is_win:
                    current_streak += 1
                    best_streak = max(best_streak, current_streak)
                else:
                    if current_streak > 0:
                        break
            stats.streak_current = current_streak
            stats.streak_best = best_streak
            
            # Najlepszy/najgorszy dzień
            daily_profits: Dict[str, float] = {}
            for bet in settled_bets:
                daily_profits[bet.date] = daily_profits.get(bet.date, 0) + bet.profit
            
            if daily_profits:
                stats.best_day = max(daily_profits, key=daily_profits.get)
                stats.worst_day = min(daily_profits, key=daily_profits.get)
        
        return stats
    
    def simulate(
        self, 
        predictions: List[Dict], 
        base_stake: float = 100,
        strategy: BettingStrategy = BettingStrategy.FLAT
    ) -> Tuple[ROIStats, List[Bet]]:
        """
        Symulacja zakładów na podstawie listy predykcji.
        
        Args:
            predictions: Lista predykcji z polami: match_id, prediction, odds, result, confidence
            base_stake: Bazowa stawka
            strategy: Strategia zakładów
            
        Returns:
            Tuple z ROIStats i listą symulowanych zakładów
        """
        simulated_bets = []
        
        for pred in predictions:
            if not pred.get('odds') or not pred.get('result'):
                continue
            
            stake = self.calculate_stake(
                odds=pred['odds'],
                confidence=pred.get('confidence', 0.5),
                base_stake=base_stake,
                strategy=strategy
            )
            
            bet = Bet(
                match_id=pred.get('match_id', f"sim_{len(simulated_bets)}"),
                home_team=pred.get('home_team', 'Team A'),
                away_team=pred.get('away_team', 'Team B'),
                date=pred.get('date', datetime.now().strftime('%Y-%m-%d')),
                prediction=pred['prediction'],
                odds=pred['odds'],
                stake=stake,
                result=pred['result'],
                source=pred.get('source', 'simulation'),
                confidence=pred.get('confidence', 0.5)
            )
            simulated_bets.append(bet)
        
        # Oblicz statystyki
        stats = ROIStats()
        stats.total_bets = len(simulated_bets)
        stats.settled_bets = stats.total_bets
        stats.wins = sum(1 for b in simulated_bets if b.is_win)
        stats.losses = stats.total_bets - stats.wins
        stats.total_staked = sum(b.stake for b in simulated_bets)
        stats.total_profit = sum(b.profit for b in simulated_bets)
        
        if stats.total_staked > 0:
            stats.roi_percent = (stats.total_profit / stats.total_staked) * 100
        if stats.settled_bets > 0:
            stats.win_rate = (stats.wins / stats.settled_bets) * 100
            stats.average_odds = sum(b.odds for b in simulated_bets) / len(simulated_bets)
        
        return stats, simulated_bets
    
    def export_report(self, days: int = 30, output_file: str = None) -> str:
        """
        Eksportuje raport ROI do pliku.
        
        Args:
            days: Okres w dniach
            output_file: Ścieżka do pliku (opcjonalna)
            
        Returns:
            Ścieżka do wygenerowanego pliku
        """
        stats = self.get_stats(days)
        
        if output_file is None:
            output_file = os.path.join(
                self.data_dir, 
                f"roi_report_{datetime.now().strftime('%Y-%m-%d')}.json"
            )
        
        report = {
            'generated_at': datetime.now().isoformat(),
            'period_days': days,
            'stats': stats.to_dict(),
            'bets': [
                {
                    'match': f"{b.home_team} vs {b.away_team}",
                    'date': b.date,
                    'prediction': b.prediction,
                    'odds': b.odds,
                    'stake': b.stake,
                    'result': b.result,
                    'profit': b.profit,
                    'status': 'WIN' if b.is_win else 'LOSS' if b.is_settled else 'PENDING'
                }
                for b in self.bets
                if b.date >= (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            ]
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"📊 Raport zapisany: {output_file}")
        return output_file
    
    def print_summary(self, days: int = 30):
        """Wyświetla podsumowanie ROI"""
        stats = self.get_stats(days)
        
        print("\n" + "=" * 50)
        print(f"📊 ROI TRACKER - Ostatnie {days} dni")
        print("=" * 50)
        print(f"📈 Łącznie zakładów: {stats.total_bets}")
        print(f"✅ Wygrane: {stats.wins} ({stats.win_rate:.1f}%)")
        print(f"❌ Przegrane: {stats.losses}")
        print(f"⏳ Oczekujące: {stats.pending}")
        print("-" * 50)
        print(f"💰 Postawiono: {stats.total_staked:.2f} PLN")
        profit_emoji = "🟢" if stats.total_profit >= 0 else "🔴"
        print(f"{profit_emoji} Profit: {stats.total_profit:+.2f} PLN")
        print(f"📊 ROI: {stats.roi_percent:+.2f}%")
        print("-" * 50)
        print(f"📉 Średnie kursy: {stats.average_odds:.2f}")
        print(f"🔥 Aktualny streak: {stats.streak_current}")
        print(f"🏆 Najlepszy streak: {stats.streak_best}")
        print("=" * 50 + "\n")


def main():
    """Główna funkcja CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='ROI Tracker dla predykcji sportowych')
    parser.add_argument('--days', type=int, default=30, help='Okres w dniach')
    parser.add_argument('--stake', type=float, default=100, help='Bazowa stawka')
    parser.add_argument('--simulate', action='store_true', help='Tryb symulacji')
    parser.add_argument('--strategy', choices=['flat', 'kelly', 'proportional'], 
                       default='flat', help='Strategia zakładów')
    parser.add_argument('--export', action='store_true', help='Eksportuj raport')
    
    args = parser.parse_args()
    
    tracker = ROITracker()
    
    if args.simulate:
        # Demo symulacja z przykładowymi danymi
        demo_predictions = [
            {'prediction': '1', 'odds': 1.85, 'result': '1', 'confidence': 0.65},
            {'prediction': '1', 'odds': 2.10, 'result': '1', 'confidence': 0.55},
            {'prediction': '2', 'odds': 1.75, 'result': '2', 'confidence': 0.70},
            {'prediction': '1', 'odds': 1.95, 'result': 'X', 'confidence': 0.50},
            {'prediction': '2', 'odds': 2.30, 'result': '1', 'confidence': 0.45},
        ]
        
        strategy = BettingStrategy(args.strategy)
        stats, bets = tracker.simulate(demo_predictions, args.stake, strategy)
        
        print(f"\n📊 Symulacja ({strategy.value}):")
        print(f"   Zakłady: {stats.total_bets}, Wygrane: {stats.wins}")
        print(f"   ROI: {stats.roi_percent:+.2f}%")
        print(f"   Profit: {stats.total_profit:+.2f} PLN")
    else:
        tracker.print_summary(args.days)
        
        if args.export:
            tracker.export_report(args.days)


if __name__ == '__main__':
    main()
