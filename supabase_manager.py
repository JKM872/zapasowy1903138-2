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
from typing import Dict, List, Optional
from datetime import datetime
import os

# Supabase credentials from environment (with fallback)
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://lczcittvuaocimqkhaho.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', os.environ.get('SUPABASE_ANON_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxjemNpdHR2dWFvY2ltcWtoYWhvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjYwOTA3MDksImV4cCI6MjA4MTY2NjcwOX0.6CWKNB6nqqYgDUuSTEeNF61g2NvorXw4s5gf8hqy7Rc'))


class SupabaseManager:
    """Zarządza operacjami na bazie Supabase"""
    
    def __init__(self):
        """Inicjalizuje połączenie z Supabase"""
        self.client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print(f"✅ Connected to Supabase: {SUPABASE_URL}")
    
    
    def save_prediction(self, match_data: Dict) -> bool:
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
            prediction_record = {
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
            response = self.client.table('predictions').insert(prediction_record).execute()
            
            print(f"✅ Saved to Supabase: {match_data.get('home_team')} vs {match_data.get('away_team')}")
            return True
            
        except Exception as e:
            print(f"❌ Error saving to Supabase: {e}")
            return False
    
    
    def save_bulk_predictions(self, matches_data: List[Dict]) -> int:
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
        
        print(f"📊 Saved {success_count}/{len(matches_data)} predictions to Supabase")
        return success_count
    
    
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
            update_data = {
                'actual_result': actual_result,
                'home_score': home_score,
                'away_score': away_score,
                'result_updated_at': datetime.now().isoformat(),
            }
            
            response = self.client.table('predictions').update(update_data).eq('id', match_id).execute()
            
            print(f"✅ Updated result for match ID {match_id}: {actual_result} ({home_score}-{away_score})")
            return True
            
        except Exception as e:
            print(f"❌ Error updating result: {e}")
            return False
    
    
    def get_source_accuracy(self, source: str, days: int = 30) -> Dict:
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
            
            predictions = response.data
            
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
                    probs = {
                        '1': pred.get('sofascore_home_win_prob', 0) or 0,
                        'X': pred.get('sofascore_draw_prob', 0) or 0,
                        '2': pred.get('sofascore_away_win_prob', 0) or 0,
                    }
                    source_pred = max(probs, key=probs.get)
                    
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
            print(f"❌ Error calculating accuracy: {e}")
            return {
                'total_predictions': 0,
                'correct_predictions': 0,
                'accuracy': 0.0,
                'roi': 0.0
            }
    
    
    def get_all_sources_accuracy(self, days: int = 30) -> Dict:
        """
        Pobiera accuracy wszystkich źródeł
        
        Returns:
            Dict z accuracy dla każdego źródła
        """
        sources = ['livesport', 'forebet', 'sofascore', 'gemini']
        
        results = {}
        for source in sources:
            results[source] = self.get_source_accuracy(source, days)
        
        return results


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
    test_match = {
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
    print(f"\n{'✅' if success else '❌'} Test save: {success}")
    
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
