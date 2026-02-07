@echo off
REM =========================================================
REM Quick Launch Script - All Sports
REM =========================================================
REM Uruchamia scraper dla wszystkich sportów na dzisiejszą datę
REM 
REM Użycie: 
REM   1. Edytuj DATE poniżej na właściwą datę (YYYY-MM-DD)
REM   2. Kliknij dwukrotnie lub uruchom z konsoli
REM =========================================================

echo.
echo ============================================================
echo  Livesport H2H Scraper - Multi-Sport Edition
echo ============================================================
echo.

REM Ustaw datę (zmień na właściwą)
SET DATE=2025-10-05

echo Data: %DATE%
echo.
echo Uruchamiam scraper dla wszystkich sportów...
echo.

REM Uruchom scraper
python livesport_h2h_scraper.py --mode auto --date %DATE% --sports football basketball volleyball handball rugby hockey --headless --use-forebet --use-sofascore

echo.
echo ============================================================
echo  Gotowe!
echo ============================================================
echo.
echo Wyniki zapisano w katalogu: outputs/
echo.

pause

