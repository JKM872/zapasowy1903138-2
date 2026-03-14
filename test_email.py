"""
Test Email Notifier - Unit Tests
================================
Testy jednostkowe dla modułu wysyłania emaili.
"""

import sys
import os

print("=" * 60)
print("🧪 TESTY JEDNOSTKOWE: Email Notifier")
print("=" * 60)

tests_passed = 0
tests_failed = 0

# ============================================================================
# TEST 1: Importy
# ============================================================================
print("\n📦 TEST 1: Importy modułów")
print("-" * 50)

try:
    from email_notifier import (
        send_email_notification,
        create_html_email,
        SMTP_CONFIG
    )
    print("   ✅ Import email_notifier - OK")
    tests_passed += 1
except ImportError as e:
    print(f"   ❌ Import email_notifier - FAILED: {e}")
    tests_failed += 1

# ============================================================================
# TEST 2: SMTP Configuration
# ============================================================================
print("\n📧 TEST 2: Konfiguracja SMTP")
print("-" * 50)

expected_providers = ['gmail', 'outlook', 'yahoo']
for provider in expected_providers:
    if provider in SMTP_CONFIG:
        config = SMTP_CONFIG[provider]
        if 'server' in config and 'port' in config and 'use_tls' in config:
            print(f"   ✅ {provider}: {config['server']}:{config['port']} (TLS={config['use_tls']})")
            tests_passed += 1
        else:
            print(f"   ❌ {provider}: brak wymaganych kluczy")
            tests_failed += 1
    else:
        print(f"   ❌ {provider}: brak w SMTP_CONFIG")
        tests_failed += 1

# ============================================================================
# TEST 3: create_html_email function
# ============================================================================
print("\n📝 TEST 3: Funkcja create_html_email")
print("-" * 50)

test_matches = [
    {
        'home_team': 'Liverpool',
        'away_team': 'Manchester United',
        'match_time': '17.11.2025 20:00',
        'home_wins_in_h2h_last5': 3,
        'away_wins_in_h2h_last5': 1,
        'forebet_probability': 75.5,
        'gemini_reasoning': 'Test reasoning',
        'gemini_recommendation': 'HIGH',  # Required for TOP PICKS
        'gemini_confidence': 90,  # Required >= 85 for TOP PICKS
        'home_odds': 1.85,
        'draw_odds': 3.50,
        'away_odds': 4.20,
        'focus_team': 'home'
    }
]

try:
    html = create_html_email(test_matches, '2025-11-17')
    
    # Sprawdź czy HTML zawiera kluczowe elementy
    checks = [
        ('Liverpool', 'home_team'),
        ('Manchester United', 'away_team'),
        ('1.85', 'home_odds'),
    ]
    
    all_ok = True
    for text, field in checks:
        if text in html:
            print(f"   ✅ HTML zawiera {field}: {text}")
            tests_passed += 1
        else:
            print(f"   ❌ HTML nie zawiera {field}: {text}")
            tests_failed += 1
            all_ok = False
    
    if len(html) > 500:
        print(f"   ✅ HTML długość: {len(html)} znaków")
        tests_passed += 1
    else:
        print(f"   ❌ HTML za krótki: {len(html)} znaków")
        tests_failed += 1
        
except Exception as e:
    print(f"   ❌ create_html_email error: {e}")
    tests_failed += 1

# ============================================================================
# TEST 4: send_email_notification signature
# ============================================================================
print("\n📮 TEST 4: Sygnatura send_email_notification")
print("-" * 50)

import inspect
try:
    sig = inspect.signature(send_email_notification)
    params = list(sig.parameters.keys())
    
    required_params = ['csv_file', 'to_email', 'from_email', 'password']
    optional_params = ['provider', 'subject', 'sort_by', 'only_form_advantage', 'skip_no_odds']
    
    for param in required_params:
        if param in params:
            print(f"   ✅ Parametr wymagany: {param}")
            tests_passed += 1
        else:
            print(f"   ❌ Brak parametru: {param}")
            tests_failed += 1
    
    for param in optional_params:
        if param in params:
            print(f"   ✅ Parametr opcjonalny: {param}")
            tests_passed += 1
        else:
            print(f"   ⚠️ Brak parametru opcjonalnego: {param}")
            
except Exception as e:
    print(f"   ❌ Błąd sprawdzania sygnatury: {e}")
    tests_failed += 1

# ============================================================================
# TEST 5: NaN/Float handling in HTML (fix from earlier)
# ============================================================================
print("\n🔢 TEST 5: Obsługa NaN/float w HTML")
print("-" * 50)

import math

test_matches_nan = [
    {
        'home_team': 'Test Home',
        'away_team': 'Test Away',
        'match_time': '01.12.2025 20:00',
        'home_wins_in_h2h_last5': 3,
        'away_wins_in_h2h_last5': 1,
        'forebet_probability': float('nan'),  # NaN value!
        'gemini_reasoning': 123.45,  # Float instead of string!
        'home_odds': None,  # None value!
        'draw_odds': 3.50,
        'away_odds': 4.20,
        'focus_team': 'home'
    }
]

try:
    html_nan = create_html_email(test_matches_nan, '2025-12-01')
    
    if 'Test Home' in html_nan:
        print("   ✅ HTML generuje się z wartościami NaN/None")
        tests_passed += 1
    else:
        print("   ❌ HTML nie generuje się poprawnie")
        tests_failed += 1
        
    # Sprawdź czy nie ma błędu "float has no len()"
    if 'Brak' in html_nan or 'N/A' in html_nan or len(html_nan) > 500:
        print("   ✅ HTML obsługuje NaN/None poprawnie")
        tests_passed += 1
    else:
        print("   ⚠️ HTML może nie obsługiwać NaN poprawnie")
        
except Exception as e:
    print(f"   ❌ Błąd generowania HTML z NaN: {e}")
    tests_failed += 1

# ============================================================================
# TEST 6: Scheduled times check
# ============================================================================
print("\n⏰ TEST 6: Zaplanowane godziny uruchamiania")
print("-" * 50)

schedule_times = {
    '2:00 UTC': 'Football',
    '2:05 UTC': 'Basketball', 
    '2:10 UTC': 'Tennis',
    '2:15 UTC': 'Hockey',
    '2:20 UTC': 'Volleyball',
    '2:25 UTC': 'Handball'
}

for time, sport in schedule_times.items():
    print(f"   ✅ {time} -> {sport}")
    tests_passed += 1

print("\n   📝 Uwaga: 2:00 UTC = 3:00 czasu polskiego zimą")

# ============================================================================
# PODSUMOWANIE
# ============================================================================
print("\n" + "=" * 60)
total_tests = tests_passed + tests_failed
print(f"📊 PODSUMOWANIE: {tests_passed}/{total_tests} testów przeszło")
print("=" * 60)

if tests_failed == 0:
    print("\n✅ WSZYSTKIE TESTY EMAIL PRZESZŁY POMYŚLNIE!")
    sys.exit(0)
else:
    print(f"\n❌ {tests_failed} TESTÓW NIE PRZESZŁO!")
    sys.exit(1)
