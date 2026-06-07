# 🏓 Table Tennis Pipeline — AiScore (HOME / AWAY)

Nowy, **niezależny** pipeline tenisa stołowego, którego źródłem listy meczów,
H2H i formy jest **AiScore** (`https://www.aiscore.com/table-tennis`). Nie
narusza istniejących pipeline'ów innych sportów ani wcześniejszego
`table_tennis_pipeline.py` (SofaScore) — to osobne pliki i osobne workflowy.

## Dlaczego AiScore?

AiScore listuje praktycznie wszystkie mecze tenisa stołowego (w tym amatorskie:
TT Cup, TT Elite, Setka Cup) wraz z bogatą sekcją head-to-head oraz formą
(ogólną i w podziale dom/wyjazd). LiveSport ma ich za mało, a SofaScore służy
tu **wyłącznie** do (obowiązkowego) Fan Vote.

## Reużyte, niezmienione klocki

| Element | Plik | Rola |
|---|---|---|
| Źródło meczów + H2H + forma | `aiscore_scraper.py` | **nowe** |
| Fan Vote (OBOWIĄZKOWY) | `sofascore_scraper.get_sofascore_prediction` | reuse |
| Kursy (best-effort) | `sofascore_scraper` odds API (LV Bet itd.) + Livesport fallback | reuse |
| Scoring (2-way, bez remisu) | `tennis_scoring_engine.TennisScoringEngine` | reuse |
| Bramka kwalifikacji | `qualification_gate.apply_qualification_gate` | reuse |
| E-mail (jak tenis) | `email_notifier.send_email_notification` | reuse |
| Telegram | `telegram_notifier.send_telegram_summary` | reuse |
| Przeglądarka | `livesport_h2h_scraper.start_driver` | reuse |

## Reguły kwalifikacji

1. **H2H ≥ 60%** — faworyt (strona zgodna z `--focus`) musi mieć ≥60% wygranych
   w bezpośrednich meczach z rywalem (min. 3 mecze H2H). *Twardy warunek.*
2. **Fan Vote** — SofaScore Fan Vote musi zostać znaleziony. *Twardy warunek.*
3. **Tylko przyszłe** — mecz nie może być rozpoczęty. *Twardy warunek.*
4. **Kursy** — z **SofaScore** (ten sam event co Fan Vote; SofaScore agreguje
   bukmacherów, m.in. LV Bet, także dla lig amatorskich) — rynek „Full time"
   2-way, parsowany case-insensitive. Fallback: Livesport multi-bukmacher.
   Wzbogacają scoring (EV). Brak kursów **nie** dyskwalifikuje.

> Faworyt liczenia H2H wyznacza `--focus`: `home` → gospodarz, `away` → gość.
> To samo rozróżnienie co `scrape.yml` (home) / `scrape_away.yml` (away).

## HOME vs AWAY — dwa workflowy

| Workflow | `--focus` | Cron (UTC) |
|---|---|---|
| `scrape_table_tennis_aiscore_home.yml` | `home` (gospodarze) | `30 5 * * *` |
| `scrape_table_tennis_aiscore_away.yml` | `away` (goście) | `30 6 * * *` |

Crony są przesunięte, by ograniczyć wyścig push na `main`. Każdy workflow ma
FlareSolverr + Cloudflare WARP (dla SofaScore Fan Vote) oraz race-safe push
(rebase + retry ×6), zgodnie z istniejącym wzorcem.

Pliki wyjściowe nie kolidują (focus w nazwie):

```
results/matches_<DATA>_table_tennis_aiscore_home.json
results/matches_<DATA>_table_tennis_aiscore_away.json
outputs/table_tennis_aiscore_home_<DATA>.csv
outputs/table_tennis_aiscore_away_<DATA>.csv
```

## Uruchomienie lokalne

```bash
python table_tennis_aiscore_pipeline.py --focus home --date 2026-06-05
python table_tennis_aiscore_pipeline.py --focus away --no-email --no-telegram
```

## Testy

```bash
python -m pytest test_aiscore_scraper.py -q
```

Testy weryfikują parser na rzeczywistym fixture (`tests/fixtures/aiscore_tt_h2h.html`):
Szostak wygrał 4/6 H2H z Komorowiczem = 66.7% ≥ 60% → kwalifikuje się, oraz że
brak Fan Vote blokuje kwalifikację.

## ⚠️ Uwaga o weryfikacji live

Parser i bramki przetestowano na zapisanym HTML. Strona listingu AiScore jest
renderowana JS — `list_match_urls` zbiera linki `/table-tennis/match-…` po
załadowaniu strony. Selektory ekstrakcji są odporne (meta + klasy `winText`/
`loserText` + porównanie wyniku), ale realne zachowanie listingu i stron meczów
trzeba potwierdzić przy pierwszym uruchomieniu w GitHub Actions.
