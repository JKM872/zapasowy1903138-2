@echo off
REM =========================================================
REM Scraper - SIATKÓWKA (GOŚCIE) + EMAIL
REM =========================================================

echo.
echo ============================================================
echo  Livesport H2H Scraper - SIATKÓWKA + EMAIL
echo  TRYB: GOŚCIE (AWAY TEAMS) z >=60%% H2H
echo ============================================================
echo.

REM Ustaw datę (zmień na właściwą)
SET DATE=2025-10-12

echo Data: %DATE%
echo Sport: Siatkówka (Volleyball)
echo Fokus: DRUŻYNY GOŚCI + PRZEWAGA FORMY
echo Email: jakub.majka.zg@gmail.com
echo.

python scrape_and_notify.py --date %DATE% --sports volleyball --to jakub.majka.zg@gmail.com --from-email jakub.majka.zg@gmail.com --password "vurb tcai zaaq itjx" --away-team-focus --only-form-advantage --headless --use-forebet --use-sofascore --use-odds

echo.
echo ============================================================
echo  Gotowe! Email wysłany.
echo ============================================================
echo.
pause

