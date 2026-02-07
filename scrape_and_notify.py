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
import math
import re
from datetime import datetime
from livesport_h2h_scraper import start_driver, get_match_links_from_day, process_match, process_match_tennis, detect_sport_from_url
from email_notifier import send_email_notification
from app_integrator import AppIntegrator, create_integrator_from_config
import pandas as pd
import numpy as np
import time


def clean_odds_value(val):
    """
    Czyści wartość kursu - zamienia NaN/None/string 'nan' na None.
    Zwraca float lub None.
    """
    if val is None:
        return None
    if isinstance(val, str):
        if val.lower() == 'nan' or val.strip() == '':
            return None
        try:
            return float(val)
        except ValueError:
            return None
    if isinstance(val, float):
        if math.isnan(val):
            return None
        return val
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def clean_for_json(value):
    """
    Czyści wartość przed eksportem JSON - zamienia NaN na None.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str) and value.lower() == 'nan':
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def clean_dataframe_for_csv(df):
    """
    Czyści DataFrame przed zapisem do CSV - zamienia NaN na None dla kursów.
    """
    # Zamień NaN na None w całym DataFrame
    df = df.replace({pd.NA: None, np.nan: None})
    
    # Specjalne czyszczenie kolumn z kursami
    odds_columns = ['home_odds', 'draw_odds', 'away_odds']
    for col in odds_columns:
        if col in df.columns:
            df[col] = df[col].apply(clean_odds_value)
    
    return df

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
    use_gemini: bool = False,
    include_sorted_odds: bool = True,
    odds_limit: int = 15
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
    import time as time_module
    import os
    
    # Wykrywanie CI
    IS_CI = os.getenv('CI') == 'true' or os.getenv('GITHUB_ACTIONS') == 'true'
    
    # Statystyki dla CI
    _ci_stats = {
        'total_matches': 0,
        'qualifying': 0,
        'enriched': 0,  # mecze z danymi z Forebet/SofaScore/Gemini
        'with_odds': 0,
        'start_time': time_module.time(),
    }
    
    print("="*70)
    print("🤖 AUTOMATYCZNY SCRAPING + POWIADOMIENIE EMAIL")
    if IS_CI:
        print("🔧 TRYB CI: Zoptymalizowane timeouty, mniej retry")
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
    
    driver = start_driver(headless=headless)
    
    try:
        # KROK 1: Zbierz linki
        print("\n🔍 KROK 1/3: Zbieranie linków do meczów...")
        urls = get_match_links_from_day(driver, date, sports=sports, leagues=None)
        print(f"✅ Znaleziono {len(urls)} meczów")
        
        if max_matches and len(urls) > max_matches:
            urls = urls[:max_matches]
            print(f"⚠️  Ograniczono do {max_matches} meczów (tryb testowy)")
        
        # ========================================================================
        # DWUFAZOWY PROCES OPTYMALIZACJI CZASOWEJ
        # FAZA 1: Szybkie sprawdzenie kwalifikacji (bez Forebet/SofaScore)
        # FAZA 2: Wzbogacenie danych tylko dla kwalifikujących się meczów
        # ========================================================================
        
        # Przygotuj nazwę pliku
        sport_suffix = '_'.join(sports) if len(sports) <= 2 else 'multi'
        if away_team_focus:
            outfn = f'outputs/livesport_h2h_{date}_{sport_suffix}_AWAY_FOCUS_EMAIL.csv'
        else:
            outfn = f'outputs/livesport_h2h_{date}_{sport_suffix}_EMAIL.csv'
        os.makedirs('outputs', exist_ok=True)
        
        rows = []
        qualifying_count = 0
        qualifying_indices = []  # Indeksy kwalifikujących się meczów
        RESTART_INTERVAL = 50  # Zwiększone dla szybszego przetwarzania w FAZIE 1
        CHECKPOINT_INTERVAL = 40  # Zwiększone dla FAZY 1
        
        # ========================================================================
        # FAZA 1: SZYBKIE SPRAWDZENIE KWALIFIKACJI (BEZ Forebet/SofaScore)
        # ========================================================================
        phase1_start = time_module.time()
        print(f"\n" + "="*70)
        print(f"⚡ FAZA 1/2: SZYBKIE SPRAWDZENIE KWALIFIKACJI ({len(urls)} meczów)")
        print(f"   (bez Forebet/SofaScore - tylko H2H + forma)")
        print("="*70)
        
        for i, url in enumerate(urls, 1):
            # Oblicz ETA
            if i > 1:
                elapsed = time_module.time() - phase1_start
                avg_per_match = elapsed / (i - 1)
                remaining = (len(urls) - i + 1) * avg_per_match
                eta_min = remaining / 60
                progress_pct = (i / len(urls)) * 100
                print(f"\n[FAZA 1: {i}/{len(urls)} ({progress_pct:.0f}%)] ETA: {eta_min:.1f} min")
            else:
                print(f"\n[FAZA 1: {i}/{len(urls)}] Przetwarzam...")
            
            # RETRY LOGIC - w CI tylko 1 próba, lokalnie 3 próby
            max_retries = 1 if IS_CI else 3
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
                            qualifying_indices.append(len(rows) - 1)
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
                        
                        success = True
                    
                    else:
                        # Sporty drużynowe - FAZA 1: BEZ Forebet/SofaScore
                        current_sport = detect_sport_from_url(url)
                        info = process_match(url, driver, away_team_focus=away_team_focus,
                                           use_forebet=False, use_gemini=False, 
                                           use_sofascore=False, sport=current_sport)
                        rows.append(info)
                        
                        if info['qualifies']:
                            qualifying_count += 1
                            qualifying_indices.append(len(rows) - 1)
                            h2h_count = info.get('h2h_count', 0)
                            win_rate = info.get('win_rate', 0.0)
                            home_form = info.get('home_form', [])
                            away_form = info.get('away_form', [])
                            
                            home_form_str = '-'.join(home_form) if home_form else 'N/A'
                            away_form_str = '-'.join(away_form) if away_form else 'N/A'
                            
                            if away_team_focus:
                                wins_count = info.get('away_wins_in_h2h_last5', 0)
                                focused_team = info['away_team']
                            else:
                                wins_count = info['home_wins_in_h2h_last5']
                                focused_team = info['home_team']
                            
                            print(f"   ✅ KWALIFIKUJE! {info['home_team']} vs {info['away_team']}")
                            print(f"      Fokus: {focused_team}, H2H: {wins_count}/{h2h_count} ({win_rate*100:.0f}%)")
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
                        
                        success = True
                    
                except (ConnectionResetError, ConnectionError, Exception) as e:
                    retry_count += 1
                    if retry_count < max_retries:
                        print(f"   ⚠️  Błąd połączenia (próba {retry_count}/{max_retries}): {str(e)[:100]}")
                        print(f"   🔄 Restartowanie przeglądarki i ponowienie próby...")
                        try:
                            driver.quit()
                        except:
                            pass
                        time.sleep(2 if IS_CI else 3)
                        driver = start_driver(headless=headless)
                    else:
                        print(f"   ❌ Błąd po {max_retries} próbach: {str(e)[:100]}")
                        print(f"   ⏭️  Pomijam ten mecz i kontynuuję...")
            
            # CHECKPOINT - zapisz co 40 meczów
            if i % CHECKPOINT_INTERVAL == 0 and len(rows) > 0:
                print(f"\n💾 CHECKPOINT FAZA 1: ({i}/{len(urls)} meczów)...")
                try:
                    df_checkpoint = pd.DataFrame(rows)
                    if 'h2h_last5' in df_checkpoint.columns:
                        df_checkpoint['h2h_last5'] = df_checkpoint['h2h_last5'].apply(lambda x: str(x) if x else '')
                    # 🔧 Czyść kursy przed zapisem - zamień NaN na None
                    df_checkpoint = clean_dataframe_for_csv(df_checkpoint)
                    df_checkpoint.to_csv(outfn, index=False, encoding='utf-8-sig')
                    print(f"   ✅ Zapisano! ({qualifying_count} kwalifikujących)")
                except Exception as e:
                    print(f"   ⚠️  Błąd zapisu: {e}")
            
            # AUTO-RESTART przeglądarki
            if i % RESTART_INTERVAL == 0 and i < len(urls):
                print(f"\n🔄 AUTO-RESTART po {i} meczach...")
                try:
                    driver.quit()
                    time.sleep(1.5 if IS_CI else 2)
                    driver = start_driver(headless=headless)
                    print(f"   ✅ OK! Kontynuuję...")
                except Exception as e:
                    print(f"   ⚠️  Błąd restartu: {e}")
                    driver = start_driver(headless=headless)
            
            # Rate limiting - zoptymalizowane dla szybkości
            elif i < len(urls):
                time.sleep(0.3 if IS_CI else 0.8)
        
        phase1_end = time_module.time()
        phase1_duration = phase1_end - phase1_start
        
        print(f"\n" + "="*70)
        print(f"⚡ FAZA 1 ZAKOŃCZONA!")
        print(f"   Czas: {phase1_duration/60:.1f} min ({phase1_duration:.0f}s)")
        print(f"   Przetworzone: {len(rows)} meczów")
        print(f"   Kwalifikujące się: {qualifying_count} ({100*qualifying_count/len(rows):.1f}%)" if len(rows) > 0 else "")
        print(f"   Średni czas/mecz: {phase1_duration/len(rows):.2f}s" if len(rows) > 0 else "")
        
        # 🎾 TENNIS-SPECIFIC LOGGING: Pokaż statystyki dla tenisa
        if 'tennis' in sports:
            tennis_matches = [r for r in rows if r.get('sport') == 'tennis' or '/tenis/' in str(r.get('match_url', '')).lower()]
            tennis_qualifying = [r for r in tennis_matches if r.get('qualifies')]
            tennis_with_ranking = [r for r in tennis_qualifying if r.get('ranking_a') and r.get('ranking_b')]
            tennis_with_form = [r for r in tennis_qualifying if r.get('form_a') or r.get('home_form')]
            tennis_with_odds = [r for r in tennis_qualifying if r.get('home_odds') or r.get('away_odds')]
            
            print(f"\n   🎾 TENNIS SUMMARY:")
            print(f"      Total tennis matches: {len(tennis_matches)}")
            print(f"      Qualifying: {len(tennis_qualifying)}")
            print(f"      With ranking: {len(tennis_with_ranking)}")
            print(f"      With form: {len(tennis_with_form)}")
            print(f"      With odds: {len(tennis_with_odds)}")
            
            # Debug: Pokaż przykładowe dane (w CI)
            if IS_CI and tennis_qualifying and len(tennis_qualifying) > 0:
                sample = tennis_qualifying[0]
                print(f"      Sample match: {sample.get('home_team')} vs {sample.get('away_team')}")
                print(f"         Advanced score: {sample.get('advanced_score', 'N/A')}")
                print(f"         Ranking A: {sample.get('ranking_a', 'N/A')}, B: {sample.get('ranking_b', 'N/A')}")
                print(f"         Form A: {sample.get('form_a', sample.get('home_form', 'N/A'))}")
                print(f"         H2H: {sample.get('home_wins_in_h2h_last5', 0)}-{sample.get('away_wins_in_h2h', 0)}")
        
        # 🏐 VOLLEYBALL SUMMARY
        if 'volleyball' in sports:
            vol_matches = [r for r in rows if r.get('sport') == 'volleyball' or '/siatkowka/' in str(r.get('match_url', '')).lower()]
            vol_qualifying = [r for r in vol_matches if r.get('qualifies')]
            vol_with_form = [r for r in vol_qualifying if r.get('home_form_overall') or r.get('home_form')]
            vol_with_odds = [r for r in vol_qualifying if r.get('home_odds') or r.get('away_odds')]
            
            print(f"\n   🏐 VOLLEYBALL SUMMARY:")
            print(f"      Total matches: {len(vol_matches)}")
            print(f"      Qualifying: {len(vol_qualifying)}")
            print(f"      With form: {len(vol_with_form)}")
            print(f"      With odds: {len(vol_with_odds)}")
        
        # 🏀 BASKETBALL SUMMARY
        if 'basketball' in sports:
            bball_matches = [r for r in rows if r.get('sport') == 'basketball' or '/koszykowka/' in str(r.get('match_url', '')).lower()]
            bball_qualifying = [r for r in bball_matches if r.get('qualifies')]
            bball_with_form = [r for r in bball_qualifying if r.get('home_form_overall') or r.get('home_form')]
            bball_with_odds = [r for r in bball_qualifying if r.get('home_odds') or r.get('away_odds')]
            
            print(f"\n   🏀 BASKETBALL SUMMARY:")
            print(f"      Total matches: {len(bball_matches)}")
            print(f"      Qualifying: {len(bball_qualifying)}")
            print(f"      With form: {len(bball_with_form)}")
            print(f"      With odds: {len(bball_with_odds)}")
        
        print("="*70)
        
        # ========================================================================
        # FAZA 2: WZBOGACENIE DANYCH (tylko kwalifikujące się mecze)
        # ========================================================================
        if qualifying_count > 0 and (use_forebet or use_sofascore or use_gemini):
            phase2_start = time_module.time()
            print(f"\n" + "="*70)
            print(f"🎯 FAZA 2/2: WZBOGACENIE DANYCH ({qualifying_count} kwalifikujących meczów)")
            if use_forebet:
                print(f"   ✓ Forebet: predykcje i prawdopodobieństwa")
            if use_sofascore:
                print(f"   ✓ SofaScore: Fan Vote")
            if use_gemini:
                print(f"   ✓ Gemini AI: analiza")
            print("="*70)
            
            # 🔥 PRE-FETCH: Pobierz HTML Forebet dla wszystkich sportów na raz
            if use_forebet:
                try:
                    from forebet_scraper import prefetch_all_sports, search_forebet_prediction
                    FOREBET_AVAILABLE = True
                    print(f"\n🔥 PRE-FETCH: Pobieranie HTML Forebet dla wszystkich sportów...")
                    unique_sports = list(set(sports))
                    prefetch_results = prefetch_all_sports(unique_sports, date)
                    for sport_name, success in prefetch_results.items():
                        status = "✅" if success else "❌"
                        print(f"   {status} {sport_name}")
                except ImportError as ie:
                    FOREBET_AVAILABLE = False
                    print(f"   ⚠️ Forebet scraper niedostępny: ImportError - {ie}")
                except Exception as e:
                    FOREBET_AVAILABLE = False
                    print(f"   ⚠️ Forebet scraper niedostępny: {type(e).__name__} - {e}")
            
            # Import SofaScore jeśli potrzebny
            if use_sofascore:
                try:
                    from sofascore_scraper import get_sofascore_prediction
                    SOFASCORE_AVAILABLE = True
                except ImportError as ie:
                    SOFASCORE_AVAILABLE = False
                    print(f"   ⚠️ SofaScore scraper niedostępny: ImportError - {ie}")
                except Exception as e:
                    SOFASCORE_AVAILABLE = False
                    print(f"   ⚠️ SofaScore scraper niedostępny: {type(e).__name__} - {e}")
            
            # Przetwórz każdy kwalifikujący się mecz
            enriched_count = 0
            for j, idx in enumerate(qualifying_indices, 1):
                row = rows[idx]
                home_team = row.get('home_team', '')
                away_team = row.get('away_team', '')
                match_time = row.get('match_time', '')
                current_sport = detect_sport_from_url(row.get('match_url', ''))
                
                # ETA dla FAZY 2
                if j > 1:
                    elapsed = time_module.time() - phase2_start
                    avg_per_match = elapsed / (j - 1)
                    remaining = (qualifying_count - j + 1) * avg_per_match
                    eta_min = remaining / 60
                    print(f"\n[FAZA 2: {j}/{qualifying_count}] {home_team} vs {away_team} (ETA: {eta_min:.1f} min)")
                else:
                    print(f"\n[FAZA 2: {j}/{qualifying_count}] {home_team} vs {away_team}")
                
                # FOREBET
                if use_forebet and FOREBET_AVAILABLE:
                    try:
                        # Wyciągnij datę z match_time
                        match_date = None
                        if match_time:
                            date_match = re.search(r'(\d{1,2}\.\d{1,2}\.\d{4})', match_time)
                            if date_match:
                                day, month, year = date_match.group(1).split('.')
                                match_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                        
                        if not match_date:
                            match_date = date
                        
                        forebet_result = search_forebet_prediction(
                            home_team=home_team,
                            away_team=away_team,
                            match_date=match_date,
                            sport=current_sport
                        )
                        
                        if forebet_result.get('success') or forebet_result.get('found'):
                            row['forebet_prediction'] = forebet_result.get('prediction')
                            row['forebet_probability'] = forebet_result.get('probability')
                            row['forebet_exact_score'] = forebet_result.get('exact_score')
                            row['forebet_over_under'] = forebet_result.get('over_under')
                            row['forebet_btts'] = forebet_result.get('btts')
                            row['forebet_avg_goals'] = forebet_result.get('avg_goals')
                            print(f"   ✅ Forebet: {row['forebet_prediction']} ({row['forebet_probability']}%)")
                        else:
                            print(f"   ⚠️ Forebet: nie znaleziono ({forebet_result.get('error', 'brak')})")
                    except Exception as e:
                        print(f"   ❌ Forebet błąd: {str(e)[:50]}")
                
                # SOFASCORE
                if use_sofascore and SOFASCORE_AVAILABLE:
                    try:
                        sofascore_result = get_sofascore_prediction(
                            home_team=home_team,
                            away_team=away_team,
                            sport=current_sport
                        )
                        
                        if sofascore_result.get('found'):
                            row['sofascore_home_win_prob'] = sofascore_result.get('home_win_prob')
                            row['sofascore_draw_prob'] = sofascore_result.get('draw_prob')
                            row['sofascore_away_win_prob'] = sofascore_result.get('away_win_prob')
                            row['sofascore_total_votes'] = sofascore_result.get('total_votes')
                            print(f"   ✅ SofaScore: H:{row['sofascore_home_win_prob']}% D:{row['sofascore_draw_prob']}% A:{row['sofascore_away_win_prob']}%")
                        else:
                            print(f"   ⚠️ SofaScore: nie znaleziono")
                    except Exception as e:
                        print(f"   ❌ SofaScore błąd: {str(e)[:50]}")
                
                # GEMINI AI (jeśli włączone)
                if use_gemini:
                    try:
                        from gemini_analyzer import analyze_match_with_gemini
                        gemini_result = analyze_match_with_gemini(row)
                        if gemini_result:
                            row['gemini_prediction'] = gemini_result.get('prediction')
                            row['gemini_confidence'] = gemini_result.get('confidence')
                            row['gemini_reasoning'] = gemini_result.get('reasoning')
                            row['gemini_recommendation'] = gemini_result.get('recommendation')
                            print(f"   ✅ Gemini: {row['gemini_recommendation']} ({row['gemini_confidence']}%)")
                    except Exception as e:
                        print(f"   ❌ Gemini błąd: {str(e)[:50]}")
                
                # Oznacz jako wzbogacony
                if row.get('forebet_prediction') or row.get('sofascore_home_win_prob') or row.get('gemini_prediction'):
                    enriched_count += 1
                
                # Rate limiting między meczami w FAZIE 2
                if j < qualifying_count:
                    time.sleep(0.5 if IS_CI else 1.0)
            
            phase2_end = time_module.time()
            phase2_duration = phase2_end - phase2_start
            
            print(f"\n" + "="*70)
            print(f"🎯 FAZA 2 ZAKOŃCZONA!")
            print(f"   Czas: {phase2_duration/60:.1f} min ({phase2_duration:.0f}s)")
            print(f"   Wzbogaconych: {enriched_count}/{qualifying_count}")
            print(f"   Średni czas/mecz: {phase2_duration/qualifying_count:.2f}s" if qualifying_count > 0 else "")
            print("="*70)
        else:
            if qualifying_count == 0:
                print(f"\n⚠️ Brak kwalifikujących się meczów - pomijam FAZĘ 2")
            elif not (use_forebet or use_sofascore or use_gemini):
                print(f"\n⚠️ Forebet/SofaScore/Gemini wyłączone - pomijam FAZĘ 2")
        
        # Zapisz finalne wyniki (plik już istnieje jeśli były checkpointy)
        print("\n💾 Zapisywanie finalnych wyników...")
        
        # 🔧 Upewnij się, że odds_source jest ustawiony (dla emaila)
        for row in rows:
            if row.get('odds_bookmaker') and not row.get('odds_source'):
                row['odds_source'] = row.get('odds_bookmaker')
        
        df = pd.DataFrame(rows)
        if 'h2h_last5' in df.columns:
            df['h2h_last5'] = df['h2h_last5'].apply(lambda x: str(x) if x else '')
        
        # 🔧 Czyść kursy przed zapisem - zamień NaN na None
        df = clean_dataframe_for_csv(df)
        
        df.to_csv(outfn, index=False, encoding='utf-8-sig')
        print(f"✅ Zapisano do: {outfn}")
        
        # ========================================================================
        # CI STATS: Podsumowanie wydajności
        # ========================================================================
        _ci_stats['total_matches'] = len(rows)
        _ci_stats['qualifying'] = qualifying_count
        _ci_stats['enriched'] = sum(1 for r in rows if r.get('forebet_prediction') or r.get('sofascore_home_win_prob') or r.get('gemini_prediction'))
        _ci_stats['with_odds'] = sum(1 for r in rows if r.get('home_odds'))
        _ci_stats['elapsed'] = time_module.time() - _ci_stats['start_time']
        
        avg_per_match = _ci_stats['elapsed'] / len(rows) if len(rows) > 0 else 0
        
        print("\n" + "="*70)
        print("📊 CI STATS: PODSUMOWANIE SCRAPINGU")
        print("="*70)
        print(f"   Total meczów:      {_ci_stats['total_matches']}")
        print(f"   Kwalifikujące:     {_ci_stats['qualifying']} ({100*_ci_stats['qualifying']/_ci_stats['total_matches']:.1f}%)" if _ci_stats['total_matches'] > 0 else "   Kwalifikujące:     0")
        print(f"   Wzbogacone:        {_ci_stats['enriched']} (Forebet/SofaScore/Gemini)")
        print(f"   Z kursami:         {_ci_stats['with_odds']}")
        print(f"   Czas:              {_ci_stats['elapsed']/60:.1f} min ({_ci_stats['elapsed']:.0f}s)")
        print(f"   Śr. czas/mecz:     {avg_per_match:.2f}s")
        if _ci_stats['total_matches'] >= 100:
            est_3000 = avg_per_match * 3000 / 3600
            print(f"   Est. dla 3000:     {est_3000:.1f}h")
        print("="*70 + "\n")
        
        # Zapisz przewidywania do JSON (dla późniejszej weryfikacji)
        if qualifying_count > 0:
            predictions_file = outfn.replace('.csv', '_predictions.json')
            qualifying_rows = [r for r in rows if r.get('qualifies', False)]
            
            with open(predictions_file, 'w', encoding='utf-8') as f:
                json.dump(qualifying_rows, f, ensure_ascii=False, indent=2)
            print(f"✅ Przewidywania zapisane do: {predictions_file}")
        
        # 📝 UWAGA: Kursy są pobierane z Livesport API w FAZIE 1 (process_match)
        # Preferowany bukmacher: Pinnacle (ID=3)
        # Nie używamy FlashScore - tylko Livesport API
        
        # 📊 EKSPORT JSON DLA FRONTEND API
        print(f"\n📊 Eksport danych JSON dla frontendu...")
        os.makedirs('results', exist_ok=True)
        sport_suffix = '_'.join(sports) if len(sports) <= 2 else 'multi'
        json_filename = f'results/matches_{date}_{sport_suffix}.json'
        
        # Przygotuj dane w formacie frontendu
        frontend_matches = []
        for row in rows:
            match_data = {
                'id': hash(f"{row.get('home_team', '')}_{row.get('away_team', '')}_{row.get('time', '')}"),
                'homeTeam': row.get('home_team', ''),
                'awayTeam': row.get('away_team', ''),
                'time': row.get('time', ''),
                'date': date,
                'league': row.get('league', row.get('tournament', '')),
                'country': row.get('country', ''),
                'sport': sport_suffix if len(sports) == 1 else row.get('sport', 'football'),
                'matchUrl': row.get('url', ''),
                'qualifies': row.get('qualifies', False),
                # H2H
                'h2h': {
                    'home': row.get('home_wins_in_h2h_last5', 0),
                    'draw': row.get('draws_in_h2h_last5', 0),
                    'away': row.get('away_wins_in_h2h_last5', 0),
                    'total': row.get('h2h_count', 5),
                    'winRate': int(row.get('win_rate', 0) * 100) if row.get('win_rate') else 0
                },
                # Form
                'homeForm': row.get('home_form', []),
                'awayForm': row.get('away_form', []),
                'homeFormHome': row.get('home_form_home', []),
                'awayFormAway': row.get('away_form_away', []),
                'formAdvantage': row.get('form_advantage', False),
                # Odds - czyść NaN przed eksportem
                'odds': {
                    'home': clean_odds_value(row.get('home_odds')),
                    'draw': clean_odds_value(row.get('draw_odds')),
                    'away': clean_odds_value(row.get('away_odds')),
                    'bookmaker': clean_for_json(row.get('odds_source', row.get('odds_bookmaker', 'Pinnacle')))
                } if clean_odds_value(row.get('home_odds')) or clean_odds_value(row.get('away_odds')) else None,
                # Forebet - czyść NaN przed eksportem
                'forebet': {
                    'prediction': clean_for_json(row.get('forebet_prediction')),
                    'probability': clean_for_json(row.get('forebet_probability')),
                    'exactScore': clean_for_json(row.get('forebet_score')),
                    'overUnder': clean_for_json(row.get('forebet_over_under')),
                    'btts': clean_for_json(row.get('forebet_btts'))
                } if clean_for_json(row.get('forebet_prediction')) else None,
                # SofaScore - czyść NaN przed eksportem
                'sofascore': {
                    'home': clean_for_json(row.get('sofascore_home_win_prob')),
                    'draw': clean_for_json(row.get('sofascore_draw_prob')),
                    'away': clean_for_json(row.get('sofascore_away_win_prob')),
                    'votes': clean_for_json(row.get('sofascore_total_votes', 0))
                } if clean_for_json(row.get('sofascore_home_win_prob')) else None,
                # Focus
                'focusTeam': 'away' if away_team_focus else 'home'
            }
            frontend_matches.append(match_data)
        
        # Zapisz JSON
        json_output = {
            'date': date,
            'sport': sport_suffix,
            'generatedAt': datetime.now().isoformat(),
            'stats': {
                'total': len(frontend_matches),
                'qualifying': qualifying_count,
                'formAdvantage': sum(1 for m in frontend_matches if m.get('formAdvantage'))
            },
            'matches': frontend_matches
        }
        
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(json_output, f, ensure_ascii=False, indent=2)
        
        print(f"   ✅ JSON zapisany: {json_filename}")
        
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
                skip_no_odds=skip_no_odds,
                include_sorted_odds=include_sorted_odds,
                odds_limit=odds_limit
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
    parser.add_argument('--sorted-odds', action='store_true', default=True,
                       help='💰📊 Dodaj sekcje z kursami posortowanymi od najwyższych (domyślnie włączone)')
    parser.add_argument('--no-sorted-odds', action='store_true',
                       help='💰📊 Wyłącz sekcje z posortowanymi kursami')
    parser.add_argument('--odds-limit', type=int, default=15,
                       help='Max liczba meczów w każdej sekcji kursów (domyślnie 15)')
    
    args = parser.parse_args()
    
    # Sorted odds - domyślnie włączone, chyba że --no-sorted-odds
    include_sorted_odds = not args.no_sorted_odds
    
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
        use_gemini=args.use_gemini,
        include_sorted_odds=include_sorted_odds,
        odds_limit=args.odds_limit
    )
    
    print("\n✨ ZAKOŃCZONO!")


if __name__ == '__main__':
    main()

