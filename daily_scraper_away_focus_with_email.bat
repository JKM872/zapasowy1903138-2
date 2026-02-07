@echo off
REM ============================================
REM Daily Scraper - GOŚCIE (AWAY FOCUS) + EMAIL
REM ============================================
REM Automatycznie zbiera mecze gdzie GOŚCIE
REM mają przewagę ≥60% w H2H i wysyła email
REM UWAGA: To może trwać 2-4 godziny!
REM ============================================

echo.
echo ========================================
echo   FLASHSCORE SCRAPER - GOŚCIE + EMAIL
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
echo Tryb: GOŚCIE (AWAY TEAMS) z >=60%% H2H
echo.

REM UWAGA: Musisz stworzyć wersję scrape_and_notify.py z obsługą --away-team-focus
REM lub użyć bezpośrednio scrapera i potem wysłać email osobno

echo ========================================
echo UWAGA: Dla trybu z emailem
echo ========================================
echo.
echo Najpierw uruchamiam scraper (bez email):
echo.

python livesport_h2h_scraper.py ^
  --mode auto ^
  --date %TODAY% ^
  --sports football basketball volleyball handball rugby hockey ^
  --away-team-focus ^
  --headless ^
  --use-gemini ^
  --use-forebet ^
  --use-sofascore

echo.
echo ========================================
echo Scraping zakończony!
echo ========================================
echo.
echo Aby wysłać email, użyj narzędzia do wysyłania
echo z pliku CSV: outputs\livesport_h2h_%TODAY%_AWAY_FOCUS.csv
echo.

REM Zapisz log
echo %date% %time% - Scraping AWAY FOCUS completed >> scraper_log.txt

pause


