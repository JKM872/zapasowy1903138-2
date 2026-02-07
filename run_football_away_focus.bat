@echo off
REM =========================================================
REM Quick Launch Script - Football Only (AWAY TEAMS FOCUS)
REM =========================================================
REM Uruchamia scraper TYLKO dla piłki nożnej
REM FOKUS: DRUŻYNY GOŚCI z ≥60% wygranych w H2H
REM 
REM Użycie: 
REM   1. Edytuj DATE poniżej na właściwą datę (YYYY-MM-DD)
REM   2. Kliknij dwukrotnie lub uruchom z konsoli
REM =========================================================

echo.
echo ============================================================
echo  Livesport H2H Scraper - Football Edition
echo  TRYB: GOŚCIE (AWAY TEAMS) z przewagą H2H
echo ============================================================
echo.

REM Ustaw datę (zmień na właściwą)
SET DATE=2025-10-12

echo Data: %DATE%
echo Sport: Piłka nożna
echo Fokus: DRUŻYNY GOŚCI z >=60%% H2H
echo.
echo Uruchamiam scraper...
echo.

REM Uruchom scraper z flagą --away-team-focus
python livesport_h2h_scraper.py --mode auto --date %DATE% --sports football --away-team-focus --headless --use-forebet --use-sofascore

echo.
echo ============================================================
echo  Gotowe!
echo ============================================================
echo.
echo Wyniki zapisano w katalogu: outputs/
echo Nazwa pliku: livesport_h2h_%DATE%_football_AWAY_FOCUS.csv
echo.

pause


