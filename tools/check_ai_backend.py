#!/usr/bin/env python3
"""Report which AI backend the pipeline will actually get.

Run as a CI preflight. The AI signal was dead for the entire life of this
repository — 0 usable picks across 1000 settled matches — and nothing said so:
Gemini's quota was gone, the Groq fallback returned None without a word, and
every affected row simply stored the text 'Błąd API' as if it were a verdict.
A five-line check at the start of a run makes that state impossible to miss.

Exit code is always 0: a missing AI backend degrades predictions, it does not
invalidate them, so it must not fail the scrape.

    python tools/check_ai_backend.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    print('=' * 62)
    print('  AI BACKEND PREFLIGHT')
    print('=' * 62)

    usable = []

    # --- Gemini -------------------------------------------------------
    try:
        from gemini_analyzer import GEMINI_AVAILABLE, GEMINI_API_KEY
        if not GEMINI_AVAILABLE:
            print('  Gemini : ❌ brak SDK (google-generativeai)')
        elif not GEMINI_API_KEY:
            print('  Gemini : ❌ brak GEMINI_API_KEY')
        else:
            print('  Gemini : ✅ SDK i klucz obecne')
            usable.append('gemini')
    except Exception as e:
        print(f'  Gemini : ❌ {type(e).__name__}: {str(e)[:60]}')

    # --- Groq ---------------------------------------------------------
    try:
        import groq_client
        key = groq_client.api_key()
        if not key:
            print('  Groq   : ❌ brak GROQ_API_KEY')
        else:
            models = groq_client.list_available_models(key)
            if not models:
                print('  Groq   : ❌ klucz obecny, ale API nie zwróciło modeli '
                      '(klucz nieważny lub odwołany?)')
            else:
                chosen = groq_client.resolve_model(key)
                print(f'  Groq   : ✅ {len(models)} modeli, wybrany: {chosen}')
                usable.append('groq')
    except Exception as e:
        print(f'  Groq   : ❌ {type(e).__name__}: {str(e)[:60]}')

    print('-' * 62)
    if usable:
        print(f'  ✅ Analiza AI dostępna przez: {", ".join(usable)}')
    else:
        print('  ⚠️ ŻADEN backend AI nie odpowiada — predykcje powstaną bez '
              'sygnału AI.')
        print('     Waga "gemini" rozłoży się na pozostałe źródła '
              '(silnik abstynuje, nie wstawia remisu).')
    print('=' * 62)
    return 0


if __name__ == '__main__':
    sys.exit(main())
