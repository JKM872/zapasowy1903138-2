@echo off
REM =========================================================
REM Quick Launch Script - All Sports (AWAY TEAMS FOCUS)
REM =========================================================
REM Uruchamia scraper dla wszystkich sportów na dzisiejszą datę
REM FOKUS: DRUŻYNY GOŚCI z ≥60% wygranych w H2H
REM 
REM Użycie: 
REM   1. Edytuj DATE poniżej na właściwą datę (YYYY-MM-DD)
REM   2. Kliknij dwukrotnie lub uruchom z konsoli
REM =========================================================

echo.
echo ============================================================
echo  Livesport H2H Scraper - Multi-Sport Edition
echo  TRYB: GOŚCIE (AWAY TEAMS) z przewagą H2H
echo ============================================================
echo.

REM Ustaw datę (zmień na właściwą)
SET DATE=2025-10-12

echo Data: %DATE%
echo Fokus: DRUŻYNY GOŚCI z >=60%% H2H
echo.
echo Uruchamiam scraper dla wszystkich sportów...
echo.

REM Uruchom scraper z flagą --away-team-focus
python livesport_h2h_scraper.py --mode auto --date %DATE% --sports football basketball volleyball handball rugby hockey --away-team-focus --headless --use-forebet --use-sofascore

echo.
echo ============================================================
echo  Gotowe!
echo ============================================================
echo.
echo Wyniki zapisano w katalogu: outputs/
echo Nazwa pliku zawiera sufiks: _AWAY_FOCUS
echo.

pause


