"""
SKRYPT AUTOMATYCZNY: Scrapuje mecze i wysyła powiadomienie email

FLOW:
1. Forebet - predykcje (filtrowanie meczów z przewagą)
2. SofaScore - głosy fanów
3. Livesport - H2H + forma
4. FlashScore - kursy bukmacherskie
5. Email/AI - powiadomienie
"""

import argparse
import os
import sys
import json
from datetime import datetime
from livesport_h2h_scraper import start_driver, get_match_links_from_day, process_match, process_match_tennis, detect_sport_from_url
from email_notifier import send_email_notification
from app_integrator import AppIntegrator, create_integrator_from_config
import pandas as pd
import time

# Import FlashScore odds scraper
try:
    from flashscore_odds_scraper import FlashScoreOddsScraper
    FLASHSCORE_AVAILABLE = True
except ImportError:
    FLASHSCORE_AVAILABLE = False
    print("⚠️ flashscore_odds_scraper.py not found - odds will not be fetched")


def scrape_and_send_email(
    date: str,
    sports: list,
    to_email: str,
    from_email: str,
    password: str,
    provider: str = 'gmail',
    headless: bool = True,
    max_matches: int = None,
    sort_by: str = 'time',
    app_url: str = None,
    app_api_key: str = None,
    only_form_advantage: bool = False,
    skip_no_odds: bool = False,
    away_team_focus: bool = False,
    use_forebet: bool = False,
    use_sofascore: bool = False,
    use_odds: bool = False,
    use_gemini: bool = False
):
    """
    Scrapuje mecze i automatycznie wysyła email z wynikami
    
    NOWY FLOW (jeśli włączone):
    1. Forebet → predykcje i filtrowanie
    2. SofaScore → głosy fanów  
    3. Livesport → H2H + forma
    4. FlashScore → kursy bukmacherskie
    5. Email → powiadomienie
    
    Args:
        date: Data w formacie YYYY-MM-DD
        sports: Lista sportów (np. ['football', 'basketball'])
        to_email: Email odbiorcy
        from_email: Email nadawcy
        password: Hasło email
        provider: 'gmail', 'outlook', lub 'yahoo'
        headless: Czy uruchomić w trybie headless
        max_matches: Opcjonalnie: limit meczów (dla testów)
        sort_by: Sortowanie: 'time' (godzina), 'wins' (wygrane), 'team' (alfabetycznie)
        only_form_advantage: Wysyłaj tylko mecze z przewagą formy gospodarzy (🔥)
        skip_no_odds: Pomijaj mecze bez kursów bukmacherskich (💰)
        away_team_focus: Szukaj meczów gdzie GOŚCIE mają ≥60% H2H (zamiast gospodarzy) (🏃)
        use_odds: Pobieraj kursy z FlashScore (💰)
    """
    
    print("="*70)
    print("🤖 AUTOMATYCZNY SCRAPING + POWIADOMIENIE EMAIL")
    print("="*70)
    print(f"📅 Data: {date}")
    print(f"⚽ Sporty: {', '.join(sports)}")
    print(f"📧 Email do: {to_email}")
    print(f"🔧 Provider: {provider}")
    if away_team_focus:
        print(f"🏃 TRYB: Fokus na drużynach GOŚCI (away teams) ≥60% H2H")
    if only_form_advantage:
        print(f"🔥 TRYB: Tylko mecze z PRZEWAGĄ FORMY {'gości' if away_team_focus else 'gospodarzy'}")
    if skip_no_odds:
        print(f"💰 TRYB: Pomijam mecze BEZ KURSÓW bukmacherskich")
    if use_odds:
        print(f"💰 TRYB: Pobieranie kursów z FlashScore")
    if use_forebet:
        print(f"🎯 TRYB: Pobieranie predykcji z Forebet")
    if use_gemini:
        print(f"🤖 TRYB: Analiza Gemini AI")
    if max_matches:
        print(f"⚠️  TRYB TESTOWY: Limit {max_matches} meczów")
    print("="*70)
    
    # 🔥 FOREBET PRE-FETCH: Załaduj HTML dla wszystkich sportów NA POCZĄTKU
    # To zapobiega wielokrotnym wywołaniom FlareSolverr dla 2000 meczów
    if use_forebet:
        try:
            from forebet_scraper import prefetch_forebet_html
            print(f"\n🔥 FOREBET PREFETCH: Ładuję HTML dla {len(sports)} sportów...")
            for sport in sports:
                prefetch_forebet_html(sport, date)
            print("✅ Forebet cache załadowany!\n")
        except Exception as e:
            print(f"⚠️ Forebet prefetch error: {e}\n")
    
    driver = start_driver(headless=headless)
    
    try:
        # KROK 1: Zbierz linki
        print("\n🔍 KROK 1/3: Zbieranie linków do meczów...")
        urls = get_match_links_from_day(driver, date, sports=sports, leagues=None)
        print(f"✅ Znaleziono {len(urls)} meczów")
        
        if max_matches and len(urls) > max_matches:
            urls = urls[:max_matches]
            print(f"⚠️  Ograniczono do {max_matches} meczów (tryb testowy)")
        
        # KROK 2: Przetwórz mecze
        print(f"\n🔄 KROK 2/3: Przetwarzanie {len(urls)} meczów...")
        print("="*70)
        
        rows = []
        qualifying_count = 0
        RESTART_INTERVAL = 40  # Restart Chrome co 40 meczów (zmniejszone z 80 dla stabilności)
        CHECKPOINT_INTERVAL = 30  # Zapisz checkpoint co 30 meczów (bezpieczeństwo danych)
        
        # Przygotuj nazwę pliku
        sport_suffix = '_'.join(sports) if len(sports) <= 2 else 'multi'
        if away_team_focus:
            outfn = f'outputs/livesport_h2h_{date}_{sport_suffix}_AWAY_FOCUS_EMAIL.csv'
        else:
            outfn = f'outputs/livesport_h2h_{date}_{sport_suffix}_EMAIL.csv'
        os.makedirs('outputs', exist_ok=True)
        
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}] Przetwarzam...")
            
            # RETRY LOGIC - 3 próby przy błędzie połączenia
            max_retries = 3
            retry_count = 0
            success = False
            
            while retry_count < max_retries and not success:
                try:
                    # Wykryj sport z URL (tennis ma '/tenis/' w URLu)
                    is_tennis = '/tenis/' in url.lower() or 'tennis' in url.lower()
                    
                    if is_tennis:
                        # Użyj dedykowanej funkcji dla tenisa (ADVANCED)
                        info = process_match_tennis(url, driver)
                        rows.append(info)
                        
                        if info['qualifies']:
                            qualifying_count += 1
                            player_a_wins = info['home_wins_in_h2h_last5']
                            player_b_wins = info.get('away_wins_in_h2h', 0)
                            advanced_score = info.get('advanced_score', 0)
                            favorite = info.get('favorite', 'unknown')
                            
                            # Określ faworyta
                            if favorite == 'player_a':
                                fav_name = info['home_team']
                            elif favorite == 'player_b':
                                fav_name = info['away_team']
                            else:
                                fav_name = "Równi"
                            
                            print(f"   ✅ KWALIFIKUJE! {info['home_team']} vs {info['away_team']}")
                            print(f"      Faworytem: {fav_name} (Score: {advanced_score:.1f}/100)")
                        else:
                            player_a_wins = info['home_wins_in_h2h_last5']
                            player_b_wins = info.get('away_wins_in_h2h', 0)
                            advanced_score = info.get('advanced_score', 0)
                            print(f"   ❌ Nie kwalifikuje (Score: {advanced_score:.1f}/100, H2H: {player_a_wins}-{player_b_wins})")
                        
                        success = True  # Sukces, wyjdź z retry loop
                    
                    else:
                        # Sporty drużynowe
                        current_sport = detect_sport_from_url(url)
                        info = process_match(url, driver, away_team_focus=away_team_focus,
                                           use_forebet=use_forebet, use_gemini=use_gemini, 
                                           use_sofascore=use_sofascore, use_flashscore=use_odds,
                                           sport=current_sport)
                        rows.append(info)
                        
                        if info['qualifies']:
                            qualifying_count += 1
                            h2h_count = info.get('h2h_count', 0)
                            win_rate = info.get('win_rate', 0.0)
                            home_form = info.get('home_form', [])
                            away_form = info.get('away_form', [])
                            
                            home_form_str = '-'.join(home_form) if home_form else 'N/A'
                            away_form_str = '-'.join(away_form) if away_form else 'N/A'
                            
                            # Wybierz co pokazać w zależności od trybu
                            if away_team_focus:
                                wins_count = info.get('away_wins_in_h2h_last5', 0)
                                focused_team = info['away_team']
                            else:
                                wins_count = info['home_wins_in_h2h_last5']
                                focused_team = info['home_team']
                            
                            print(f"   ✅ KWALIFIKUJE! {info['home_team']} vs {info['away_team']}")
                            print(f"      Fokus: {focused_team}")
                            print(f"      H2H: {wins_count}/{h2h_count} ({win_rate*100:.0f}%)")
                            if home_form or away_form:
                                print(f"      Forma: {info['home_team']} [{home_form_str}] | {info['away_team']} [{away_form_str}]")
                        else:
                            h2h_count = info.get('h2h_count', 0)
                            win_rate = info.get('win_rate', 0.0)
                            if h2h_count > 0:
                                if away_team_focus:
                                    wins_count = info.get('away_wins_in_h2h_last5', 0)
                                else:
                                    wins_count = info['home_wins_in_h2h_last5']
                                print(f"   ❌ Nie kwalifikuje ({wins_count}/{h2h_count} = {win_rate*100:.0f}%)")
                            else:
                                print(f"   ⚠️  Brak H2H")
                        
                        success = True  # Sukces, wyjdź z retry loop
                    
                except (ConnectionResetError, ConnectionError, Exception) as e:
                    retry_count += 1
                    if retry_count < max_retries:
                        print(f"   ⚠️  Błąd połączenia (próba {retry_count}/{max_retries}): {str(e)[:100]}")
                        print(f"   🔄 Restartowanie przeglądarki i ponowienie próby...")
                        try:
                            driver.quit()
                        except:
                            pass
                        time.sleep(3)
                        driver = start_driver(headless=headless)
                    else:
                        print(f"   ❌ Błąd po {max_retries} próbach: {str(e)[:100]}")
                        print(f"   ⏭️  Pomijam ten mecz i kontynuuję...")
            
            # CHECKPOINT - zapisz co 30 meczów (bezpieczeństwo danych!)
            if i % CHECKPOINT_INTERVAL == 0 and len(rows) > 0:
                print(f"\n💾 CHECKPOINT: Zapisywanie postępu ({i}/{len(urls)} meczów)...")
                try:
                    df_checkpoint = pd.DataFrame(rows)
                    if 'h2h_last5' in df_checkpoint.columns:
                        df_checkpoint['h2h_last5'] = df_checkpoint['h2h_last5'].apply(lambda x: str(x) if x else '')
                    df_checkpoint.to_csv(outfn, index=False, encoding='utf-8-sig')
                    print(f"   ✅ Checkpoint zapisany! ({len(rows)} meczów, {qualifying_count} kwalifikujących)")
                except Exception as e:
                    print(f"   ⚠️  Błąd zapisu checkpointu: {e}")
            
            # AUTO-RESTART przeglądarki co N meczów (zapobiega crashom)
            if i % RESTART_INTERVAL == 0 and i < len(urls):
                print(f"\n🔄 AUTO-RESTART: Restartowanie przeglądarki po {i} meczach...")
                print(f"   ✅ Przetworzone dane ({len(rows)} meczów) są bezpieczne w pamięci i na dysku!")
                try:
                    driver.quit()
                    time.sleep(2)
                    driver = start_driver(headless=headless)
                    print(f"   ✅ Przeglądarka zrestartowana! Kontynuuję od meczu {i+1}...\n")
                except Exception as e:
                    print(f"   ⚠️  Błąd restartu: {e}")
                    driver = start_driver(headless=headless)
            
            # Rate limiting
            elif i < len(urls):
                time.sleep(1.5)
        
        # Zapisz finalne wyniki (plik już istnieje jeśli były checkpointy)
        print("\n💾 Zapisywanie finalnych wyników...")
        
        df = pd.DataFrame(rows)
        if 'h2h_last5' in df.columns:
            df['h2h_last5'] = df['h2h_last5'].apply(lambda x: str(x) if x else '')
        
        df.to_csv(outfn, index=False, encoding='utf-8-sig')
        print(f"✅ Zapisano do: {outfn}")
        
        # Zapisz przewidywania do JSON (dla późniejszej weryfikacji)
        if qualifying_count > 0:
            predictions_file = outfn.replace('.csv', '_predictions.json')
            qualifying_rows = [r for r in rows if r.get('qualifies', False)]
            
            with open(predictions_file, 'w', encoding='utf-8') as f:
                json.dump(qualifying_rows, f, ensure_ascii=False, indent=2)
            print(f"✅ Przewidywania zapisane do: {predictions_file}")
        
        # KROK 2.5: Pobierz kursy z FlashScore (tylko dla kwalifikujących się meczów)
        if use_odds and FLASHSCORE_AVAILABLE and qualifying_count > 0:
            print(f"\n💰 KROK 2.5/4: Pobieranie kursów z FlashScore...")
            print("="*70)
            
            odds_scraper = FlashScoreOddsScraper(headless=False)
            odds_fetched = 0
            
            for row in rows:
                if row.get('qualifies', False):
                    try:
                        home_team = row.get('home_team', '')
                        away_team = row.get('away_team', '')
                        current_sport = detect_sport_from_url(row.get('url', ''))
                        
                        odds_result = odds_scraper.get_odds(
                            home_team=home_team,
                            away_team=away_team,
                            sport=current_sport
                        )
                        
                        if odds_result.get('odds_found'):
                            row['home_odds'] = odds_result.get('home_odds')
                            row['draw_odds'] = odds_result.get('draw_odds')
                            row['away_odds'] = odds_result.get('away_odds')
                            row['odds_source'] = odds_result.get('odds_source')
                            odds_fetched += 1
                            print(f"   ✅ {home_team} vs {away_team}: {row['home_odds']}/{row['draw_odds']}/{row['away_odds']}")
                        else:
                            row['home_odds'] = None
                            row['draw_odds'] = None
                            row['away_odds'] = None
                            row['odds_source'] = None
                            print(f"   ⚠️ {home_team} vs {away_team}: Kursy nie znalezione")
                        
                    except Exception as e:
                        print(f"   ❌ Błąd pobierania kursów: {e}")
                        row['home_odds'] = None
                        row['draw_odds'] = None
                        row['away_odds'] = None
            
            print(f"\n   📊 Pobrano kursy dla {odds_fetched}/{qualifying_count} meczów")
            
            # Zapisz ponownie CSV z kursami
            df = pd.DataFrame(rows)
            if 'h2h_last5' in df.columns:
                df['h2h_last5'] = df['h2h_last5'].apply(lambda x: str(x) if x else '')
            df.to_csv(outfn, index=False, encoding='utf-8-sig')
            print(f"   ✅ CSV zaktualizowany o kursy: {outfn}")
        
        # Podsumowanie scrapingu
        print("\n📊 PODSUMOWANIE SCRAPINGU:")
        print(f"   Przetworzono: {len(rows)} meczów")
        print(f"   Kwalifikujących się: {qualifying_count}")
        if rows:
            percent = (qualifying_count / len(rows)) * 100
            print(f"   Procent: {percent:.1f}%")
        
        # KROK 3: Wyślij email (tylko jeśli są kwalifikujące się mecze)
        if qualifying_count > 0:
            print(f"\n📧 KROK 3/4: Wysyłanie powiadomienia email...")
            print("="*70)
            
            # Buduj tytuł emaila dynamicznie
            subject_parts = []
            if only_form_advantage:
                subject_parts.append("🔥 PRZEWAGA FORMY")
            if skip_no_odds:
                subject_parts.append("💰 Z KURSAMI")
            
            if subject_parts:
                subject = f"Mecze ({' + '.join(subject_parts)}) - {date}"
            else:
                subject = f"🏆 {qualifying_count} kwalifikujących się meczów - {date}"
            
            send_email_notification(
                csv_file=outfn,
                to_email=to_email,
                from_email=from_email,
                password=password,
                provider=provider,
                subject=subject,
                sort_by=sort_by,
                only_form_advantage=only_form_advantage,
                skip_no_odds=skip_no_odds
            )
            
            print("\n✅ SUKCES! Email wysłany.")
        else:
            # Komunikat o braku meczów
            msg_parts = []
            if only_form_advantage:
                msg_parts.append("PRZEWAGĄ FORMY")
            if skip_no_odds:
                msg_parts.append("KURSAMI")
            
            if msg_parts:
                print(f"\n⚠️  Brak kwalifikujących się meczów z {' i '.join(msg_parts)} - email nie został wysłany")
            else:
                print(f"\n⚠️  Brak kwalifikujących się meczów - email nie został wysłany")
        
        # KROK 4: Wyślij dane do aplikacji UI (jeśli skonfigurowane)
        if app_url:
            print(f"\n🔗 KROK 4/4: Wysyłanie danych do aplikacji UI...")
            print("="*70)
            
            try:
                # Utwórz integrator
                integrator = AppIntegrator(app_url=app_url, api_key=app_api_key)
                
                # Testuj połączenie
                if integrator.test_connection():
                    # Wyślij mecze do aplikacji
                    sport_name = '_'.join(sports) if len(sports) <= 2 else 'multi'
                    success = integrator.send_matches(
                        matches=rows,
                        date=date,
                        sport=sport_name
                    )
                    
                    if success:
                        print("   ✅ Dane wysłane do aplikacji pomyślnie!")
                    else:
                        print("   ⚠️  Nie udało się wysłać danych do aplikacji")
                else:
                    print("   ⚠️  Nie można połączyć się z aplikacją - pomijam")
            
            except Exception as e:
                print(f"   ⚠️  Błąd wysyłania do aplikacji: {e}")
                print("   💡 Scraping i email zakończone pomyślnie")
        else:
            # Spróbuj załadować z pliku konfiguracyjnego
            integrator = create_integrator_from_config()
            if integrator and integrator.test_connection():
                print(f"\n🔗 BONUS: Wysyłanie danych do aplikacji z konfiguracji...")
                sport_name = '_'.join(sports) if len(sports) <= 2 else 'multi'
                integrator.send_matches(rows, date, sport_name)
        
    except Exception as e:
        print(f"\n❌ Błąd: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        driver.quit()
        print("\n🔒 Przeglądarka zamknięta")


def main():
    parser = argparse.ArgumentParser(
        description='Scrapuje mecze i wysyła powiadomienie email',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Przykłady użycia:

  # Podstawowe: piłka nożna na dzisiaj
  python scrape_and_notify.py --date 2025-10-05 --sports football \\
    --to twoj@email.com --from twoj@email.com --password "haslo"

  # Wiele sportów
  python scrape_and_notify.py --date 2025-10-05 --sports football basketball \\
    --to twoj@email.com --from twoj@email.com --password "haslo"

  # 🔥 NOWE: Tylko mecze z PRZEWAGĄ FORMY (przyspiesza proces)
  python scrape_and_notify.py --date 2025-10-05 --sports football \\
    --to twoj@email.com --from twoj@email.com --password "haslo" --only-form-advantage

  # 💰 NOWE: Pomijaj mecze BEZ KURSÓW
  python scrape_and_notify.py --date 2025-10-05 --sports football \\
    --to twoj@email.com --from twoj@email.com --password "haslo" --skip-no-odds

  # 🔥💰 Połączenie: Tylko przewaga formy + tylko z kursami
  python scrape_and_notify.py --date 2025-10-05 --sports football \\
    --to twoj@email.com --from twoj@email.com --password "haslo" --only-form-advantage --skip-no-odds

  # 🏃 NOWE: Fokus na drużynach GOŚCI (away teams)
  python scrape_and_notify.py --date 2025-10-05 --sports football \\
    --to twoj@email.com --from twoj@email.com --password "haslo" --away-team-focus

  # 🏃🔥 Połączenie: Goście + przewaga formy
  python scrape_and_notify.py --date 2025-10-05 --sports football \\
    --to twoj@email.com --from twoj@email.com --password "haslo" --away-team-focus --only-form-advantage

  # Test na 20 meczach
  python scrape_and_notify.py --date 2025-10-05 --sports football \\
    --to twoj@email.com --from twoj@email.com --password "haslo" --max-matches 20

WAŻNE dla Gmail:
  Użyj "App Password" zamiast zwykłego hasła!
  Uzyskaj tutaj: https://myaccount.google.com/apppasswords
        """
    )
    
    parser.add_argument('--date', required=True, help='Data YYYY-MM-DD')
    parser.add_argument('--sports', nargs='+', required=True,
                       choices=['football', 'soccer', 'basketball', 'volleyball', 'handball', 'rugby', 'hockey', 'tennis'],
                       help='Lista sportów')
    parser.add_argument('--to', required=True, help='Email odbiorcy')
    parser.add_argument('--from-email', required=True, help='Email nadawcy')
    parser.add_argument('--password', required=True, help='Hasło email (lub App Password dla Gmail)')
    parser.add_argument('--provider', default='gmail', choices=['gmail', 'outlook', 'yahoo'],
                       help='Provider email (domyślnie: gmail)')
    parser.add_argument('--headless', action='store_true', help='Uruchom bez wyświetlania przeglądarki')
    parser.add_argument('--max-matches', type=int, help='Limit meczów (dla testów)')
    parser.add_argument('--sort', default='time', choices=['time', 'wins', 'team'],
                       help='Sortowanie: time (godzina), wins (wygrane), team (alfabetycznie)')
    parser.add_argument('--only-form-advantage', action='store_true',
                       help='🔥 Wyślij tylko mecze z PRZEWAGĄ FORMY gospodarzy/gości (przyspiesza proces)')
    parser.add_argument('--skip-no-odds', action='store_true',
                       help='💰 Pomijaj mecze BEZ KURSÓW bukmacherskich')
    parser.add_argument('--away-team-focus', action='store_true',
                       help='🏃 Szukaj meczów gdzie GOŚCIE mają >=60%% H2H (zamiast gospodarzy)')
    parser.add_argument('--use-forebet', action='store_true',
                       help='🎯 Pobieraj predykcje z Forebet.com (wymaga widocznej przeglądarki)')
    parser.add_argument('--use-sofascore', action='store_true',
                       help='🗳️ Pobieraj Fan Vote z SofaScore.com (wymaga widocznej przeglądarki)')
    parser.add_argument('--use-odds', action='store_true',
                       help='💰 Pobieraj kursy z FlashScore.com')
    parser.add_argument('--use-gemini', action='store_true',
                       help='🤖 Analizuj mecze z Gemini AI')
    parser.add_argument('--app-url', default=None,
                       help='URL aplikacji UI do wysyłania danych (np. http://localhost:3000)')
    parser.add_argument('--app-api-key', default=None,
                       help='API key dla aplikacji UI (opcjonalne)')
    
    args = parser.parse_args()
    
    scrape_and_send_email(
        date=args.date,
        sports=args.sports,
        to_email=args.to,
        from_email=args.from_email,
        password=args.password,
        provider=args.provider,
        headless=args.headless,
        max_matches=args.max_matches,
        sort_by=args.sort,
        app_url=args.app_url,
        app_api_key=args.app_api_key,
        only_form_advantage=args.only_form_advantage,
        skip_no_odds=args.skip_no_odds,
        away_team_focus=args.away_team_focus,
        use_forebet=args.use_forebet,
        use_sofascore=args.use_sofascore,
        use_odds=args.use_odds,
        use_gemini=args.use_gemini
    )
    
    print("\n✨ ZAKOŃCZONO!")


if __name__ == '__main__':
    main()

