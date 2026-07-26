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

# Model - Gemini 2.0 Flash (fast + free tier)
GEMINI_MODEL = "models/gemini-2.0-flash"

# v7.3 — łańcuch modeli próbowanych w kolejności przy quota/deprecated.
# Pierwszy działający zostaje zapamiętany w `_GEMINI_ACTIVE_MODEL`.
# Override przez env var: GEMINI_MODEL_CHAIN=model1,model2,...
_GEMINI_MODEL_CHAIN_DEFAULT = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash-001",
    "models/gemini-2.0-flash",
    "models/gemini-1.5-flash-002",
    "models/gemini-1.5-flash-8b",
]
GEMINI_MODEL_CHAIN = [
    m.strip() for m in (
        os.getenv('GEMINI_MODEL_CHAIN', '').strip()
        or ','.join(_GEMINI_MODEL_CHAIN_DEFAULT)
    ).split(',') if m.strip()
]
_GEMINI_ACTIVE_MODEL: Optional[str] = None


def _is_quota_or_rate_error(exc: BaseException) -> bool:
    msg = f"{type(exc).__name__}: {exc}".lower()
    return any(n in msg for n in (
        '429', 'resource_exhausted', 'quota', 'rate limit',
        'rate_limit', 'too many requests', 'overloaded',
    ))


def _is_model_unavailable_error(exc: BaseException) -> bool:
    msg = f"{type(exc).__name__}: {exc}".lower()
    return any(n in msg for n in (
        'model_not_found', 'model not found', 'decommissioned',
        'deprecated', 'does not exist', 'invalid model',
        'not_found_error', 'unsupported model', '404',
    ))


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
    
    # Przygotuj prompt dla AI (wspólny dla wszystkich backendów)
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

    # ------------------------------------------------------------------
    # Backend selection.
    # Gemini is tried first only when it is genuinely usable. When the SDK or
    # key is missing — the state this repo has been in for its whole history,
    # 0 predictions across 160k matches — we go straight to Groq instead of
    # returning a SKIP placeholder.
    # ------------------------------------------------------------------
    gemini_usable = GEMINI_AVAILABLE and bool(GEMINI_API_KEY)

    if gemini_usable:
        try:
            genai.configure(api_key=GEMINI_API_KEY)
        except Exception as e:
            print(f"   ⚠️ Gemini config error ({e}) — próbuję Groq")
            gemini_usable = False

    if not gemini_usable:
        groq_result = _analyze_with_groq(prompt)
        if groq_result is not None:
            return groq_result
        return {
            'prediction': 'Brak dostępnego backendu AI',
            'confidence': 0,
            'reasoning': ('Gemini: brak SDK lub klucza; Groq: brak GROQ_API_KEY '
                          'lub błąd API'),
            'recommendation': 'SKIP',
            'error': 'No AI backend available',
        }

    # v7.3 — rotacja modeli z chain. Pierwszy działający → cache.
    global _GEMINI_ACTIVE_MODEL
    chain = list(GEMINI_MODEL_CHAIN)
    if _GEMINI_ACTIVE_MODEL and _GEMINI_ACTIVE_MODEL in chain:
        chain.remove(_GEMINI_ACTIVE_MODEL)
        chain.insert(0, _GEMINI_ACTIVE_MODEL)

    last_err: Optional[BaseException] = None
    for model_name in chain:
        try:
            model = genai.GenerativeModel(model_name)
        except Exception as e:
            last_err = e
            if _is_model_unavailable_error(e):
                print(f"   🔁 Gemini ({model_name}): model niedostępny — rotuję")
                continue
            return {
                'prediction': 'Błąd inicjalizacji modelu',
                'confidence': 0,
                'reasoning': str(e),
                'recommendation': 'SKIP',
                'error': f'Model init error: {e}'
            }

        # Per-model retry z krótkim backoffem dla transient errors
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = model.generate_content(prompt)
                result = _parse_gemini_response(response.text)
                _GEMINI_ACTIVE_MODEL = model_name
                return result
            except Exception as e:
                last_err = e
                if _is_quota_or_rate_error(e):
                    print(f"   🔁 Gemini ({model_name}): quota/429 — rotuję")
                    break  # przerwij retry, przejdź do kolejnego modelu
                if _is_model_unavailable_error(e):
                    print(f"   🔁 Gemini ({model_name}): model niedostępny — rotuję")
                    break
                if attempt < MAX_RETRIES:
                    print(f"   ⚠️ Gemini ({model_name}) attempt {attempt + 1}/{MAX_RETRIES + 1}: {type(e).__name__}: {str(e)[:80]}")
                    time.sleep(2)
                # ostatnia próba - wyjdź z attempt loopa, ale NIE rotuj
                # (transient błąd, niezwiązany z modelem)

        # Jeśli pętla retry skończyła się BEZ break (= bez quota/model error),
        # to znaczy ostatni attempt rzucił, ale to nie quota — nie rotujemy.
        if not (_is_quota_or_rate_error(last_err) or _is_model_unavailable_error(last_err)):
            break

    # Gemini chain exhausted — fall back to Groq before giving up, so a
    # quota-exhausted Gemini key does not silently disable AI analysis.
    print(f"   ↻ Gemini wyczerpany ({len(chain)} modeli) — przechodzę na Groq")
    groq_result = _analyze_with_groq(prompt)
    if groq_result is not None:
        return groq_result

    return {
        'prediction': f'Błąd API (po {len(chain)} modelach)',
        'confidence': 0,
        'reasoning': str(last_err) if last_err else 'unknown',
        'recommendation': 'SKIP',
        'error': f'API error: {type(last_err).__name__ if last_err else "?"}'
    }


