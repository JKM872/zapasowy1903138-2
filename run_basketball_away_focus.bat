@echo off
REM =========================================================
REM Scraper - KOSZYKÓWKA (GOŚCIE)
REM =========================================================

echo.
echo ============================================================
echo  Livesport H2H Scraper - KOSZYKÓWKA
echo  TRYB: GOŚCIE (AWAY TEAMS) z >=60%% H2H
echo ============================================================
echo.

REM Ustaw datę (zmień na właściwą)
SET DATE=2025-10-12

echo Data: %DATE%
echo Sport: Koszykówka (Basketball)
echo Fokus: DRUŻYNY GOŚCI
echo.

python livesport_h2h_scraper.py --mode auto --date %DATE% --sports basketball --away-team-focus --headless --use-forebet --use-sofascore

echo.
echo Wyniki: outputs\livesport_h2h_%DATE%_basketball_AWAY_FOCUS.csv
echo.
pause

