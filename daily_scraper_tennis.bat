@echo off
REM ============================================
REM Daily Scraper - TYLKO TENIS
REM ============================================
REM Scraping tenisowych meczów z pełną analizą V3
REM ============================================

echo.
echo ========================================
echo   FLASHSCORE SCRAPER - TENIS 🎾
echo ========================================
echo.
echo Start: %date% %time%
echo.

REM Przejdź do katalogu projektu (automatycznie z lokalizacji .bat)
cd /d "%~dp0"

REM Ustaw kodowanie UTF-8
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

REM Pobierz dzisiejszą datę w formacie YYYY-MM-DD
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set TODAY=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%

echo Scrapuję mecze tenisowe na dzień: %TODAY%
echo System: Tennis V3 Enhanced
echo.

REM Uruchom scraper z TYLKO tenisem
python scrape_and_notify.py ^
  --date %TODAY% ^
  --sports tennis ^
  --to jakub.majka.zg@gmail.com ^
  --from-email jakub.majka.zg@gmail.com ^
  --password "vurb tcai zaaq itjx" ^
  --headless ^
  --sort time ^
  --use-forebet ^
  --use-sofascore

echo.
echo ========================================
echo Zakończono: %date% %time%
echo ========================================
echo.
echo Sprawdź email oraz katalog outputs/
echo Plik: livesport_h2h_%TODAY%_tennis_EMAIL.csv
echo.

REM Zapisz log
echo %date% %time% - Tennis scraping completed >> scraper_log.txt

REM Poczekaj 5 sekund przed zamknięciem
timeout /t 5 >nul


