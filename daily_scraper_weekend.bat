@echo off
REM ============================================
REM Weekend Scraper - NAJPOPULARNIEJSZE SPORTY
REM ============================================
REM Football + Basketball + Tennis (ok. 1 godzina)
REM ============================================

echo.
echo ========================================
echo   FLASHSCORE SCRAPER - WEEKEND
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

echo Scrapuję najpopularniejsze sporty na dzień: %TODAY%
echo.

REM Uruchom scraper z popularnymi sportami
python scrape_and_notify.py ^
  --date %TODAY% ^
  --sports football basketball volleyball ^
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
echo ========================================
echo.

REM Zapisz log
echo %date% %time% - Weekend scraping completed >> scraper_log.txt

REM Poczekaj 5 sekund przed zamknięciem
timeout /t 5 >nul

