"""
Email Scheduler - Automatyczne wysyłanie raportów
==================================================

Harmonogram wysyłki emaili z predykcjami:
- Rano (8:00) - mecze na dziś
- Wieczór (20:00) - podsumowanie dnia

Użycie:
    python email_scheduler.py --start
    python email_scheduler.py --test
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# APScheduler
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    print("APScheduler not installed. Run: pip install apscheduler")

# Local imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from email_notifier import send_email_report
    EMAIL_AVAILABLE = True
except ImportError:
    EMAIL_AVAILABLE = False


class EmailScheduler:
    """
    Scheduler do automatycznego wysyłania emaili.
    Obsługuje harmonogram poranny i wieczorny.
    """
    
    def __init__(self):
        self.scheduler = None
        self.config = {
            'morning_hour': 8,
            'morning_minute': 0,
            'evening_hour': 20,
            'evening_minute': 0,
            'timezone': 'Europe/Warsaw'
        }
        
        if SCHEDULER_AVAILABLE:
            self.scheduler = BackgroundScheduler(timezone=self.config['timezone'])
    
    def _get_today_matches(self) -> List[Dict]:
        """Pobiera mecze na dziś"""
        today = datetime.now().strftime('%Y-%m-%d')
        matches = []
        
        outputs_dir = os.path.join(os.path.dirname(__file__), 'outputs')
        
        for sport in ['football', 'basketball', 'volleyball', 'handball', 'hockey', 'tennis']:
            filepath = os.path.join(outputs_dir, f'matches_{today}_{sport}.json')
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        sport_matches = data.get('matches', [])
                        for m in sport_matches:
                            m['sport'] = sport
                        matches.extend(sport_matches)
                except Exception as e:
                    print(f"Blad wczytywania {filepath}: {e}")
        
        return matches
    
    def _get_yesterday_results(self) -> List[Dict]:
        """Pobiera wyniki z wczoraj"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        results = []
        
        outputs_dir = os.path.join(os.path.dirname(__file__), 'outputs')
        
        for sport in ['football', 'basketball', 'volleyball', 'handball', 'hockey', 'tennis']:
            filepath = os.path.join(outputs_dir, f'results_{yesterday}_{sport}.json')
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        results.extend(data.get('results', []))
                except Exception:
                    pass
        
        return results
    
    def morning_job(self):
        """Job poranny - wysyla predykcje na dzis"""
        print(f"[{datetime.now()}] Uruchamiam job poranny...")
        
        matches = self._get_today_matches()
        qualifying = [m for m in matches if m.get('qualifies')]
        
        if not matches:
            print("Brak meczow na dzis")
            return
        
        subject = f"BigOne - Predykcje na {datetime.now().strftime('%d.%m.%Y')} ({len(qualifying)} kwalifikujacych)"
        
        body = f"""
        <h1>Predykcje na dzis</h1>
        <p>Znaleziono <strong>{len(matches)}</strong> meczow, w tym <strong>{len(qualifying)}</strong> kwalifikujacych.</p>
        
        <h2>Top 5 meczow</h2>
        <ul>
        """
        
        # Top 5 po win_rate
        top_matches = sorted(
            qualifying,
            key=lambda x: x.get('h2h', {}).get('winRate', 0),
            reverse=True
        )[:5]
        
        for m in top_matches:
            h2h = m.get('h2h', {})
            body += f"""
            <li>
                <strong>{m.get('homeTeam')} vs {m.get('awayTeam')}</strong><br>
                Liga: {m.get('league', 'N/A')} | H2H: {h2h.get('winRate', 0)}%
            </li>
            """
        
        body += "</ul>"
        
        if EMAIL_AVAILABLE:
            try:
                send_email_report(subject, body)
                print(f"Email poranny wyslany do {len(matches)} meczow")
            except Exception as e:
                print(f"Blad wysylania emaila: {e}")
        else:
            print("Email notifier niedostepny")
    
    def evening_job(self):
        """Job wieczorny - podsumowanie dnia"""
        print(f"[{datetime.now()}] Uruchamiam job wieczorny...")
        
        matches = self._get_today_matches()
        results = self._get_yesterday_results()
        
        subject = f"BigOne - Podsumowanie {datetime.now().strftime('%d.%m.%Y')}"
        
        body = f"""
        <h1>Podsumowanie dnia</h1>
        
        <h2>Statystyki z dzis</h2>
        <ul>
            <li>Wszystkich meczow: {len(matches)}</li>
            <li>Kwalifikujacych: {sum(1 for m in matches if m.get('qualifies'))}</li>
        </ul>
        
        <h2>Wyniki z wczoraj</h2>
        <p>Zakonczone mecze: {len(results)}</p>
        """
        
        if EMAIL_AVAILABLE:
            try:
                send_email_report(subject, body)
                print("Email wieczorny wyslany")
            except Exception as e:
                print(f"Blad wysylania emaila: {e}")
    
    def start(self):
        """Uruchamia scheduler"""
        if not SCHEDULER_AVAILABLE:
            print("APScheduler niedostepny")
            return
        
        # Job poranny
        self.scheduler.add_job(
            self.morning_job,
            CronTrigger(
                hour=self.config['morning_hour'],
                minute=self.config['morning_minute']
            ),
            id='morning_report',
            name='Poranny raport predykcji',
            replace_existing=True
        )
        
        # Job wieczorny
        self.scheduler.add_job(
            self.evening_job,
            CronTrigger(
                hour=self.config['evening_hour'],
                minute=self.config['evening_minute']
            ),
            id='evening_report',
            name='Wieczorne podsumowanie',
            replace_existing=True
        )
        
        self.scheduler.start()
        print(f"Scheduler uruchomiony")
        print(f"  - Poranny raport: {self.config['morning_hour']:02d}:{self.config['morning_minute']:02d}")
        print(f"  - Wieczorny raport: {self.config['evening_hour']:02d}:{self.config['evening_minute']:02d}")
        
        # Lista jobow
        for job in self.scheduler.get_jobs():
            print(f"  Job: {job.name} | Next run: {job.next_run_time}")
    
    def stop(self):
        """Zatrzymuje scheduler"""
        if self.scheduler:
            self.scheduler.shutdown()
            print("Scheduler zatrzymany")
    
    def run_forever(self):
        """Uruchamia scheduler i czeka"""
        self.start()
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            self.stop()


def main():
    """Glowna funkcja CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Email Scheduler dla BigOne')
    parser.add_argument('--start', action='store_true', help='Uruchom scheduler')
    parser.add_argument('--test-morning', action='store_true', help='Test job poranny')
    parser.add_argument('--test-evening', action='store_true', help='Test job wieczorny')
    parser.add_argument('--status', action='store_true', help='Pokaz status')
    
    args = parser.parse_args()
    
    scheduler = EmailScheduler()
    
    if args.test_morning:
        scheduler.morning_job()
    elif args.test_evening:
        scheduler.evening_job()
    elif args.start:
        scheduler.run_forever()
    elif args.status:
        print("Email Scheduler dla BigOne")
        print(f"APScheduler dostepny: {SCHEDULER_AVAILABLE}")
        print(f"Email notifier dostepny: {EMAIL_AVAILABLE}")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
