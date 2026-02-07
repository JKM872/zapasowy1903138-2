@echo off
REM =========================================================
REM Scraper - PIŁKA RĘCZNA (GOŚCIE)
REM =========================================================

echo.
echo ============================================================
echo  Livesport H2H Scraper - PIŁKA RĘCZNA
echo  TRYB: GOŚCIE (AWAY TEAMS) z >=60%% H2H
echo ============================================================
echo.

REM Ustaw datę (zmień na właściwą)
SET DATE=2025-10-12

echo Data: %DATE%
echo Sport: Piłka ręczna (Handball)
echo Fokus: DRUŻYNY GOŚCI
echo.

python livesport_h2h_scraper.py --mode auto --date %DATE% --sports handball --away-team-focus --headless --use-forebet --use-sofascore

echo.
echo Wyniki: outputs\livesport_h2h_%DATE%_handball_AWAY_FOCUS.csv
echo.
pause

