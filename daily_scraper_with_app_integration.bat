@echo off
REM ============================================
REM Daily Scraper - Z INTEGRACJĄ DO APLIKACJI UI
REM ============================================
REM Scraper automatycznie wysyła dane do aplikacji
REM ============================================

echo.
echo ========================================
echo   FLASHSCORE SCRAPER + APP INTEGRATION
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

REM ===== KONFIGURACJA =====
REM Zmień te wartości na swoje!

SET APP_URL=http://localhost:3000
SET APP_API_KEY=
SET SPORTS=football basketball
SET EMAIL_TO=jakub.majka.zg@gmail.com
SET EMAIL_FROM=jakub.majka.zg@gmail.com
SET EMAIL_PASSWORD=vurb tcai zaaq itjx

REM ========================

echo Scrapuję mecze na dzień: %TODAY%
echo Sporty: %SPORTS%
echo Aplikacja UI: %APP_URL%
echo.

REM Uruchom scraper z integracją do aplikacji
python scrape_and_notify.py ^
  --date %TODAY% ^
  --sports %SPORTS% ^
  --to %EMAIL_TO% ^
  --from-email %EMAIL_FROM% ^
  --password "%EMAIL_PASSWORD%" ^
  --headless ^
  --sort time ^
  --use-forebet ^
  --use-sofascore ^
  --use-odds ^
  --app-url %APP_URL%

echo.
echo ========================================
echo Zakończono: %date% %time%
echo ========================================
echo.
echo Dane wysłane do:
echo   - Email: %EMAIL_TO%
echo   - Aplikacja: %APP_URL%
echo.

REM Zapisz log
echo %date% %time% - Scraping with app integration completed >> scraper_log.txt

REM Poczekaj 5 sekund przed zamknięciem
timeout /t 5 >nul