def _analyze_with_groq(prompt: str) -> Optional[Dict[str, Any]]:
    """Run the analysis prompt through Groq. Returns None when unavailable.

    Uses the same prompt and the same response parser as Gemini, so the output
    shape (prediction/confidence/reasoning/recommendation) is identical and
    downstream consumers need no changes. ``ai_provider`` records which backend
    actually answered.
    """
    try:
        import groq_client
        import requests
    except ImportError:
        return None

    key = groq_client.api_key()
    if not key:
        return None

    model = groq_client.resolve_model(key)

    def _post(model_id: str):
        return requests.post(
            groq_client.CHAT_ENDPOINT,
            headers={'Authorization': f'Bearer {key}',
                     'Content-Type': 'application/json'},
            json={
                'model': model_id,
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.2,
                'max_tokens': 700,
            },
            timeout=groq_client.REQUEST_TIMEOUT,
        )

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = _post(model)
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(2)
                continue
            print(f"   ⚠️ Groq AI error: {type(e).__name__}: {str(e)[:80]}")
            return None

        # Retired model → re-resolve once and retry.
        if groq_client.is_decommissioned_error(resp.status_code, resp.text):
            groq_client.reset_resolved_model()
            new_model = groq_client.resolve_model(key, force=True)
            if new_model != model:
                print(f"   ↻ Groq: model '{model}' wycofany → '{new_model}'")
                model = new_model
                continue

        if resp.status_code == 200:
            try:
                text = resp.json()['choices'][0]['message']['content']
            except (KeyError, IndexError, ValueError) as e:
                print(f"   ⚠️ Groq: nieczytelna odpowiedź ({e})")
                return None
            result = _parse_gemini_response(text)
            result['ai_provider'] = f'groq:{model}'
            return result

        # 429 / 5xx are worth one retry; anything else is terminal.
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt < MAX_RETRIES:
                time.sleep(2)
                continue
        print(f"   ⚠️ Groq API {resp.status_code}: {resp.text[:100]}")
        return None

    return None


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
    """Build an Ultra PRO analysis prompt for Gemini API (English output)."""

    prompt = f"""You are a professional sports analyst with deep expertise in {sport}.
Provide a comprehensive, data-driven analysis of the upcoming match.

## MATCH
{home_team} (home) vs {away_team} (away)
Sport: {sport}

## DATA
"""

    # H2H
    if h2h_data:
        total_h2h = h2h_data.get('total', 5)
        hw = h2h_data.get('home_wins', 0)
        aw = h2h_data.get('away_wins', 0)
        dr = h2h_data.get('draws', 0)
        prompt += f"\n### Head-to-Head (last {total_h2h} meetings)\n"
        prompt += f"- {home_team} wins: {hw}\n"
        prompt += f"- {away_team} wins: {aw}\n"
        if dr:
            prompt += f"- Draws: {dr}\n"
        if total_h2h > 0:
            wr = hw / total_h2h * 100
            prompt += f"- Home H2H win rate: {wr:.0f}%\n"

    # Overall form
    if home_form or away_form:
        prompt += "\n### Recent Form (overall)\n"
        if home_form:
            prompt += f"- {home_team}: {home_form}\n"
        if away_form:
            prompt += f"- {away_team}: {away_form}\n"

    # Venue-specific form
    if home_form_away or away_form_away:
        prompt += "\n### Venue-Specific Form\n"
        if home_form_away:
            prompt += f"- {home_team} at HOME: {home_form_away}\n"
        if away_form_away:
            prompt += f"- {away_team} AWAY: {away_form_away}\n"

    # Forebet
    if forebet_prediction:
        prompt += f"\n### Forebet Prediction\n{forebet_prediction}\n"

    # Odds
    if home_odds or away_odds:
        prompt += "\n### Bookmaker Odds\n"
        if home_odds:
            prompt += f"- {home_team}: {home_odds}\n"
        if away_odds:
            prompt += f"- {away_team}: {away_odds}\n"
        if draw_odds:
            prompt += f"- Draw: {draw_odds}\n"

    # Additional info
    if additional_info:
        prompt += f"\n### Additional Context\n{additional_info}\n"

    # Instructions
    prompt += """

## TASK
Analyze ALL available data above and respond **in English** using EXACTLY this format:

PICK: [exactly one of: 1 | X | 2 — where 1 = home win, X = draw, 2 = away win. Use X only in sports that can end level.]
PREDICTION: [1-2 sentence prediction with key reasoning]
CONFIDENCE: [0-100 integer]
REASONING: [4-6 sentences covering: H2H patterns, form trends, home/away advantage, odds analysis, and overall risk assessment. Mention specific numbers.]
KEY_FACTORS: [Comma-separated list of 3-5 main factors driving your prediction, e.g. "Strong H2H record (4/5 wins), Excellent home form, Favorable odds value"]
RISK_FACTORS: [Comma-separated list of 1-3 risks or counter-arguments, e.g. "Away team improving form, Close odds suggest uncertainty"]
RECOMMENDATION: [HIGH/MEDIUM/LOW/SKIP]

RULES:
- Be specific and data-driven. Reference actual numbers from the data.
- CONFIDENCE reflects prediction certainty: 85+ only when multiple strong signals align.
- HIGH recommendation: strong data support, confidence ≥ 75, clear edge visible.
- MEDIUM: decent signals but some uncertainty, confidence 55-74.
- LOW: weak signals or conflicting data, confidence 35-54.
- SKIP: insufficient data or high risk, confidence < 35.
"""

    return prompt


