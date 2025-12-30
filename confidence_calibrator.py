"""
Confidence Calibrator - Kalibracja pewności predykcji
======================================================

Analizuje historyczną trafność i kalibruje wagi źródeł danych.
Oblicza confidence score 0-100 na podstawie wielu czynników.

Użycie:
    python confidence_calibrator.py --analyze --days 30
    python confidence_calibrator.py --calibrate
"""

import os
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import math

# Local imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from supabase_manager import SupabaseManager
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


@dataclass
class SourceAccuracy:
    """Trafność pojedynczego źródła"""
    name: str
    total_predictions: int = 0
    correct_predictions: int = 0
    accuracy: float = 0.0
    weight: float = 1.0
    
    def calculate_accuracy(self):
        if self.total_predictions > 0:
            self.accuracy = self.correct_predictions / self.total_predictions
        return self.accuracy


@dataclass
class CalibrationResult:
    """Wynik kalibracji"""
    source_weights: Dict[str, float] = field(default_factory=dict)
    baseline_accuracy: float = 0.0
    calibrated_at: str = ""
    predictions_analyzed: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "source_weights": self.source_weights,
            "baseline_accuracy": round(self.baseline_accuracy, 4),
            "calibrated_at": self.calibrated_at,
            "predictions_analyzed": self.predictions_analyzed
        }


