# 🤖 GEMINI AI QUICKSTART

**Faza 3: Inteligentna analiza meczów z Google Gemini AI**

---

## 🎯 Co robi Gemini AI?

Gemini AI łączy **wszystkie dane** (H2H, forma, Forebet, odds) i tworzy **inteligentne predykcje** z uzasadnieniem:

### **Bez Gemini (Faza 1-2):**
```csv
home_team,away_team,h2h_wins,home_form,forebet_prediction
Resovia,BBTS Bielsko-Biała,3,W-W-D-W-L,65% home win
```

### **Z Gemini (Faza 3):** 🔥
```csv
...,gemini_prediction,gemini_confidence,gemini_recommendation
...,⭐ HIGH: Dom wygrał 3/5 H2H + silna forma (7.3/10) vs słaby gość (2.0/10). Forebet potwierdza 65%. VALUE BET!,85%,HIGH
```

---

## ⚡ SETUP (3 minuty)

### **Krok 1: Zdobądź darmowy API key**

1. Idź do: **https://makersuite.google.com/app/apikey**
2. Kliknij **"Create API Key"**
3. Skopiuj klucz (wygląda jak: `AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`)

**LIMIT:** 60 requestów/minutę + 1500/dzień = **DARMOWE!** 🎁

---

### **Krok 2: Utwórz plik konfiguracyjny**

```bash
# Skopiuj template
copy gemini_config.example.py gemini_config.py

# Edytuj gemini_config.py i wklej swój API key:
```

**`gemini_config.py`:**
```python
GEMINI_API_KEY = "AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"  # ← Twój klucz tutaj
```

✅ **Gotowe!** (plik `gemini_config.py` jest w `.gitignore` - nie wycieknie na GitHub)

---

### **Krok 3: Zainstaluj SDK (jeśli nie masz)**

```bash
pip install google-generativeai
```

---

## 🚀 UŻYCIE

### **Podstawowe** (volleyball z Gemini AI):
```bash
python livesport_h2h_scraper.py --mode auto --date 2025-11-17 --sports volleyball --use-gemini
```

### **Z Forebet + Gemini** (potrójna analiza! 🔥🔥🔥):
```bash
python livesport_h2h_scraper.py --mode auto --date 2025-11-17 --sports football --use-forebet --use-gemini
```

### **Batch - wszystkie sporty + AI**:
```bash
python livesport_h2h_scraper.py --mode auto --date 2025-11-17 --sports football basketball volleyball --use-gemini
```

---

## 📊 OUTPUT

**CSV kolumny (Gemini):**

| Kolumna | Przykład | Opis |
|---------|----------|------|
| `gemini_prediction` | "⭐ HIGH: Dom wygrał 3/5 H2H..." | Krótka predykcja (1-2 zdania) |
| `gemini_confidence` | `85` | Pewność AI (0-100%) |
| `gemini_reasoning` | "Gospodarze wygrali 60% H2H..." | Szczegółowe uzasadnienie |
| `gemini_recommendation` | `HIGH` | Rekomendacja: HIGH/MEDIUM/LOW/SKIP |

---

## 🧪 TEST

### **Test Gemini analyzer (sam moduł):**
```bash
python gemini_analyzer.py
```

**Output:**
```
🤖 Gemini AI Analyzer - Test
==================================================
✅ Configuration OK
✅ API Key: AIzaSyXXXX...XXXXX
✅ Model: gemini-1.5-flash

Testing analysis...
==================================================
📊 RESULTS:
==================================================
🔮 Prediction: Strong home advantage. Resovia dominates with 3/5 H2H wins...
📈 Confidence: 85%
💡 Reasoning: Key factors: 1) H2H record (60% win rate) 2) Superior home form...
⭐ Recommendation: HIGH
```

---

## 💡 PRZYKŁADY

### **1. Volleyball z AI**
```bash
python livesport_h2h_scraper.py --mode auto --date 2025-11-17 --sports volleyball --use-gemini
```

**Output w CSV:**
```
gemini_prediction: "Dom dominuje: 4/5 H2H wygranych + forma 8.3/10 vs 2.7/10 gościa"
gemini_confidence: 90
gemini_recommendation: HIGH
```

---

### **2. Football + Forebet + Gemini** (triple power! 🔥)
```bash
python livesport_h2h_scraper.py --mode auto --date 2025-11-17 --sports football --use-forebet --use-gemini
```

**Gemini widzi:**
- ✅ H2H: 3-1-1 (60% home wins)
- ✅ Forma: 7.3/10 vs 4.0/10
- ✅ Forebet: 65% home win, 2-1 score
- ✅ Odds: 1.85 (fair value)

**AI prediction:**
```
"⭐ HIGH CONFIDENCE: Gospodarze wygrali 3/5 H2H, mają lepszą formę (7.3 vs 4.0), 
Forebet przewiduje 65% home win. Kursy 1.85 = VALUE BET!"
```

---

## ⚠️ TROUBLESHOOTING

### **"No API key configured"**
→ Stwórz `gemini_config.py` z `GEMINI_API_KEY = "your-key"`

### **"google-generativeai not installed"**
```bash
pip install google-generativeai
```

### **"Rate limit exceeded"**
→ Darmowy limit: 60 req/min. Dodaj `time.sleep(1)` między requestami (już zrobione!)

### **"API error"**
→ Sprawdź API key: https://makersuite.google.com/app/apikey
→ Sprawdź limit: https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas

---

## 📈 RATE LIMITING

**Darmowy tier:**
- ✅ 60 requests/minute
- ✅ 1500 requests/day
- ✅ Wystarczy dla ~100 meczów/dzień

**Automatyczne opóźnienie:** 1 sekunda między requestami (w kodzie)

---

## 🎯 ZALETY

✅ **Inteligentna analiza** - łączy wszystkie dane
✅ **Natural language** - czytelne uzasadnienia
✅ **Confidence score** - wiesz jak pewna jest AI
✅ **Rekomendacje** - HIGH/MEDIUM/LOW/SKIP
✅ **Darmowe** - 60 req/min
✅ **Graceful degradation** - działa bez Gemini (jeśli brak klucza)

---

## 🔥 BEST PRACTICES

### **1. Triple Analysis** (H2H + Forebet + Gemini):
```bash
python livesport_h2h_scraper.py --mode auto --date 2025-11-17 --sports football --use-forebet --use-gemini
```

### **2. Filter by confidence:**
```python
# W Pandas/Excel: filtruj gemini_confidence >= 80%
df = df[df['gemini_confidence'] >= 80]
```

### **3. Combine recommendations:**
```python
# Szukaj HIGH recommendations z Gemini + Forebet prediction >60%
df[(df['gemini_recommendation'] == 'HIGH') & (df['forebet_probability'] > 60)]
```

---

## 📚 WIĘCEJ INFORMACJI

- **Pełny guide:** `GEMINI_INTEGRATION_GUIDE.md`
- **API docs:** https://ai.google.dev/docs
- **Get API key:** https://makersuite.google.com/app/apikey

---

## ✨ NEXT STEPS

Po skonfigurowaniu Gemini możesz:

1. **Testować lokalnie** - sprawdź jak AI analizuje mecze
2. **Kombinować z Forebet** - triple analiza (H2H + Forebet + AI)
3. **Filtrować po confidence** - tylko wysokie pewności (>80%)
4. **GitHub Actions** - dodaj `GEMINI_API_KEY` do secrets

---

**🎉 Gotowe! Masz teraz AI w swojej aplikacji!** 🤖

**Questions?** Zobacz `GEMINI_INTEGRATION_GUIDE.md` lub check code in `gemini_analyzer.py`
