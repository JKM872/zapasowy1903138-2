@echo off
REM ========================================================================
REM DAILY SCRAPER - TRYB PREMIUM (🔥💰)
REM ========================================================================
REM Ten skrypt automatycznie scrapuje dzisiejsze mecze i wysyła emailem
REM TYLKO NAJLEPSZE MECZE:
REM   🔥 Z PRZEWAGĄ FORMY gospodarzy
REM   💰 Z KURSAMI bukmacherskimi
REM 
REM To najbardziej precyzyjny tryb - tylko TOP mecze z pełnymi danymi!
REM ========================================================================

echo.
echo ========================================================================
echo SCRAPER - TRYB PREMIUM (🔥 FORMA + 💰 KURSY)
echo ========================================================================
echo.

REM Pobierz dzisiejszą datę w formacie YYYY-MM-DD
for /f "tokens=1-3 delims=/ " %%a in ('date /t') do (
    set DATE=%%c-%%b-%%a
)

REM Jeśli format daty jest DD-MM-YYYY, zmień na YYYY-MM-DD
for /f "tokens=1-3 delims=.-/ " %%a in ("%DATE%") do (
    if %%a GTR 31 (
        set DATE=%%a-%%b-%%c
    ) else (
        set DATE=%%c-%%b-%%a
    )
)

echo Data: %DATE%
echo.

REM ========================================================================
REM KONFIGURACJA - EDYTUJ TE WARTOŚCI!
REM ========================================================================

REM Adres email odbiorcy
set TO_EMAIL=twoj@email.com

REM Adres email nadawcy (Gmail)
set FROM_EMAIL=twoj@gmail.com

REM Hasło aplikacji Gmail (https://myaccount.google.com/apppasswords)
set PASSWORD=twoje_app_password

REM Sporty do scrapowania (football basketball handball volleyball)
set SPORTS=football basketball

REM ========================================================================
REM URUCHOMIENIE SCRAPERA
REM ========================================================================

echo Scrapuje dzisiejsze mecze dla: %SPORTS%
echo Filtruje:
echo   🔥 Tylko mecze z PRZEWAGĄ FORMY
echo   💰 Tylko mecze z KURSAMI
echo.
echo To najbardziej precyzyjny tryb!
echo.

python scrape_and_notify.py ^
    --date %DATE% ^
    --sports %SPORTS% ^
    --to %TO_EMAIL% ^
    --from-email %FROM_EMAIL% ^
    --password "%PASSWORD%" ^
    --provider gmail ^
    --headless ^
    --only-form-advantage ^
    --skip-no-odds ^
    --use-forebet ^
    --use-sofascore ^
    --use-odds ^
    --use-gemini

echo.
echo ========================================================================
echo ZAKOŃCZONO!
echo ========================================================================
pause




