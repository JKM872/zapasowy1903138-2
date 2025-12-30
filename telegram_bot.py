"""
Telegram Bot dla BigOne - Powiadomienia o predykcjach sportowych
================================================================

Bot Telegram wysyłający powiadomienia o najlepszych typach dnia.
Komendy:
    /start - Powitanie
    /today - Mecze na dziś
    /predict <team> - Predykcja dla drużyny
    /roi - Statystyki ROI
    /subscribe - Subskrypcja powiadomień
    /unsubscribe - Rezygnacja z powiadomień

Konfiguracja:
    Ustaw zmienne środowiskowe:
    - TELEGRAM_BOT_TOKEN: Token bota
    - TELEGRAM_CHAT_ID: ID czatu do powiadomień automatycznych

Użycie:
    python telegram_bot.py
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from typing import List, Dict, Optional, Set

# Sprawdź czy python-telegram-bot jest zainstalowany
try:
    from telegram import Update, Bot
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("⚠️ python-telegram-bot nie jest zainstalowany.")
    print("   Zainstaluj: pip install python-telegram-bot")

# Import lokalnych modułów
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from roi_tracker import ROITracker
except ImportError:
    ROITracker = None


# Konfiguracja
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
ADMIN_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'outputs')
SUBSCRIBERS_FILE = os.path.join(DATA_DIR, 'telegram_subscribers.json')


class BigOneBot:
    """
    Bot Telegram dla systemu BigOne.
    Wysyła powiadomienia o meczach i predykcjach.
    """
    
    def __init__(self, token: str):
        self.token = token
        self.subscribers: Set[int] = set()
        self._load_subscribers()
    
    def _load_subscribers(self):
        """Wczytuje listę subskrybentów"""
        if os.path.exists(SUBSCRIBERS_FILE):
            try:
                with open(SUBSCRIBERS_FILE, 'r') as f:
                    data = json.load(f)
                    self.subscribers = set(data.get('subscribers', []))
                print(f"📱 Wczytano {len(self.subscribers)} subskrybentów")
            except Exception as e:
                print(f"⚠️ Błąd wczytywania subskrybentów: {e}")
    
    def _save_subscribers(self):
        """Zapisuje listę subskrybentów"""
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SUBSCRIBERS_FILE, 'w') as f:
            json.dump({'subscribers': list(self.subscribers)}, f)
    
    def get_today_matches(self) -> List[Dict]:
        """Pobiera mecze na dziś z pliku wyników"""
        today = datetime.now().strftime('%Y-%m-%d')
        matches = []
        
        # Szukaj plików z dzisiejszą datą
        for sport in ['football', 'basketball', 'volleyball', 'handball', 'hockey', 'tennis']:
            filepath = os.path.join(DATA_DIR, f'matches_{today}_{sport}.json')
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        matches.extend(data.get('matches', []))
                except Exception as e:
                    print(f"⚠️ Błąd wczytywania {filepath}: {e}")
        
        return matches
    
    def format_match_message(self, match: Dict) -> str:
        """Formatuje informacje o meczu do wiadomości"""
        home = match.get('homeTeam', '?')
        away = match.get('awayTeam', '?')
        time = match.get('time', '?')
        league = match.get('league', '')
        
        # H2H
        h2h = match.get('h2h', {})
        h2h_str = f"H2H: {h2h.get('home', 0)}-{h2h.get('draw', 0)}-{h2h.get('away', 0)}"
        
        # Kursy
        odds = match.get('odds', {})
        odds_str = ""
        if odds.get('home'):
            odds_str = f"Kursy: 🏠{odds.get('home', '-')} | ✈️{odds.get('away', '-')}"
        
        # Forebet
        forebet = match.get('forebet', {})
        forebet_str = ""
        if forebet.get('prediction'):
            pred_map = {'1': '🏠 HOME', 'X': '🤝 DRAW', '2': '✈️ AWAY'}
            forebet_str = f"Forebet: {pred_map.get(forebet['prediction'], forebet['prediction'])} ({forebet.get('probability', '?')}%)"
        
        # Kwalifikacja
        qualify = "✅ KWALIFIKUJE" if match.get('qualifies') else ""
        form_adv = "🔥 FORMA" if match.get('formAdvantage') else ""
        
        lines = [
            f"⚽ *{home}* vs *{away}*",
            f"🕐 {time} | {league}",
            h2h_str,
        ]
        
        if odds_str:
            lines.append(odds_str)
        if forebet_str:
            lines.append(forebet_str)
        if qualify or form_adv:
            lines.append(f"{qualify} {form_adv}".strip())
        
        return "\n".join(lines)
    
    def format_daily_summary(self, matches: List[Dict]) -> str:
        """Formatuje podsumowanie dnia"""
        if not matches:
            return "📭 Brak meczów na dziś z kwalifikującymi się predykcjami."
        
        qualifying = [m for m in matches if m.get('qualifies')]
        form_adv = [m for m in matches if m.get('formAdvantage')]
        
        lines = [
            f"📊 *PODSUMOWANIE - {datetime.now().strftime('%d.%m.%Y')}*",
            "",
            f"📌 Wszystkich meczów: {len(matches)}",
            f"✅ Kwalifikujących: {len(qualifying)}",
            f"🔥 Z przewagą formy: {len(form_adv)}",
            "",
            "─" * 20,
            ""
        ]
        
        # Top 5 meczów
        top_matches = sorted(
            qualifying, 
            key=lambda x: x.get('h2h', {}).get('winRate', 0), 
            reverse=True
        )[:5]
        
        if top_matches:
            lines.append("*🏆 TOP 5 MECZÓW:*")
            lines.append("")
            for i, match in enumerate(top_matches, 1):
                home = match.get('homeTeam', '?')
                away = match.get('awayTeam', '?')
                win_rate = match.get('h2h', {}).get('winRate', 0)
                lines.append(f"{i}. {home} vs {away} ({win_rate}%)")
        
        return "\n".join(lines)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler komendy /start"""
    welcome = """
🎯 *Witaj w BigOne Bot!*

Jestem botem do śledzenia predykcji sportowych.

*Dostępne komendy:*
/today - Mecze na dziś
/top - Top 5 najlepszych typów
/roi - Statystyki ROI
/subscribe - Subskrypcja powiadomień
/unsubscribe - Rezygnacja

Miłego typowania! 🍀
    """
    await update.message.reply_text(welcome, parse_mode='Markdown')


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler komendy /today"""
    bot = BigOneBot(BOT_TOKEN)
    matches = bot.get_today_matches()
    
    if not matches:
        await update.message.reply_text(
            "📭 Brak danych o meczach na dziś.\n"
            "Uruchom scraper: `python scrape_and_notify.py`",
            parse_mode='Markdown'
        )
        return
    
    summary = bot.format_daily_summary(matches)
    await update.message.reply_text(summary, parse_mode='Markdown')


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler komendy /top"""
    bot = BigOneBot(BOT_TOKEN)
    matches = bot.get_today_matches()
    
    qualifying = [m for m in matches if m.get('qualifies')]
    top_matches = sorted(
        qualifying, 
        key=lambda x: x.get('h2h', {}).get('winRate', 0), 
        reverse=True
    )[:5]
    
    if not top_matches:
        await update.message.reply_text("📭 Brak kwalifikujących meczów na dziś.")
        return
    
    lines = ["🏆 *TOP 5 TYPÓW NA DZIŚ:*", ""]
    
    for i, match in enumerate(top_matches, 1):
        msg = bot.format_match_message(match)
        lines.append(f"*{i}.* " + msg.replace('*', ''))
        lines.append("")
    
    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')


