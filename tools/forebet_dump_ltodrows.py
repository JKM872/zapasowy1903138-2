"""
Diagnostyka: wyciagnij definicje `ltodrows` z JS Forebet.
=========================================================
Kontrolka "More" na liscie predykcji Forebet to:

    <span onclick='ltodrows("1x2","2026-09-12","","0","-240","1789153200","1789261200")'>More</span>

czyli doladowanie AJAX-em. Bez znajomosci endpointu nie da sie pobrac dalszej
czesci dnia inaczej niz przegladarka, a zadna przegladarka nie przechodzi
Cloudflare na runnerze GitHuba (`cloudflare_bypass.get_page()` wprost pomija w
CI undetected/puppeteer/drissionpage/playwright).

FlareSolverr przez Cloudflare przechodzi, wiec pobieramy nim plik JS i
wypisujemy cialo funkcji. Skrypt jest tylko po to, zeby TEN adres poznac —
implementacja paginacji ma potem uzywac go wprost, bez przegladarki.

Uruchomienie:
    python tools/forebet_dump_ltodrows.py
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

JS_CANDIDATES = [
    'https://www.forebet.com/includes/js/all.js?v=618',
    'https://www.forebet.com/includes/js/all.js',
    'https://www.forebet.com/includes/js/stsrt.js?v=1',
]


def fetch(url: str) -> str | None:
    """Pobierz plik przez ten sam bypass, ktorego uzywa glowny workflow."""
    try:
        from cloudflare_bypass import fetch_forebet_with_bypass
    except Exception as e:
        print(f"BLAD importu cloudflare_bypass: {e}")
        return None
    try:
        return fetch_forebet_with_bypass(url, debug=True)
    except Exception as e:
        print(f"BLAD pobierania {url}: {type(e).__name__}: {e}")
        return None


def dump_function(js: str, name: str) -> None:
    """Wypisz cialo funkcji `name` (proste dopasowanie nawiasow klamrowych)."""
    for m in re.finditer(rf'function\s+{re.escape(name)}\s*\(', js):
        start = m.start()
        depth = 0
        i = js.find('{', m.end())
        if i < 0:
            continue
        j = i
        while j < len(js):
            if js[j] == '{':
                depth += 1
            elif js[j] == '}':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = js[start:j + 1]
        print(f"\n===== function {name} ({len(body)} znakow) =====")
        print(body[:4000])
        print("===== koniec =====\n")
        return
    print(f"Nie znalazlem definicji function {name}")


def main() -> None:
    for url in JS_CANDIDATES:
        print(f"\n>>> Pobieram {url}")
        js = fetch(url)
        if not js:
            print("   brak tresci")
            continue
        print(f"   otrzymano {len(js)} znakow")

        if 'ltodrows' not in js:
            print("   brak 'ltodrows' w tym pliku")
            continue

        dump_function(js, 'ltodrows')

        # Wszystkie adresy, ktore moglyby byc endpointem doladowania.
        urls = set(re.findall(r'["\']((?:/|https?://)[^"\']*(?:ajax|ltod|rows|more|load)[^"\']*)["\']',
                              js, re.IGNORECASE))
        if urls:
            print("Kandydaci na endpoint (ajax/ltod/rows/more/load):")
            for u in sorted(urls)[:40]:
                print(f"   {u}")

        # Wywolania XHR/fetch w okolicy ltodrows.
        for m in re.finditer(r'ltodrows', js):
            frag = js[max(0, m.start() - 200): m.start() + 1200]
            if 'open(' in frag or 'fetch(' in frag or 'ajax' in frag.lower():
                print("\n--- fragment z wywolaniem zadania ---")
                print(frag[:1500])
                break
        return

    print("\nNie udalo sie znalezc definicji w zadnym z plikow.")


if __name__ == '__main__':
    main()