class ConfidenceCalibrator:
    """
    Główna klasa do kalibracji pewności.
    Analizuje historyczne wyniki i dostosowuje wagi źródeł.
    """
    
    # Domyślne wagi źródeł
    DEFAULT_WEIGHTS = {
        'livesport': 1.0,      # H2H i forma
        'forebet': 1.2,        # AI predictions
        'sofascore': 1.0,      # Fan vote
        'gemini': 1.5,         # LLM analysis
        'consensus': 2.0       # Zgodność źródeł
    }
    
    CALIBRATION_FILE = "outputs/calibration_weights.json"
    
    def __init__(self, data_dir: str = "outputs"):
        self.data_dir = data_dir
        self.weights = self.DEFAULT_WEIGHTS.copy()
        self._load_calibration()
    
    def _load_calibration(self):
        """Wczytuje zapisane wagi kalibracyjne"""
        if os.path.exists(self.CALIBRATION_FILE):
            try:
                with open(self.CALIBRATION_FILE, 'r') as f:
                    data = json.load(f)
                    self.weights = data.get('source_weights', self.DEFAULT_WEIGHTS)
                    print(f"Wczytano kalibrację z {self.CALIBRATION_FILE}")
            except Exception as e:
                print(f"Błąd wczytywania kalibracji: {e}")
    
    def _save_calibration(self, result: CalibrationResult):
        """Zapisuje wagi kalibracyjne"""
        os.makedirs(os.path.dirname(self.CALIBRATION_FILE), exist_ok=True)
        with open(self.CALIBRATION_FILE, 'w') as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"Zapisano kalibrację do {self.CALIBRATION_FILE}")
    
    def analyze_source_accuracy(self, days: int = 30) -> Dict[str, SourceAccuracy]:
        """
        Analizuje trafność każdego źródła danych.
        
        Args:
            days: Liczba dni wstecz
            
        Returns:
            Dict z SourceAccuracy dla każdego źródła
        """
        sources = {
            'livesport': SourceAccuracy('livesport'),
            'forebet': SourceAccuracy('forebet'),
            'sofascore': SourceAccuracy('sofascore'),
            'gemini': SourceAccuracy('gemini'),
            'consensus': SourceAccuracy('consensus')
        }
        
        predictions = self._get_predictions_with_results(days)
        
        for pred in predictions:
            actual = pred.get('actual_result')
            if not actual:
                continue
            
            # Livesport H2H
            if pred.get('livesport_win_rate') is not None:
                sources['livesport'].total_predictions += 1
                h2h_pred = '1' if pred.get('livesport_win_rate', 0) >= 60 else '2'
                if h2h_pred == actual:
                    sources['livesport'].correct_predictions += 1
            
            # Forebet
            if pred.get('forebet_prediction'):
                sources['forebet'].total_predictions += 1
                if pred['forebet_prediction'] == actual:
                    sources['forebet'].correct_predictions += 1
            
            # SofaScore Fan Vote
            if pred.get('sofascore_home_win_prob') is not None:
                sources['sofascore'].total_predictions += 1
                home_prob = pred.get('sofascore_home_win_prob', 0)
                away_prob = pred.get('sofascore_away_win_prob', 0)
                ss_pred = '1' if home_prob > away_prob else '2' if away_prob > home_prob else 'X'
                if ss_pred == actual:
                    sources['sofascore'].correct_predictions += 1
            
            # Gemini AI
            if pred.get('gemini_recommendation'):
                sources['gemini'].total_predictions += 1
                # HIGH/LOCK = correct if we predicted the actual winner
                if pred.get('gemini_recommendation') in ['HIGH', 'LOCK']:
                    # Zakładamy predykcję na podstawie focus_team
                    if pred.get('focus_team') == 'home' and actual == '1':
                        sources['gemini'].correct_predictions += 1
                    elif pred.get('focus_team') == 'away' and actual == '2':
                        sources['gemini'].correct_predictions += 1
        
        # Oblicz accuracy
        for source in sources.values():
            source.calculate_accuracy()
        
        return sources
    
    def _get_predictions_with_results(self, days: int) -> List[Dict]:
        """Pobiera predykcje z wynikami z bazy"""
        if not SUPABASE_AVAILABLE:
            # Fallback - demo data
            return self._generate_demo_predictions()
        
        try:
            db = SupabaseManager()
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            response = db.client.table('predictions').select('*')\
                .gte('match_date', since)\
                .not_.is_('actual_result', 'null')\
                .execute()
            
            return response.data
        except Exception as e:
            print(f"Błąd pobierania danych: {e}")
            return []
    
    def _generate_demo_predictions(self) -> List[Dict]:
        """Generuje demo dane do testów"""
        import random
        random.seed(42)
        
        predictions = []
        for i in range(100):
            actual = random.choice(['1', 'X', '2'])
            predictions.append({
                'id': i,
                'actual_result': actual,
                'livesport_win_rate': random.randint(40, 80),
                'forebet_prediction': random.choice(['1', 'X', '2']),
                'forebet_probability': random.randint(40, 70),
                'sofascore_home_win_prob': random.randint(30, 60),
                'sofascore_away_win_prob': random.randint(20, 50),
                'gemini_recommendation': random.choice(['LOW', 'MEDIUM', 'HIGH', 'LOCK']),
                'focus_team': random.choice(['home', 'away'])
            })
        return predictions
    
    def calibrate(self, days: int = 30) -> CalibrationResult:
        """
        Przeprowadza kalibrację wag źródeł.
        
        Wagi są proporcjonalne do accuracy^2 (wyższa nagroda za lepszą trafność).
        """
        sources = self.analyze_source_accuracy(days)
        
        # Oblicz nowe wagi
        # Używamy accuracy^2 żeby bardziej premiować lepsze źródła
        total_score = sum(s.accuracy ** 2 for s in sources.values() if s.total_predictions > 10)
        
        if total_score == 0:
            print("Za mało danych do kalibracji")
            return CalibrationResult()
        
        new_weights = {}
        for name, source in sources.items():
            if source.total_predictions > 10:
                # Normalizuj do skali 0.5 - 2.0
                raw_weight = (source.accuracy ** 2) / total_score * len(sources)
                new_weights[name] = max(0.5, min(2.0, raw_weight))
            else:
                new_weights[name] = self.DEFAULT_WEIGHTS.get(name, 1.0)
        
        # Baseline accuracy
        total_correct = sum(s.correct_predictions for s in sources.values())
        total_preds = sum(s.total_predictions for s in sources.values())
        baseline = total_correct / total_preds if total_preds > 0 else 0
        
        result = CalibrationResult(
            source_weights=new_weights,
            baseline_accuracy=baseline,
            calibrated_at=datetime.now().isoformat(),
            predictions_analyzed=len(self._get_predictions_with_results(days))
        )
        
        self.weights = new_weights
        self._save_calibration(result)
        
        return result
    
    def calculate_confidence(
        self,
        prediction: Dict,
        use_calibration: bool = True
    ) -> float:
        """
        Oblicza confidence score (0-100) dla predykcji.
        
        Uwzględnia:
        - Zgodność źródeł
        - Siłę H2H
        - Różnicę w formie
        - Pewność Forebet
        - Fan vote margin
        
        Args:
            prediction: Dict z danymi predykcji
            use_calibration: Czy używać skalibrowanych wag
            
        Returns:
            Confidence score 0-100
        """
        weights = self.weights if use_calibration else self.DEFAULT_WEIGHTS
        
        confidence_factors = []
        
        # 1. H2H Win Rate (0-100)
        h2h_rate = prediction.get('livesport_win_rate', 50)
        h2h_score = h2h_rate * weights.get('livesport', 1.0)
        confidence_factors.append(('h2h', h2h_score, 1.0))
        
        # 2. Forebet Probability (0-100)
        forebet_prob = prediction.get('forebet_probability', 0)
        if forebet_prob > 0:
            forebet_score = forebet_prob * weights.get('forebet', 1.0)
            confidence_factors.append(('forebet', forebet_score, 1.0))
        
        # 3. SofaScore margin
        ss_home = prediction.get('sofascore_home_win_prob', 0)
        ss_away = prediction.get('sofascore_away_win_prob', 0)
        ss_margin = abs(ss_home - ss_away)
        # Margin 0-50 -> score 0-100
        ss_score = min(ss_margin * 2, 100) * weights.get('sofascore', 1.0)
        if ss_margin > 0:
            confidence_factors.append(('sofascore', ss_score, 0.8))
        
        # 4. Gemini recommendation
        gemini_map = {'LOCK': 95, 'HIGH': 80, 'MEDIUM': 60, 'LOW': 40, 'AVOID': 20}
        gemini_rec = prediction.get('gemini_recommendation', '')
        gemini_score = gemini_map.get(gemini_rec, 50) * weights.get('gemini', 1.0)
        if gemini_rec:
            confidence_factors.append(('gemini', gemini_score, 1.2))
        
        # 5. Consensus (ile źródeł się zgadza)
        agreement = self._count_agreement(prediction)
        consensus_score = agreement * 25 * weights.get('consensus', 1.0)  # 0-4 sources * 25
        confidence_factors.append(('consensus', consensus_score, 1.5))
        
        # Ważona średnia
        if not confidence_factors:
            return 50.0
        
        total_weighted = sum(score * weight for _, score, weight in confidence_factors)
        total_weights = sum(weight for _, _, weight in confidence_factors)
        
        raw_confidence = total_weighted / total_weights
        
        # Normalizuj do 0-100
        confidence = max(0, min(100, raw_confidence))
        
        return round(confidence, 1)
    
    def _count_agreement(self, prediction: Dict) -> int:
        """Liczy ile źródeł zgadza się z predykcją"""
        agreement = 0
        focus = prediction.get('focus_team', 'home')
        expected_result = '1' if focus == 'home' else '2'
        
        # H2H
        if prediction.get('livesport_win_rate', 0) >= 60:
            agreement += 1
        
        # Forebet
        if prediction.get('forebet_prediction') == expected_result:
            agreement += 1
        
        # SofaScore
        ss_home = prediction.get('sofascore_home_win_prob', 0)
        ss_away = prediction.get('sofascore_away_win_prob', 0)
        if (focus == 'home' and ss_home > ss_away) or (focus == 'away' and ss_away > ss_home):
            agreement += 1
        
        # Gemini
        if prediction.get('gemini_recommendation') in ['HIGH', 'LOCK']:
            agreement += 1
        
        return agreement
    
    def print_analysis(self, days: int = 30):
        """Wyświetla analizę źródeł"""
        sources = self.analyze_source_accuracy(days)
        
        print("\n" + "="*60)
        print(f"ANALIZA TRAFNOŚCI - Ostatnie {days} dni")
        print("="*60)
        
        for name, source in sorted(sources.items(), key=lambda x: x[1].accuracy, reverse=True):
            if source.total_predictions > 0:
                bar_len = int(source.accuracy * 30)
                bar = "[" + "#" * bar_len + " " * (30 - bar_len) + "]"
                print(f"\n{name.upper()}")
                print(f"  {bar} {source.accuracy*100:.1f}%")
                print(f"  {source.correct_predictions}/{source.total_predictions} predykcji")
                print(f"  Waga: {self.weights.get(name, 1.0):.2f}")
        
        print("\n" + "="*60)


