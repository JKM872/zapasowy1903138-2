@echo off
REM ============================================
REM Daily Scraper - WSZYSTKIE SPORTY
REM Uruchomienie: 7:00 rano → Email: ~11:00
REM ============================================

echo.
echo ========================================
echo   FLASHSCORE - WSZYSTKIE SPORTY
echo   Email będzie gotowy około 11:00!
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

echo Scrapuję WSZYSTKIE sporty na dzień: %TODAY%
echo To potrwa 2-4 godziny...
echo.

REM Uruchom scraper z WSZYSTKIMI sportami
python scrape_and_notify.py ^
  --date %TODAY% ^
  --sports football basketball volleyball handball rugby hockey tennis ^
  --to jakub.majka.zg@gmail.com ^
  --from-email jakub.majka.zg@gmail.com ^
  --password "vurb tcai zaaq itjx" ^
  --headless ^
  --sort time ^
  --use-forebet ^
  --use-sofascore ^
  --use-odds

echo.
echo ========================================
echo Zakończono: %date% %time%
echo Email wysłany!
echo ========================================
echo.

REM Zapisz log
echo %date% %time% - All sports scraping completed >> scraper_log.txt

REM Poczekaj 5 sekund przed zamknięciem
timeout /t 5 >nul

