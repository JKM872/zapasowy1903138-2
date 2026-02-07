@echo off
REM =========================================================
REM Quick Launch Script - Tennis Only
REM =========================================================
REM Szybkie uruchomienie scrapera dla tenisa
REM 
REM Użycie: 
REM   Kliknij dwukrotnie lub uruchom z konsoli
REM =========================================================

echo.
echo ============================================================
echo  🎾 Livesport H2H Scraper - TENNIS EDITION
echo ============================================================
echo  System: Tennis V3 Enhanced
echo  Features: Adaptive thresholds, Tournament weights, 
echo            Win probability, Fatigue detection
echo ============================================================
echo.

REM Pobierz dzisiejszą datę
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set DATE=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%

echo Data: %DATE%
echo.
echo Uruchamiam scraper dla tenisa...
echo.

REM Uruchom scraper
python scrape_and_notify.py ^
  --date %DATE% ^
  --sports tennis ^
  --to jakub.majka.zg@gmail.com ^
  --from-email jakub.majka.zg@gmail.com ^
  --password "vurb tcai zaaq itjx" ^
  --headless ^
  --sort time ^
  --use-forebet ^
  --use-sofascore

echo.
echo ============================================================
echo  ✅ Gotowe!
echo ============================================================
echo.
echo Wyniki zapisano w:
echo   - Email: jakub.majka.zg@gmail.com
echo   - Plik: outputs\livesport_h2h_%DATE%_tennis_EMAIL.csv
echo.

pause