async def cmd_roi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler komendy /roi"""
    if ROITracker is None:
        await update.message.reply_text("⚠️ ROI Tracker niedostępny.")
        return
    
    tracker = ROITracker()
    stats = tracker.get_stats(30)
    
    profit_emoji = "🟢" if stats.total_profit >= 0 else "🔴"
    
    message = f"""
📊 *ROI - Ostatnie 30 dni*

📈 Łącznie zakładów: {stats.total_bets}
✅ Wygrane: {stats.wins} ({stats.win_rate:.1f}%)
❌ Przegrane: {stats.losses}
⏳ Oczekujące: {stats.pending}

💰 Postawiono: {stats.total_staked:.2f} PLN
{profit_emoji} Profit: {stats.total_profit:+.2f} PLN
📊 ROI: {stats.roi_percent:+.2f}%

🔥 Aktualny streak: {stats.streak_current}
🏆 Najlepszy streak: {stats.streak_best}
    """
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler komendy /subscribe"""
    bot = BigOneBot(BOT_TOKEN)
    chat_id = update.effective_chat.id
    
    if chat_id in bot.subscribers:
        await update.message.reply_text("✅ Już jesteś subskrybentem!")
        return
    
    bot.subscribers.add(chat_id)
    bot._save_subscribers()
    await update.message.reply_text(
        "🔔 Subskrypcja aktywna!\n"
        "Będziesz otrzymywać codzienne podsumowania o 10:00."
    )


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler komendy /unsubscribe"""
    bot = BigOneBot(BOT_TOKEN)
    chat_id = update.effective_chat.id
    
    if chat_id not in bot.subscribers:
        await update.message.reply_text("ℹ️ Nie jesteś subskrybentem.")
        return
    
    bot.subscribers.discard(chat_id)
    bot._save_subscribers()
    await update.message.reply_text("🔕 Subskrypcja anulowana.")


async def send_daily_notification(bot_instance: Bot):
    """Wysyła dzienne powiadomienia do subskrybentów"""
    bigone_bot = BigOneBot(BOT_TOKEN)
    matches = bigone_bot.get_today_matches()
    summary = bigone_bot.format_daily_summary(matches)
    
    for chat_id in bigone_bot.subscribers:
        try:
            await bot_instance.send_message(
                chat_id=chat_id,
                text=summary,
                parse_mode='Markdown'
            )
            print(f"✅ Wysłano do {chat_id}")
        except Exception as e:
            print(f"❌ Błąd wysyłania do {chat_id}: {e}")


def run_bot():
    """Uruchamia bota"""
    if not TELEGRAM_AVAILABLE:
        print("❌ Telegram API niedostępne. Zainstaluj python-telegram-bot.")
        return
    
    if not BOT_TOKEN:
        print("❌ Brak TELEGRAM_BOT_TOKEN. Ustaw zmienną środowiskową.")
        print("   Przykład: set TELEGRAM_BOT_TOKEN=123456:ABC-DEF...")
        return
    
    print("🤖 Uruchamiam BigOne Telegram Bot...")
    
    # Tworzenie aplikacji
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Rejestracja handlerów
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("roi", cmd_roi))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    
    print("✅ Bot gotowy! Naciśnij Ctrl+C aby zatrzymać.")
    
    # Uruchomienie
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    run_bot()
