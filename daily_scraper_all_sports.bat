@echo off
REM ============================================
REM Daily Scraper - WSZYSTKIE SPORTY
REM ============================================
REM UWAGA: To może trwać 2-4 godziny!
REM ============================================

echo.
echo ========================================
echo   FLASHSCORE SCRAPER - WSZYSTKIE SPORTY
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

echo Scrapuję mecze na dzień: %TODAY%
echo.

REM Uruchom scraper z WSZYSTKIMI sportami + Gemini AI + Forebet + Odds
python scrape_and_notify.py ^
  --date %TODAY% ^
  --sports football basketball volleyball handball rugby hockey tennis ^
  --to jakub.majka.zg@gmail.com ^
  --from-email jakub.majka.zg@gmail.com ^
  --password "vurb tcai zaaq itjx" ^
  --headless ^
  --sort time ^
  --use-gemini ^
  --use-forebet ^
  --use-sofascore ^
  --use-odds

echo.
echo ========================================
echo Zakończono: %date% %time%
echo ========================================
echo.

REM Zapisz log
echo %date% %time% - Scraping completed >> scraper_log.txt

REM Poczekaj 5 sekund przed zamknięciem (aby zobaczyć komunikaty)
timeout /t 5 >nul

