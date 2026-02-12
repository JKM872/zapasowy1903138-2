"""
Supabase Database Manager
--------------------------
Zarządza połączeniem z Supabase i zapisuje:
- Predykcje z wszystkich źródeł (LiveSport, Forebet, SofaScore, Gemini)
- Rzeczywiste wyniki meczów
- Accuracy tracking dla każdego źródła
- ROI calculations

Database: Configured via environment variables
"""

from supabase import create_client, Client
from typing import Any, Dict, List, Optional, cast
from datetime import datetime
import os

# Supabase credentials from environment (with fallback)
# NOTE: Use `or` instead of default param — GitHub Actions sets env vars to empty
# string '' when secrets are missing, which bypasses os.environ.get() defaults.
SUPABASE_URL = os.environ.get('SUPABASE_URL') or 'https://suqysbmuisffeqwgvymp.supabase.co'
SUPABASE_KEY = os.environ.get('SUPABASE_KEY') or os.environ.get('SUPABASE_ANON_KEY') or 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InN1cXlzYm11aXNmZmVxd2d2eW1wIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzA4MzU2NTUsImV4cCI6MjA4NjQxMTY1NX0.FiPzJOe1rXyjja03Jk1wKgoZg1hE2bbJDtGQPoteLIg'


class SupabaseManager:
    """Zarządza operacjami na bazie Supabase"""
    
    def __init__(self):
        """Inicjalizuje połączenie z Supabase"""
        self.client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print(f"[OK] Connected to Supabase: {SUPABASE_URL}")
    
    
    def save_prediction(self, match_data: Dict[str, Any]) -> bool:
        """
        Zapisuje predykcję meczu do tabeli 'predictions'
        
        Args:
            match_data: Dict z danymi meczu zawierający:
                - match_date: str (YYYY-MM-DD)
                - match_time: str (HH:MM)
                - home_team: str
                - away_team: str
                - sport: str
                - league: str (optional)
                
                # LiveSport data
                - livesport_h2h_home_wins: int
                - livesport_h2h_away_wins: int
                - livesport_win_rate: float (%)
                - livesport_home_form: str
                - livesport_away_form: str
                
                # Forebet data
                - forebet_prediction: str (1/X/2 lub 1/2)
                - forebet_probability: float (%)
                - forebet_home_odds: float
                - forebet_draw_odds: float (lub None)
                - forebet_away_odds: float
                
                # SofaScore data
                - sofascore_home_win_prob: float (%)
                - sofascore_draw_prob: float (% lub None)
                - sofascore_away_win_prob: float (%)
                - sofascore_total_votes: int
                
                # Gemini AI data
                - gemini_prediction: str
                - gemini_confidence: float (%)
                - gemini_recommendation: str (HIGH/MEDIUM/LOW/SKIP)
                - gemini_reasoning: str
                
                # Metadata
                - qualifies: bool
                - match_url: str
                - created_at: str (timestamp)
        
        Returns:
            True jeśli sukces, False jeśli błąd
        """
        try:
            # Prepare data for insert
            prediction_record: Dict[str, Any] = {
                'match_date': match_data.get('match_date'),
                'match_time': match_data.get('match_time'),
                'home_team': match_data.get('home_team'),
                'away_team': match_data.get('away_team'),
                'sport': match_data.get('sport', 'football'),
                'league': match_data.get('league'),
                
                # LiveSport
                'livesport_h2h_home_wins': match_data.get('home_wins_in_h2h_last5'),
                'livesport_h2h_away_wins': match_data.get('away_wins_in_h2h_last5'),
                'livesport_win_rate': match_data.get('win_rate'),
                'livesport_home_form': match_data.get('home_form'),
                'livesport_away_form': match_data.get('away_form'),
                
                # Forebet
                'forebet_prediction': match_data.get('forebet_prediction'),
                'forebet_probability': match_data.get('forebet_probability'),
                'forebet_home_odds': match_data.get('home_odds'),
                'forebet_draw_odds': match_data.get('draw_odds'),
                'forebet_away_odds': match_data.get('away_odds'),
                
                # SofaScore
                'sofascore_home_win_prob': match_data.get('sofascore_home_win_prob'),
                'sofascore_draw_prob': match_data.get('sofascore_draw_prob'),
                'sofascore_away_win_prob': match_data.get('sofascore_away_win_prob'),
                'sofascore_total_votes': match_data.get('sofascore_total_votes', 0),
                
                # Gemini
                'gemini_prediction': match_data.get('gemini_prediction'),
                'gemini_confidence': match_data.get('gemini_confidence'),
                'gemini_recommendation': match_data.get('gemini_recommendation'),
                'gemini_reasoning': match_data.get('gemini_reasoning'),
                
                # Metadata
                'qualifies': match_data.get('qualifies', False),
                'match_url': match_data.get('match_url'),
                'created_at': datetime.now().isoformat(),
            }
            
            # Insert do Supabase
            self.client.table('predictions').insert(prediction_record).execute()
            
            print(f"[OK] Saved to Supabase: {match_data.get('home_team')} vs {match_data.get('away_team')}")
            return True
            
        except Exception as e:
            print(f"[ERROR] Error saving to Supabase: {e}")
            import traceback
            traceback.print_exc()  # Print full stack trace for debugging
            return False
    
    
    def save_bulk_predictions(self, matches_data: List[Dict[str, Any]]) -> int:
        """
        Zapisuje wiele predykcji naraz (batch insert)
        
        Args:
            matches_data: Lista dictów z danymi meczów
        
        Returns:
            Liczba zapisanych rekordów
        """
        success_count = 0
        
        for match in matches_data:
            if self.save_prediction(match):
                success_count += 1
        
        print(f"[STATS] Saved {success_count}/{len(matches_data)} predictions to Supabase")
        return success_count
    
    
    def get_predictions(self, date: Optional[str] = None, sport: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
        """
        Pobiera predykcje z tabeli 'predictions'.
        
        Args:
            date: Data meczu (YYYY-MM-DD). Jeśli None, zwraca najnowsze.
            sport: Filtr sportu (football, basketball, ...). None = wszystkie.
            limit: Maks. rekordów.
        
        Returns:
            Lista dictów z danymi meczów.
        """
        try:
            query = self.client.table('predictions').select('*')
            
            if date:
                query = query.eq('match_date', date)
            if sport and sport != 'all':
                query = query.eq('sport', sport)
            
            query = query.order('match_date', desc=True).order('match_time', desc=False).limit(limit)
            response = query.execute()
            
            return cast(List[Dict[str, Any]], response.data) if response.data else []
        except Exception as e:
            print(f"[ERROR] Error fetching predictions: {e}")
            return []
    
    
    def get_available_dates(self) -> List[str]:
        """Zwraca listę dat dla których istnieją predykcje (desc)."""
        try:
            response = self.client.table('predictions').select('match_date').execute()
            rows = cast(List[Dict[str, Any]], response.data)
            dates: List[str] = sorted(set(r['match_date'] for r in rows if r.get('match_date')), reverse=True)
            return dates
        except Exception as e:
            print(f"[ERROR] Error fetching dates: {e}")
            return []
    
    
    def get_sport_counts(self, date: Optional[str] = None) -> Dict[str, int]:
        """Zwraca liczbę meczów per sport dla danej daty."""
        try:
            query = self.client.table('predictions').select('sport')
            if date:
                query = query.eq('match_date', date)
            response = query.execute()
            counts: Dict[str, int] = {}
            rows = cast(List[Dict[str, Any]], response.data)
            for r in rows:
                s = str(r.get('sport', 'football'))
                counts[s] = counts.get(s, 0) + 1
            return counts
        except Exception as e:
            print(f"[ERROR] Error fetching sport counts: {e}")
            return {}
    
    
    def update_match_result(
        self,
        match_id: int,
        actual_result: str,
        home_score: int,
        away_score: int
    ) -> bool:
        """
        Aktualizuje wynik meczu po jego zakończeniu
        
        Args:
            match_id: ID predykcji w bazie
            actual_result: '1' (home win), 'X' (draw), '2' (away win)
            home_score: Bramki gospodarzy
            away_score: Bramki gości
        
        Returns:
            True jeśli sukces
        """
        try:
            update_data: Dict[str, Any] = {
                'actual_result': actual_result,
                'home_score': home_score,
                'away_score': away_score,
                'result_updated_at': datetime.now().isoformat(),
            }
            
            self.client.table('predictions').update(update_data).eq('id', match_id).execute()
            
            print(f"[OK] Updated result for match ID {match_id}: {actual_result} ({home_score}-{away_score})")
            return True
            
        except Exception as e:
            print(f"[ERROR] Error updating result: {e}")
            return False
    
    
    def get_source_accuracy(self, source: str, days: int = 30) -> Dict[str, Any]:
        """
        Oblicza accuracy danego źródła za ostatnie N dni
        
        Args:
            source: 'livesport', 'forebet', 'sofascore', 'gemini'
            days: Ile dni wstecz sprawdzać
        
        Returns:
            Dict z metrykami:
            - total_predictions: int
            - correct_predictions: int
            - accuracy: float (%)
            - roi: float (%)
        """
        try:
            # Pobierz predykcje z ostatnich N dni z wynikami
            from datetime import timedelta
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            response = self.client.table('predictions')\
                .select('*')\
                .gte('match_date', cutoff_date)\
                .not_.is_('actual_result', 'null')\
                .execute()
            
            predictions = cast(List[Dict[str, Any]], response.data)
            
            if not predictions:
                return {
                    'total_predictions': 0,
                    'correct_predictions': 0,
                    'accuracy': 0.0,
                    'roi': 0.0
                }
            
            total = len(predictions)
            correct = 0
            total_stake = 0
            total_return = 0
            
            for pred in predictions:
                actual = pred['actual_result']
                
                # Determine source prediction
                source_pred = None
                source_odds = 1.0
                
                if source == 'livesport':
                    # LiveSport predicts based on H2H win rate
                    if pred['livesport_win_rate'] >= 60:
                        source_pred = '1'  # Home win
                        source_odds = pred.get('forebet_home_odds', 1.0) or 1.0
                
                elif source == 'forebet':
                    source_pred = pred['forebet_prediction']
                    if source_pred == '1':
                        source_odds = pred.get('forebet_home_odds', 1.0) or 1.0
                    elif source_pred == 'X':
                        source_odds = pred.get('forebet_draw_odds', 1.0) or 1.0
                    elif source_pred == '2':
                        source_odds = pred.get('forebet_away_odds', 1.0) or 1.0
                
                elif source == 'sofascore':
                    # SofaScore predicts based on highest probability
                    probs: Dict[str, Any] = {
                        '1': pred.get('sofascore_home_win_prob', 0) or 0,
                        'X': pred.get('sofascore_draw_prob', 0) or 0,
                        '2': pred.get('sofascore_away_win_prob', 0) or 0,
                    }
                    source_pred = max(probs, key=lambda k: float(probs[k]))
                    
                    if source_pred == '1':
                        source_odds = pred.get('forebet_home_odds', 1.0) or 1.0
                    elif source_pred == '2':
                        source_odds = pred.get('forebet_away_odds', 1.0) or 1.0
                
                elif source == 'gemini':
                    # Gemini recommends HIGH only
                    if pred.get('gemini_recommendation') == 'HIGH':
                        # Determine if home or away based on prediction text
                        gemini_text = (pred.get('gemini_prediction') or '').lower()
                        if 'home' in gemini_text or pred.get('home_team', '').lower() in gemini_text:
                            source_pred = '1'
                            source_odds = pred.get('forebet_home_odds', 1.0) or 1.0
                        else:
                            source_pred = '2'
                            source_odds = pred.get('forebet_away_odds', 1.0) or 1.0
                
                # Check if correct
                if source_pred and source_pred == actual:
                    correct += 1
                    total_return += source_odds
                
                if source_pred:
                    total_stake += 1
            
            accuracy = (correct / total * 100) if total > 0 else 0
            roi = ((total_return - total_stake) / total_stake * 100) if total_stake > 0 else 0
            
            return {
                'total_predictions': total,
                'correct_predictions': correct,
                'accuracy': round(accuracy, 2),
                'roi': round(roi, 2)
            }
            
        except Exception as e:
            print(f"[ERROR] Error calculating accuracy: {e}")
            return {
                'total_predictions': 0,
                'correct_predictions': 0,
                'accuracy': 0.0,
                'roi': 0.0
            }
    
    
    def get_all_sources_accuracy(self, days: int = 30) -> Dict[str, Any]:
        """
        Pobiera accuracy wszystkich źródeł
        
        Returns:
            Dict z accuracy dla każdego źródła
        """
        sources = ['livesport', 'forebet', 'sofascore', 'gemini']
        
        results: Dict[str, Any] = {}
        for source in sources:
            results[source] = self.get_source_accuracy(source, days)
        
        return results
    
    
    # ========================================================================
    # USER BETS METHODS
    # ========================================================================
    
    def save_user_bet(self, bet_data: Dict[str, Any]) -> Optional[int]:
        """
        Zapisuje zakład użytkownika do tabeli 'user_bets'
        
        Args:
            bet_data: Dict zawierający:
                - prediction_id: int (opcjonalne - referencja do predykcji)
                - match_date: str (YYYY-MM-DD)
                - match_time: str (HH:MM)
                - home_team: str
                - away_team: str
                - sport: str
                - league: str (opcjonalne)
                - bet_selection: str ('1', 'X', '2')
                - odds_at_bet: float
                - stake: float (domyślnie 10.00)
                - notes: str (opcjonalne)
        
        Returns:
            ID nowego zakładu lub None jeśli błąd
        """
        try:
            bet_record: Dict[str, Any] = {
                'prediction_id': bet_data.get('prediction_id'),
                'match_date': bet_data.get('match_date'),
                'match_time': bet_data.get('match_time'),
                'home_team': bet_data.get('home_team'),
                'away_team': bet_data.get('away_team'),
                'sport': bet_data.get('sport', 'football'),
                'league': bet_data.get('league'),
                'bet_selection': bet_data.get('bet_selection'),
                'odds_at_bet': bet_data.get('odds_at_bet'),
                'stake': bet_data.get('stake', 10.00),
                'status': 'pending',
                'notes': bet_data.get('notes'),
                'created_at': datetime.now().isoformat(),
            }
            
            response = self.client.table('user_bets').insert(bet_record).execute()
            
            if response.data:
                row = cast(Dict[str, Any], response.data[0])
                bet_id = int(row['id'])
                print(f"[OK] Saved bet: {bet_data.get('home_team')} vs {bet_data.get('away_team')} - {bet_data.get('bet_selection')} @ {bet_data.get('odds_at_bet')}")
                return bet_id
            return None
            
        except Exception as e:
            print(f"[ERROR] Error saving bet: {e}")
            return None
    
    
    def get_user_bets(
        self,
        status: Optional[str] = None,
        days: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Pobiera zakłady użytkownika
        
        Args:
            status: Filtruj po statusie ('pending', 'won', 'lost', 'void')
            days: Ile dni wstecz (None = wszystkie)
            limit: Maksymalna liczba rekordów
        
        Returns:
            Lista zakładów
        """
        try:
            query = self.client.table('user_bets').select('*')
            
            if status:
                query = query.eq('status', status)
            
            if days:
                from datetime import timedelta
                cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                query = query.gte('match_date', cutoff_date)
            
            query = query.order('created_at', desc=True).limit(limit)
            
            response = query.execute()
            return cast(List[Dict[str, Any]], response.data or [])
            
        except Exception as e:
            print(f"[ERROR] Error fetching bets: {e}")
            return []
    
    
    def update_bet_result(
        self,
        bet_id: int,
        actual_result: str,
        home_score: int,
        away_score: int
    ) -> bool:
        """
        Aktualizuje wynik zakładu po zakończeniu meczu
        
        Args:
            bet_id: ID zakładu
            actual_result: '1' (home win), 'X' (draw), '2' (away win)
            home_score: Bramki gospodarzy
            away_score: Bramki gości
        
        Returns:
            True jeśli sukces
        """
        try:
            # Pobierz zakład aby obliczyć profit
            response = self.client.table('user_bets').select('*').eq('id', bet_id).execute()
            
            if not response.data:
                print(f"[ERROR] Bet ID {bet_id} not found")
                return False
            
            bet = cast(Dict[str, Any], response.data[0])
            bet_selection = bet['bet_selection']
            odds = float(bet['odds_at_bet'])
            stake = float(bet['stake'])
            
            # Oblicz wynik
            if bet_selection == actual_result:
                status = 'won'
                profit = stake * (odds - 1)  # Zysk = stawka * (kurs - 1)
            else:
                status = 'lost'
                profit = -stake  # Strata = -stawka
            
            update_data: Dict[str, Any] = {
                'status': status,
                'actual_result': actual_result,
                'home_score': home_score,
                'away_score': away_score,
                'profit': round(profit, 2),
                'settled_at': datetime.now().isoformat(),
            }
            
            self.client.table('user_bets').update(update_data).eq('id', bet_id).execute()
            
            print(f"[OK] Updated bet ID {bet_id}: {status} (profit: {profit:+.2f})")
            return True
            
        except Exception as e:
            print(f"[ERROR] Error updating bet result: {e}")
            return False
    
    
    def get_user_betting_stats(self) -> Dict[str, Any]:
        """
        Pobiera statystyki zakładów użytkownika
        
        Returns:
            Dict z metrykami:
            - total_bets: int
            - pending_bets: int
            - won_bets: int
            - lost_bets: int
            - total_staked: float
            - total_profit: float
            - win_rate: float (%)
            - roi: float (%)
        """
        try:
            response = self.client.table('user_bets').select('*').execute()
            bets = cast(List[Dict[str, Any]], response.data or [])
            
            if not bets:
                return {
                    'total_bets': 0,
                    'pending_bets': 0,
                    'won_bets': 0,
                    'lost_bets': 0,
                    'total_staked': 0.0,
                    'total_profit': 0.0,
                    'win_rate': 0.0,
                    'roi': 0.0
                }
            
            total = len(bets)
            pending = sum(1 for b in bets if b['status'] == 'pending')
            won = sum(1 for b in bets if b['status'] == 'won')
            lost = sum(1 for b in bets if b['status'] == 'lost')
            
            settled_bets = [b for b in bets if b['status'] in ('won', 'lost')]
            total_staked = sum(float(b['stake'] or 0) for b in settled_bets)
            total_profit = sum(float(b['profit'] or 0) for b in settled_bets)
            
            win_rate = (won / len(settled_bets) * 100) if settled_bets else 0
            roi = (total_profit / total_staked * 100) if total_staked > 0 else 0
            
            return {
                'total_bets': total,
                'pending_bets': pending,
                'won_bets': won,
                'lost_bets': lost,
                'total_staked': round(total_staked, 2),
                'total_profit': round(total_profit, 2),
                'win_rate': round(win_rate, 2),
                'roi': round(roi, 2)
            }
            
        except Exception as e:
            print(f"[ERROR] Error fetching betting stats: {e}")
            return {
                'total_bets': 0,
                'pending_bets': 0,
                'won_bets': 0,
                'lost_bets': 0,
                'total_staked': 0.0,
                'total_profit': 0.0,
                'win_rate': 0.0,
                'roi': 0.0
            }
    
    
    def delete_bet(self, bet_id: int) -> bool:
        """
        Usuwa zakład użytkownika
        
        Args:
            bet_id: ID zakładu
        
        Returns:
            True jeśli sukces
        """
        try:
            self.client.table('user_bets').delete().eq('id', bet_id).execute()
            print(f"[OK] Deleted bet ID {bet_id}")
            return True
        except Exception as e:
            print(f"[ERROR] Error deleting bet: {e}")
            return False


# ============================================================================
# DATABASE SCHEMA (SQL)
# ============================================================================

# Uruchom to w Supabase SQL Editor aby stworzyć tabelę:
"""
CREATE TABLE predictions (
    id BIGSERIAL PRIMARY KEY,
    
    -- Match info
    match_date DATE NOT NULL,
    match_time TIME,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    sport TEXT NOT NULL DEFAULT 'football',
    league TEXT,
    
    -- LiveSport data
    livesport_h2h_home_wins INT,
    livesport_h2h_away_wins INT,
    livesport_win_rate DECIMAL(5,2),
    livesport_home_form TEXT,
    livesport_away_form TEXT,
    
    -- Forebet data
    forebet_prediction TEXT,
    forebet_probability DECIMAL(5,2),
    forebet_home_odds DECIMAL(6,2),
    forebet_draw_odds DECIMAL(6,2),
    forebet_away_odds DECIMAL(6,2),
    
    -- SofaScore data
    sofascore_home_win_prob DECIMAL(5,2),
    sofascore_draw_prob DECIMAL(5,2),
    sofascore_away_win_prob DECIMAL(5,2),
    sofascore_total_votes INT,
    
    -- Gemini AI data
    gemini_prediction TEXT,
    gemini_confidence DECIMAL(5,2),
    gemini_recommendation TEXT,
    gemini_reasoning TEXT,
    
    -- Actual result (filled after match ends)
    actual_result TEXT,  -- '1', 'X', '2'
    home_score INT,
    away_score INT,
    result_updated_at TIMESTAMPTZ,
    
    -- Metadata
    qualifies BOOLEAN DEFAULT FALSE,
    match_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_match_date (match_date),
    INDEX idx_sport (sport),
    INDEX idx_actual_result (actual_result)
);

-- Enable Row Level Security (RLS)
ALTER TABLE predictions ENABLE ROW LEVEL SECURITY;

-- Policy: Allow public read
CREATE POLICY "Allow public read" ON predictions
    FOR SELECT USING (true);

-- Policy: Allow authenticated insert/update
CREATE POLICY "Allow authenticated insert" ON predictions
    FOR INSERT WITH CHECK (true);

CREATE POLICY "Allow authenticated update" ON predictions
    FOR UPDATE USING (true);
"""


# ============================================================================
# CLI TESTING
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("TESTING SUPABASE CONNECTION")
    print("="*60 + "\n")
    
    manager = SupabaseManager()
    
    # Test save prediction
    test_match: Dict[str, Any] = {
        'match_date': '2025-11-18',
        'match_time': '20:00',
        'home_team': 'Test Home',
        'away_team': 'Test Away',
        'sport': 'football',
        'home_wins_in_h2h_last5': 3,
        'away_wins_in_h2h_last5': 1,
        'win_rate': 60.0,
        'forebet_prediction': '1',
        'forebet_probability': 65.0,
        'home_odds': 1.85,
        'away_odds': 2.10,
        'sofascore_home_win_prob': 62.0,
        'sofascore_away_win_prob': 38.0,
        'gemini_confidence': 85.0,
        'gemini_recommendation': 'HIGH',
        'qualifies': True,
        'match_url': 'https://test.com/match',
    }
    
    success = manager.save_prediction(test_match)
    print(f"\n{'[OK]' if success else '[FAIL]'} Test save: {success}")
    
    # Test accuracy (może być puste jeśli brak danych)
    print("\n" + "="*60)
    print("SOURCE ACCURACY (Last 30 days)")
    print("="*60 + "\n")
    
    accuracy = manager.get_all_sources_accuracy(days=30)
    for source, stats in accuracy.items():
        print(f"{source.upper()}:")
        print(f"  Total: {stats['total_predictions']}")
        print(f"  Correct: {stats['correct_predictions']}")
        print(f"  Accuracy: {stats['accuracy']}%")
        print(f"  ROI: {stats['roi']}%")
        print()
