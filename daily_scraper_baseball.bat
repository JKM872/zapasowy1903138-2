@echo off
REM ============================================
REM Daily Scraper - BASEBALL (Experimental)
REM ============================================
REM Osobny workflow baseballowy
REM Pitcher data wymagany do kwalifikacji
REM ============================================

echo.
echo ========================================
echo   BASEBALL SCRAPER (Experimental)
echo ========================================
echo.
echo Start: %date% %time%
echo.

REM Przejdz do katalogu projektu
cd /d "%~dp0"

REM Ustaw kodowanie UTF-8
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

REM Pobierz dzisiejsza date w formacie YYYY-MM-DD
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set TODAY=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%

echo Scrapuje mecze baseballowe na dzien: %TODAY%
echo.

REM Uruchom scraper z baseball + Gemini AI + Forebet + Odds
python scrape_and_notify.py ^
  --date %TODAY% ^
  --sports baseball ^
  --to %EMAIL_TO% ^
  --from-email %EMAIL_FROM% ^
  --password "%EMAIL_PASSWORD%" ^
  --headless ^
  --sort time ^
  --use-gemini ^
  --use-forebet ^
  --use-sofascore ^
  --use-odds

echo.
echo ========================================
echo Zakonczono: %date% %time%
echo ========================================
echo.

REM Zapisz log
echo %date% %time% - Baseball scraping completed >> scraper_log.txt

timeout /t 5 >nul
