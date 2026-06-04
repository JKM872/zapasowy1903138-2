# 🏆 World Cup Daily Analysis — pełny pakiet analityczny

Nowa oferta dla użytkowników na **Mistrzostwa Świata 2026** (11 czerwca – 19 lipca).
Codziennie analizuje **każdy** mecz turnieju, wykorzystując **komplet rynków
Pinnacle** dostępnych przez API Livesport — bukmachera o najniższej marży na
rynku, którego kursy najlepiej przybliżają realne prawdopodobieństwo.

## Co analizujemy (rynki Pinnacle)

| Rynek | betType | Co dostajemy |
|-------|---------|--------------|
| 1X2 | `HOME_DRAW_AWAY` | kursy + fair-prob (bez marży) + vig |
| Podwójna szansa | `DOUBLE_CHANCE` | 1X / 12 / X2 |
| Obie strzelą | `BOTH_TEAMS_TO_SCORE` | Tak/Nie + fair-prob |
| Totale goli | `OVER_UNDER` | wszystkie linie (0.5–5.5+), linia główna, rekomendacja |
| Handicap azjatycki | `ASIAN_HANDICAP` | wszystkie linie + linia główna |
| Dokładny wynik | `CORRECT_SCORE` | top 5 scoreline'ów + najprawdopodobniejszy |

Każda pozycja zawiera **kurs otwarcia** i **kierunek ruchu** (UP/DOWN), co
napędza detektor **ruchów linii / "ostrych pieniędzy"** oraz tagi **value-bet**
(porównanie fair-prob Pinnacle z Forebet/SofaScore).

> Rynki niedostępne w tym API dla Pinnacle: `DRAW_NO_BET`, `ODD_EVEN`,
> `HANDICAP`, oraz zakresy połówkowe (`FIRST_HALF`) — zwracają HTTP 400.

## Głęboka analiza pochodna (mało meczów = analizujemy wszystko)

Ponieważ meczów MŚ jest mało, każdy mecz analizujemy maksymalnie głęboko.
Z rynku `CORRECT_SCORE` Pinnacle budujemy **pełny rozkład wyników** i wyliczamy
deterministycznie (moduł `worldcup_extras.py`):

| Sekcja | Co zawiera |
|--------|------------|
| `goal_model.expected_goals` | xG gospodarz / gość / suma |
| `goal_model.outcome_prob` | P(1) / P(X) / P(2) z rozkładu |
| `goal_model.btts_prob` | P(obie strzelą) |
| `goal_model.clean_sheet` | P(czyste konto) dla każdej drużyny |
| `goal_model.derived_totals` | P(Over/Under) dla linii 0.5–4.5 |
| `who_scores_first` | 1 / Nikt / 2 (z modelu goli) |
| `kelly` | kryterium Kelly'ego, EV, **value coefficient**, sugerowana stawka |

## Dodatkowe elementy z Forebet + pogoda

Czego nie ma w API Pinnacle, a jest w ofercie MŚ — dociągane best-effort:

| Element | Źródło | Pole |
|---------|--------|------|
| Rożne (Under/Over 9.5) | Forebet `/corners` | `forebet_extras.corners` |
| Kartki (Under/Over 4.5) | Forebet `/cards` | `forebet_extras.cards` |
| Kto strzeli pierwszy | Forebet `/scorers` | `forebet_extras.who_scores_first` |
| TOP trends World Cup | Forebet | `forebet_extras.trends` |
| Pogoda | Open-Meteo (bez klucza) | `weather` |
| SofaScore Fan Vote | SofaScore (już w pipeline) | `sofascore` |

## Architektura

```
worldcup_pipeline.py        # orkiestrator dzienny (CLI)
 ├─ livesport_h2h_scraper    # zbiera mecze MŚ (filtr ligi) + H2H/forma + SofaScore
 ├─ pinnacle_full_odds.py    # PinnacleFullOdds — pełny pakiet rynków + vig-removal
 ├─ worldcup_analyzer.py     # analyze_match() — value, sygnały, werdykt PL
 │   └─ worldcup_extras.py   # goal_model, who_scores_first, Kelly/value
 ├─ worldcup_forebet_extras  # rożne, kartki, scorers, TOP trends (Forebet)
 ├─ Open-Meteo               # pogoda (bez klucza)
 └─ ai_prediction_engine     # werdykt AI (Ultra PRO) per mecz
        ↓
results/worldcup_<date>.json  # commitowane do repo
        ↓
api_server.py  GET /api/worldcup        # serwowane do frontendu
               GET /api/worldcup/dates
```

## Uruchomienie lokalne

```bash
# Cały dzień turnieju
python worldcup_pipeline.py --date 2026-06-11 --headless

# Szybki test (3 mecze, bez Supabase)
python worldcup_pipeline.py --date 2026-06-11 --max-matches 3 --no-supabase
```

Pojedynczy mecz, surowe rynki:

```bash
python pinnacle_full_odds.py "https://www.livesport.com/pl/mecz/.../?mid=XXXX"
```

## Automatyzacja (GitHub Actions)

`.github/workflows/worldcup_analysis.yml`:

- harmonogram: codziennie **09:00 UTC (11:00 CEST)**,
- ręczne `workflow_dispatch` z polami `date` i `max_matches`,
- FlareSolverr + Cloudflare WARP (jak `scrape.yml`),
- commit `results/worldcup_<date>.json` z `[skip ci]`.

Wymaga tych samych sekretów co `scrape.yml` (`SUPABASE_*`, `GEMINI_API_KEY`,
`SOFASCORE_COOKIES`). API Pinnacle/Livesport **nie wymaga klucza**.

## API

```http
GET /api/worldcup?date=2026-06-11        # pełny pakiet dnia (lub najnowszy)
GET /api/worldcup?value=true             # tylko mecze z wykrytym value-betem
GET /api/worldcup?search=brazil          # filtr po drużynie/lidze
GET /api/worldcup/dates                  # dostępne dni analizy
```

Każdy mecz w odpowiedzi ma blok `worldcup` z polami: `match_winner`, `totals`,
`btts`, `asian_handicap`, `correct_score`, `double_chance`, `signals`,
`value_bets`, `goal_model`, `who_scores_first`, `kelly`, `forebet_extras`,
`weather`, `verdict` oraz `markets_count`. Statystyki dzienne (`stats`)
zawierają liczniki: `withValueBets`, `withMarketSignals`, `withKellyValue`,
`withForebetExtras`.

## Testy

```bash
python -m pytest test_worldcup_extras.py test_worldcup_analyzer.py -v
```

Testy są deterministyczne (bez sieci) — używają nagranego pakietu rynków
Pinnacle, więc weryfikują model goli, Kelly, who-scores-first, sygnały ruchu
linii i werdykt bez zależności od dostępności zewnętrznych API.
