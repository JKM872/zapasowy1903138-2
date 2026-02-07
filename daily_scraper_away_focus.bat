@echo off
REM ============================================
REM Daily Scraper - WSZYSTKIE SPORTY (AWAY FOCUS)
REM ============================================
REM Automatycznie zbiera mecze gdzie GOŚCIE
REM mają przewagę ≥60% w H2H
REM UWAGA: To może trwać 2-4 godziny!
REM ============================================

echo.
echo ========================================
echo   FLASHSCORE SCRAPER - GOŚCIE (AWAY FOCUS)
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

REM Uruchom scraper z WSZYSTKIMI sportami i flagą --away-team-focus + AI/Forebet
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
echo Zakończono: %date% %time%
echo ========================================
echo.

REM Zapisz log
echo %date% %time% - Scraping AWAY FOCUS completed >> scraper_log.txt

REM Poczekaj 5 sekund przed zamknięciem (aby zobaczyć komunikaty)
timeout /t 5 >nul


