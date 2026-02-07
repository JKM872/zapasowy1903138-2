@echo off
REM =========================================================
REM Scraper - HOKEJ (GOŚCIE)
REM =========================================================

echo.
echo ============================================================
echo  Livesport H2H Scraper - HOKEJ
echo  TRYB: GOŚCIE (AWAY TEAMS) z >=60%% H2H
echo ============================================================
echo.

REM Ustaw datę (zmień na właściwą)
SET DATE=2025-10-12

echo Data: %DATE%
echo Sport: Hokej (Hockey)
echo Fokus: DRUŻYNY GOŚCI
echo.

python livesport_h2h_scraper.py --mode auto --date %DATE% --sports hockey --away-team-focus --headless --use-forebet --use-sofascore

echo.
echo Wyniki: outputs\livesport_h2h_%DATE%_hockey_AWAY_FOCUS.csv
echo.
pause

