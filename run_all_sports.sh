#!/bin/bash
# =========================================================
# Quick Launch Script - All Sports (Linux/Mac)
# =========================================================
# Uruchamia scraper dla wszystkich sportów na dzisiejszą datę
# 
# Użycie: 
#   chmod +x run_all_sports.sh
#   ./run_all_sports.sh
# =========================================================

echo ""
echo "============================================================"
echo " Livesport H2H Scraper - Multi-Sport Edition"
echo "============================================================"
echo ""

# Ustaw datę (zmień na właściwą)
DATE="2025-10-05"

echo "Data: $DATE"
echo ""
echo "Uruchamiam scraper dla wszystkich sportów..."
echo ""

# Uruchom scraper
python3 livesport_h2h_scraper.py --mode auto --date $DATE --sports football basketball volleyball handball rugby hockey --headless --use-forebet --use-sofascore

echo ""
echo "============================================================"
echo " Gotowe!"
echo "============================================================"
echo ""
echo "Wyniki zapisano w katalogu: outputs/"
echo ""