def _parse_gemini_response(response_text: str) -> Dict[str, Any]:
    """Parse structured Gemini response including new KEY_FACTORS / RISK_FACTORS."""

    result: Dict[str, Any] = {
        'prediction': '',
        # Machine-readable outcome. The scoring engine maps the prediction to a
        # side via its FIRST CHARACTER, so a prose sentence ("Wisla is likely…")
        # silently read as a draw signal. The model is now asked for an explicit
        # 1/X/2 token, and empty means "no usable pick" so the engine abstains.
        'pick': '',
        'confidence': 0,
        'reasoning': '',
        'recommendation': 'SKIP',
        'key_factors': [],
        'risk_factors': [],
        'error': None
    }

    try:
        lines = response_text.strip().split('\n')

        for line in lines:
            line = line.strip()

            if line.startswith('PICK:'):
                token = line.replace('PICK:', '').strip().upper()
                # Tolerate decorations like "**1**" or "1 (home win)".
                for candidate in ('1', 'X', '2'):
                    if candidate in token:
                        result['pick'] = candidate
                        break

            elif line.startswith('PREDICTION:'):
                result['prediction'] = line.replace('PREDICTION:', '').strip()

            elif line.startswith('CONFIDENCE:'):
                conf_str = line.replace('CONFIDENCE:', '').strip()
                import re
                match = re.search(r'(\d+)', conf_str)
                if match:
                    result['confidence'] = int(match.group(1))

            elif line.startswith('REASONING:'):
                result['reasoning'] = line.replace('REASONING:', '').strip()

            elif line.startswith('KEY_FACTORS:'):
                raw = line.replace('KEY_FACTORS:', '').strip()
                result['key_factors'] = [f.strip() for f in raw.split(',') if f.strip()]

            elif line.startswith('RISK_FACTORS:'):
                raw = line.replace('RISK_FACTORS:', '').strip()
                result['risk_factors'] = [f.strip() for f in raw.split(',') if f.strip()]

            elif line.startswith('RECOMMENDATION:'):
                rec = line.replace('RECOMMENDATION:', '').strip().upper()
                if rec in ['HIGH', 'MEDIUM', 'LOW', 'SKIP']:
                    result['recommendation'] = rec

        # Fallback: if parsing failed, use raw text
        if not result['prediction'] and response_text:
            result['prediction'] = response_text[:200]
            result['confidence'] = 50
            result['reasoning'] = response_text
            result['recommendation'] = 'MEDIUM'

    except Exception as e:
        result['error'] = f'Parse error: {e}'
        result['prediction'] = 'Response parsing error'

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
