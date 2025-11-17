"""
Gemini AI Analyzer - Inteligentna analiza meczów
------------------------------------------------
Wykorzystuje Google Gemini API do głębokiej analizy meczów na podstawie:
- H2H (ostatnie 5 spotkań bezpośrednich)
- Forma drużyn (home/away)
- Forebet predictions (jeśli dostępne)
- Odds (kursy bukmacherskie)

Output: 
- gemini_prediction: krótka, zwięzła predykcja (1-2 zdania)
- gemini_confidence: 0-100% (pewność AI)
- gemini_reasoning: szczegółowe uzasadnienie (opcjonalne)

Wymagania:
- pip install google-generativeai
- Darmowy API key z: https://makersuite.google.com/app/apikey
- Limit: 60 requests/minute (wystarczające dla większości zastosowań)

Usage:
    from gemini_analyzer import analyze_match
    
    result = analyze_match(
        home_team="Resovia",
        away_team="BBTS Bielsko-Biała",
        h2h_data={"home_wins": 3, "away_wins": 1, "draws": 1},
        home_form="7/10",
        away_form="2/10",
        forebet_prediction="62% home win",
        home_odds=1.45,
        away_odds=2.80
    )
    
    print(result['prediction'])  # ⭐ HIGH: Dom wygrał 3/5 H2H...
    print(result['confidence'])  # 85
"""

import os
import time
from typing import Dict, Optional, Any

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("⚠️ google-generativeai not installed. Run: pip install google-generativeai")


# ============================================
# KONFIGURACJA
# ============================================

# API Key (pobierz z: https://makersuite.google.com/app/apikey)
# Można też ustawić jako zmienną środowiskową: GEMINI_API_KEY
try:
    from gemini_config import GEMINI_API_KEY
except ImportError:
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', None)

# Model - gemini-1.5-flash jest szybki i darmowy (60 req/min)
GEMINI_MODEL = "gemini-1.5-flash"

# Timeout i retry
REQUEST_TIMEOUT = 10  # sekundy
MAX_RETRIES = 2


# ============================================
# GŁÓWNA FUNKCJA ANALIZY
# ============================================

