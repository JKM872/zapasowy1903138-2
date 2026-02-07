@echo off
REM =========================================================
REM Quick Launch Script - Football Only
REM =========================================================
REM Uruchamia scraper tylko dla piłki nożnej
REM =========================================================

echo.
echo ============================================================
echo  Livesport H2H Scraper - Football Only
echo ============================================================
echo.

REM Ustaw datę (zmień na właściwą)
SET DATE=2025-10-05

echo Data: %DATE%
echo.
echo Uruchamiam scraper dla pilki noznej...
echo.

REM Uruchom scraper
python livesport_h2h_scraper.py --mode auto --date %DATE% --sports football --headless --use-forebet --use-sofascore

echo.
echo ============================================================
echo  Gotowe!
echo ============================================================
echo.
echo Wyniki zapisano w katalogu: outputs/
echo.

pause

