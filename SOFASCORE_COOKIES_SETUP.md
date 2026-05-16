# SofaScore Cookies Setup (v8.1)

## Dlaczego

Cloudflare zaostrzył WAF dla IP GitHub Actions tak, że żadne automated browser
(headless Chrome, undetected_chromedriver, DrissionPage, FlareSolverr) nie
przechodzi czysto. Jedyne niezawodne rozwiązanie to **skopiowanie cookies
`cf_clearance` z prawdziwej Twojej przeglądarki** do GitHub Secret.

Cookies `cf_clearance` żyje **30 dni**, więc wystarczy odświeżać raz na miesiąc.

## Jak pobrać cookies (5 minut)

### Krok 1: Otwórz SofaScore w prawdziwej przeglądarce

Wejdź na <https://www.sofascore.com> w Chrome/Firefox/Edge **na komputerze**.
Zaczekaj aż strona w pełni się załaduje (lista meczów widoczna).

### Krok 2: Otwórz DevTools

Naciśnij `F12` (lub `Ctrl+Shift+I` / `Cmd+Option+I`).

### Krok 3: Przejdź do zakładki Cookies

**Chrome/Edge**:
- DevTools → zakładka **Application** (lub **Storage**)
- Lewy panel: **Cookies** → `https://www.sofascore.com`

**Firefox**:
- DevTools → zakładka **Storage**
- Lewy panel: **Cookies** → `https://www.sofascore.com`

### Krok 4: Skopiuj wartości dwóch cookies

Znajdź cookies o nazwach:

- `cf_clearance` — najważniejsze, długi token ~250 znaków
- `__cf_bm` — krótszy, ~50 znaków

Skopiuj **wartość** (kolumna "Value") każdego z nich.

### Krok 5: Złóż w jeden string

Zapisz wartość w formacie:

```
cf_clearance=WARTOSC_CF_CLEARANCE_TUTAJ; __cf_bm=WARTOSC_CF_BM_TUTAJ
```

Przykład (z fałszywymi wartościami):

```
cf_clearance=ABCdef123XYZ.qwerty.789-XYZ_token_dlugi; __cf_bm=krotszy_token_xyz789
```

### Krok 6: Dodaj do GitHub Secrets

1. Wejdź na repo → **Settings** → **Secrets and variables** → **Actions**
2. **New repository secret**
3. **Name**: `SOFASCORE_COOKIES`
4. **Secret**: wklej string ze Kroku 5
5. **Add secret**

### Krok 7: Test

Następny GitHub Actions run powinien pokazać w logu:

```
🍪 SofaScore: zaladowano 2 manual cookies z SOFASCORE_COOKIES env (['__cf_bm', 'cf_clearance'])
🚀 SofaScore: Szybka ścieżka przez API...
🚀 SofaScore: curl_cffi (Chrome TLS impersonation)
✅ Fan Vote: 🏠47% | 🤝28% | ✈️25% (11,842 głosów)
```

Brak więcej `403 Forbidden` → SofaScore Fan Vote wraca do maila i Telegrama.

## Refresh co 30 dni

Cookie `cf_clearance` wygasa po 30 dniach lub gdy WAF wykryje podejrzaną
aktywność. Jeśli zaczyna wracać `403`:

1. Powtórz Kroki 1-5 powyżej (nowa przeglądarka, nowe cookies).
2. Settings → Secrets → SOFASCORE_COOKIES → **Update**.
3. Następny run będzie znów działał.

## Bezpieczeństwo

- Cookies SofaScore to anonimowa sesja przeglądania, NIE konto użytkownika.
  Nawet jeśli wyciekną, ktoś dostanie tylko możliwość anonimowego oglądania
  meczów (jak każdy gość). Brak dostępu do danych osobowych.
- GitHub Secrets są szyfrowane at-rest i nigdy nie są wyświetlane w logach.
- Wartość secret jest czytelna tylko dla workflow tego repo.

## Wyłączenie

Jeśli kiedyś zechcesz wyłączyć SofaScore — usuń secret `SOFASCORE_COOKIES`
albo ustaw `SOFASCORE_GROQ_ESTIMATOR_ENABLED=0` (już domyślnie wyłączone w v7.7).

## Diagnostyka

W logu CI zobaczysz teraz dokładną informację gdzie pada bypass:

- `🍪 SofaScore: zaladowano N manual cookies z SOFASCORE_COOKIES env` — cookies
  z env załadowane OK
- `⚠️ SofaScore: SOFASCORE_COOKIES env wyglada na pusty/nieprawidlowy format`
  — sekret istnieje ale niepoprawny format (sprawdź czy jest `nazwa=wartosc;
  nazwa2=wartosc2`)
- `⚠️ SofaScore DrissionPage: <error>` — DrissionPage warmup (fallback) padl
  konkretnie z tego powodu