def analyze_match(
    home_team: str,
    away_team: str,
    sport: str = "volleyball",
    h2h_data: Optional[Dict[str, int]] = None,
    home_form: Optional[str] = None,
    away_form: Optional[str] = None,
    home_form_away: Optional[str] = None,
    away_form_away: Optional[str] = None,
    forebet_prediction: Optional[str] = None,
    home_odds: Optional[float] = None,
    away_odds: Optional[float] = None,
    draw_odds: Optional[float] = None,
    additional_info: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analizuje mecz używając Gemini AI
    
    Args:
        home_team: Nazwa gospodarzy
        away_team: Nazwa gości
        sport: Sport (volleyball, football, etc.)
        h2h_data: {"home_wins": 3, "away_wins": 1, "draws": 1, "total": 5}
        home_form: Forma gospodarzy ogólna (np. "7/10")
        away_form: Forma gości ogólna (np. "4/10")
        home_form_away: Forma gospodarzy u siebie (np. "8/10")
        away_form_away: Forma gości na wyjeździe (np. "2/10")
        forebet_prediction: Predykcja z Forebet (np. "62% home win")
        home_odds: Kurs na gospodarzy (np. 1.45)
        away_odds: Kurs na gości (np. 2.80)
        draw_odds: Kurs na remis (jeśli dostępny)
        additional_info: Dodatkowe info (ligi, ostatnia data H2H, etc.)
    
    Returns:
        {
            'prediction': str,      # Krótka predykcja (1-2 zdania)
            'confidence': int,      # 0-100%
            'reasoning': str,       # Szczegółowe uzasadnienie
            'recommendation': str,  # HIGH/MEDIUM/LOW/SKIP
            'error': str            # Jeśli wystąpił błąd
        }
    """
    
    # Sprawdź dostępność
    if not GEMINI_AVAILABLE:
        return {
            'prediction': 'Gemini AI niedostępne',
            'confidence': 0,
            'reasoning': 'Zainstaluj: pip install google-generativeai',
            'recommendation': 'SKIP',
            'error': 'Gemini SDK not installed'
        }
    
    if not GEMINI_API_KEY:
        return {
            'prediction': 'Brak API key',
            'confidence': 0,
            'reasoning': 'Ustaw GEMINI_API_KEY w gemini_config.py lub jako zmienną środowiskową',
            'recommendation': 'SKIP',
            'error': 'No API key configured'
        }
    
    # Skonfiguruj API
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
    except Exception as e:
        return {
            'prediction': 'Błąd konfiguracji API',
            'confidence': 0,
            'reasoning': str(e),
            'recommendation': 'SKIP',
            'error': f'API configuration error: {e}'
        }
    
    # Przygotuj prompt dla AI
    prompt = _build_analysis_prompt(
        home_team=home_team,
        away_team=away_team,
        sport=sport,
        h2h_data=h2h_data,
        home_form=home_form,
        away_form=away_form,
        home_form_away=home_form_away,
        away_form_away=away_form_away,
        forebet_prediction=forebet_prediction,
        home_odds=home_odds,
        away_odds=away_odds,
        draw_odds=draw_odds,
        additional_info=additional_info
    )
    
    # Wywołaj API z retry
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = model.generate_content(prompt)
            
            # Parsuj odpowiedź
            result = _parse_gemini_response(response.text)
            return result
            
        except Exception as e:
            if attempt < MAX_RETRIES:
                print(f"⚠️ Gemini API error (attempt {attempt + 1}/{MAX_RETRIES + 1}): {e}")
                time.sleep(2)  # Odczekaj przed retry
            else:
                return {
                    'prediction': f'Błąd API (po {MAX_RETRIES + 1} próbach)',
                    'confidence': 0,
                    'reasoning': str(e),
                    'recommendation': 'SKIP',
                    'error': f'API error after {MAX_RETRIES + 1} attempts: {e}'
                }


# ============================================
# HELPER FUNCTIONS
# ============================================

def _build_analysis_prompt(
    home_team: str,
    away_team: str,
    sport: str,
    h2h_data: Optional[Dict[str, int]],
    home_form: Optional[str],
    away_form: Optional[str],
    home_form_away: Optional[str],
    away_form_away: Optional[str],
    forebet_prediction: Optional[str],
    home_odds: Optional[float],
    away_odds: Optional[float],
    draw_odds: Optional[float],
    additional_info: Optional[str]
) -> str:
    """Buduje prompt dla Gemini API"""
    
    prompt = f"""Jesteś ekspertem analitykiem sportowym specjalizującym się w {sport}. 
Przeanalizuj nadchodzący mecz i podaj swoją predykcję.

**MECZ:**
{home_team} (gospodarze) vs {away_team} (goście)
Sport: {sport}

**DANE:**
"""
    
    # H2H
    if h2h_data:
        prompt += f"\n**Head-to-Head (ostatnie {h2h_data.get('total', 5)} spotkań):**\n"
        prompt += f"- Wygrane gospodarzy: {h2h_data.get('home_wins', 0)}\n"
        prompt += f"- Wygrane gości: {h2h_data.get('away_wins', 0)}\n"
        if 'draws' in h2h_data:
            prompt += f"- Remisy: {h2h_data.get('draws', 0)}\n"
    
    # Forma
    if home_form or away_form:
        prompt += "\n**Forma ogólna:**\n"
        if home_form:
            prompt += f"- {home_team}: {home_form}\n"
        if away_form:
            prompt += f"- {away_team}: {away_form}\n"
    
    if home_form_away or away_form_away:
        prompt += "\n**Forma (miejsce meczu):**\n"
        if home_form_away:
            prompt += f"- {home_team} (u siebie): {home_form_away}\n"
        if away_form_away:
            prompt += f"- {away_team} (na wyjeździe): {away_form_away}\n"
    
    # Forebet
    if forebet_prediction:
        prompt += f"\n**Forebet prediction:** {forebet_prediction}\n"
    
    # Odds
    if home_odds or away_odds:
        prompt += "\n**Kursy bukmacherskie:**\n"
        if home_odds:
            prompt += f"- {home_team}: {home_odds}\n"
        if away_odds:
            prompt += f"- {away_team}: {away_odds}\n"
        if draw_odds:
            prompt += f"- Remis: {draw_odds}\n"
    
    # Dodatkowe info
    if additional_info:
        prompt += f"\n**Dodatkowe informacje:** {additional_info}\n"
    
    # Instrukcje dla AI
    prompt += """

**ZADANIE:**
Na podstawie powyższych danych podaj:

1. **PREDICTION** (1-2 zdania): Zwięzła predykcja wyniku z kluczowymi argumentami
2. **CONFIDENCE** (0-100): Twoja pewność predykcji (liczba)
3. **REASONING** (3-5 zdań): Szczegółowe uzasadnienie z analizą wszystkich czynników
4. **RECOMMENDATION** (HIGH/MEDIUM/LOW/SKIP): Rekomendacja czy warto stawiać

**FORMAT ODPOWIEDZI:**
PREDICTION: [twoja predykcja]
CONFIDENCE: [0-100]
REASONING: [szczegółowe uzasadnienie]
RECOMMENDATION: [HIGH/MEDIUM/LOW/SKIP]

Bądź konkretny i merytoryczny. Uwzględnij wszystkie dostępne dane.
"""
    
    return prompt


def _parse_gemini_response(response_text: str) -> Dict[str, Any]:
    """Parsuje odpowiedź z Gemini API"""
    
    result = {
        'prediction': '',
        'confidence': 0,
        'reasoning': '',
        'recommendation': 'SKIP',
        'error': None
    }
    
    try:
        lines = response_text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            
            if line.startswith('PREDICTION:'):
                result['prediction'] = line.replace('PREDICTION:', '').strip()
            
            elif line.startswith('CONFIDENCE:'):
                conf_str = line.replace('CONFIDENCE:', '').strip()
                # Wyciągnij liczbę (może być "85" lub "85%")
                import re
                match = re.search(r'(\d+)', conf_str)
                if match:
                    result['confidence'] = int(match.group(1))
            
            elif line.startswith('REASONING:'):
                result['reasoning'] = line.replace('REASONING:', '').strip()
            
            elif line.startswith('RECOMMENDATION:'):
                rec = line.replace('RECOMMENDATION:', '').strip().upper()
                if rec in ['HIGH', 'MEDIUM', 'LOW', 'SKIP']:
                    result['recommendation'] = rec
        
        # Fallback: jeśli nie znaleziono struktury, użyj całego tekstu jako prediction
        if not result['prediction'] and response_text:
            result['prediction'] = response_text[:200]  # Pierwsze 200 znaków
            result['confidence'] = 50  # Neutralna pewność
            result['reasoning'] = response_text
            result['recommendation'] = 'MEDIUM'
    
    except Exception as e:
        result['error'] = f'Parse error: {e}'
        result['prediction'] = 'Błąd parsowania odpowiedzi'
    
    return result


# ============================================
# BATCH ANALYSIS (dla wielu meczów)
# ============================================

def analyze_matches_batch(matches_data: list, delay_between_requests: float = 1.0) -> list:
    """
    Analizuje wiele meczów z opóźnieniem między requestami (rate limiting)
    
    Args:
        matches_data: Lista słowników z danymi meczów (jak argumenty analyze_match)
        delay_between_requests: Opóźnienie między requestami (sekundy)
    
    Returns:
        Lista wyników analizy
    """
    results = []
    
    for i, match_data in enumerate(matches_data):
        print(f"🤖 Analyzing match {i+1}/{len(matches_data)}: {match_data.get('home_team')} vs {match_data.get('away_team')}")
        
        result = analyze_match(**match_data)
        results.append(result)
        
        # Rate limiting
        if i < len(matches_data) - 1:  # Nie czekaj po ostatnim
            time.sleep(delay_between_requests)
    
    return results


# ============================================
# TEST
# ============================================

if __name__ == "__main__":
    print("🤖 Gemini AI Analyzer - Test")
    print("=" * 50)
    
    if not GEMINI_AVAILABLE:
        print("❌ ERROR: google-generativeai not installed")
        print("   Run: pip install google-generativeai")
        exit(1)
    
    if not GEMINI_API_KEY:
        print("❌ ERROR: GEMINI_API_KEY not configured")
        print("   1. Get free API key: https://makersuite.google.com/app/apikey")
        print("   2. Create gemini_config.py with: GEMINI_API_KEY = 'your-key-here'")
        print("   OR set environment variable: GEMINI_API_KEY")
        exit(1)
    
    print("✅ Configuration OK")
    print(f"✅ API Key: {GEMINI_API_KEY[:10]}...{GEMINI_API_KEY[-5:]}")
    print(f"✅ Model: {GEMINI_MODEL}")
    print()
    
    # Test analysis
    print("Testing analysis...")
    result = analyze_match(
        home_team="Resovia Rzeszów",
        away_team="BBTS Bielsko-Biała",
        sport="volleyball",
        h2h_data={"home_wins": 3, "away_wins": 1, "draws": 0, "total": 5},
        home_form="7/10",
        away_form="4/10",
        home_form_away="8/10",
        away_form_away="2/10",
        forebet_prediction="65% home win",
        home_odds=1.45,
        away_odds=2.80
    )
    
    print("\n" + "=" * 50)
    print("📊 RESULTS:")
    print("=" * 50)
    print(f"🔮 Prediction: {result['prediction']}")
    print(f"📈 Confidence: {result['confidence']}%")
    print(f"💡 Reasoning: {result['reasoning']}")
    print(f"⭐ Recommendation: {result['recommendation']}")
    
    if result.get('error'):
        print(f"⚠️ Error: {result['error']}")
    
    print("\n✅ Test complete!")