def main():
    """Główna funkcja CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Confidence Calibrator dla BigOne')
    parser.add_argument('--analyze', action='store_true', help='Analiza źródeł')
    parser.add_argument('--calibrate', action='store_true', help='Uruchom kalibrację')
    parser.add_argument('--days', type=int, default=30, help='Okres w dniach')
    parser.add_argument('--test', action='store_true', help='Tryb testowy z demo danymi')
    
    args = parser.parse_args()
    
    calibrator = ConfidenceCalibrator()
    
    if args.analyze:
        calibrator.print_analysis(args.days)
    
    if args.calibrate:
        print("\nUruchamiam kalibrację...")
        result = calibrator.calibrate(args.days)
        print("\nNowe wagi:")
        for source, weight in result.source_weights.items():
            print(f"  {source}: {weight:.3f}")
        print(f"\nBaseline accuracy: {result.baseline_accuracy*100:.1f}%")
    
    if args.test:
        # Test confidence calculation
        demo_pred = {
            'livesport_win_rate': 70,
            'forebet_prediction': '1',
            'forebet_probability': 65,
            'sofascore_home_win_prob': 55,
            'sofascore_away_win_prob': 25,
            'gemini_recommendation': 'HIGH',
            'focus_team': 'home'
        }
        confidence = calibrator.calculate_confidence(demo_pred)
        print(f"\nTest confidence: {confidence}")


if __name__ == '__main__':
    main()
