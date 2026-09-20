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
    #
    # Raportujemy KAŻDY klucz osobno. Przy kilku kluczach sama rotacja nic nie
    # mówi o tym, czy dają osobne pule: klucze z tego samego konta Groq dzielą
    # limit i pokażą identyczne pozostałe wartości. Bez tego raportu wygląda to
    # jak 4x większy limit, a jest jedno konto odpytywane cztery razy.
    try:
        import groq_client
        keys = groq_client.api_keys()
        if not keys:
            print('  Groq   : ❌ brak GROQ_API_KEY')
        else:
            print(f'  Groq   : skonfigurowanych kluczy: {len(keys)}')
            good = 0
            fingerprints = []
            for i, k in enumerate(keys, 1):
                label = f'key {i}' if i > 1 else 'key 1 (GROQ_API_KEY)'
                masked = f'{k[:6]}…{k[-4:]}' if len(k) > 12 else '(krótki)'
                st = groq_client.probe_key(k)
                rr = st['remaining_requests']
                rt = st['remaining_tokens']
                if st['ok']:
                    good += 1
                    busy = ' (limit wyczerpany, ale klucz ważny)' \
                        if st['status'] == 429 else ''
                    org = f", org={st['organization']}" if st['organization'] else ''
                    print(f'           ✅ {label} {masked}: '
                          f'{st["models"]} modeli, zapas: '
                          f'{rr or "?"} zapytań / {rt or "?"} tokenów'
                          f'{busy}{org}')
                    fingerprints.append((rr, rt, st['organization']))
                else:
                    print(f'           ❌ {label} {masked}: '
                          f'{st["error"] or "nie odpowiada"}')
            if good:
                usable.append('groq')

            # Ostrzeżenie o wspólnym koncie — identyczny zapas u dwóch kluczy.
            orgs = [f[2] for f in fingerprints if f[2]]
            if len(orgs) != len(set(orgs)):
                print('           ⚠️ Co najmniej dwa klucze należą do TEJ SAMEJ '
                      'organizacji — dzielą limit i nic nie dodają.')
            elif len(fingerprints) > 1:
                quotas = [f[0] for f in fingerprints if f[0] is not None]
                if len(quotas) > 1 and len(set(quotas)) == 1:
                    print('           ⚠️ Wszystkie klucze pokazują IDENTYCZNY '
                          'zapas zapytań — prawdopodobnie jedno konto. '
                          'Osobne pule wymagają osobnych kont Groq.')
                elif len(quotas) > 1:
                    print(f'           ✅ Zapasy różnią się między kluczami '
                          f'({len(set(quotas))} różnych wartości) — '
                          f'to osobne pule limitów.')
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
