"""
Google Sheets Exporter - Eksport predykcji do Google Sheets
============================================================

Eksportuje predykcje i statystyki do Google Sheets.
Wymaga autoryzacji przez Google API.

Użycie:
    python sheets_exporter.py --export --date 2025-12-16
    python sheets_exporter.py --sync
"""

import os
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Google API (optional)
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


class SheetsExporter:
    """
    Eksporter do Google Sheets.
    Obsługuje autoryzację, tworzenie i aktualizację arkuszy.
    """
    
    # Zakresy API
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    
    def __init__(self, credentials_file: str = 'credentials.json'):
        """
        Args:
            credentials_file: Ścieżka do pliku credentials.json
        """
        self.credentials_file = credentials_file
        self.service = None
        self.spreadsheet_id = os.getenv('GOOGLE_SHEETS_ID', '')
        
        if GOOGLE_API_AVAILABLE and os.path.exists(credentials_file):
            self._init_service()
    
    def _init_service(self):
        """Inicjalizuje Google Sheets API service"""
        try:
            credentials = service_account.Credentials.from_service_account_file(
                self.credentials_file,
                scopes=self.SCOPES
            )
            self.service = build('sheets', 'v4', credentials=credentials)
            print("Google Sheets API zainicjalizowane")
        except Exception as e:
            print(f"Blad inicjalizacji Google API: {e}")
    
    def create_spreadsheet(self, title: str = "BigOne Predictions") -> Optional[str]:
        """Tworzy nowy arkusz"""
        if not self.service:
            print("Google API niedostepne")
            return None
        
        try:
            spreadsheet = {
                'properties': {'title': title},
                'sheets': [
                    {'properties': {'title': 'Predictions'}},
                    {'properties': {'title': 'Statistics'}},
                    {'properties': {'title': 'Value Bets'}}
                ]
            }
            
            result = self.service.spreadsheets().create(body=spreadsheet).execute()
            spreadsheet_id = result.get('spreadsheetId')
            
            print(f"Utworzono arkusz: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
            return spreadsheet_id
        except Exception as e:
            print(f"Blad tworzenia arkusza: {e}")
            return None
    
    def export_predictions(self, matches: List[Dict], sheet_name: str = 'Predictions') -> bool:
        """
        Eksportuje predykcje do arkusza.
        """
        if not self.service or not self.spreadsheet_id:
            # Fallback: eksport do CSV
            return self._export_to_csv(matches)
        
        try:
            # Nagłówki
            headers = [
                'Date', 'Time', 'Home Team', 'Away Team', 'League', 'Sport',
                'H2H Win Rate', 'Forebet Pred', 'Forebet Prob',
                'Home Odds', 'Away Odds', 'Qualifies', 'Result'
            ]
            
            # Dane
            rows = [headers]
            for m in matches:
                h2h = m.get('h2h', {})
                forebet = m.get('forebet', {})
                odds = m.get('odds', {})
                
                rows.append([
                    m.get('date', ''),
                    m.get('time', ''),
                    m.get('homeTeam', m.get('home_team', '')),
                    m.get('awayTeam', m.get('away_team', '')),
                    m.get('league', ''),
                    m.get('sport', ''),
                    h2h.get('winRate', ''),
                    forebet.get('prediction', ''),
                    forebet.get('probability', ''),
                    odds.get('home', ''),
                    odds.get('away', ''),
                    'Yes' if m.get('qualifies') else 'No',
                    m.get('actual_result', '')
                ])
            
            # Update arkusza
            range_name = f'{sheet_name}!A1'
            body = {'values': rows}
            
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption='RAW',
                body=body
            ).execute()
            
            print(f"Wyeksportowano {len(matches)} predykcji do Google Sheets")
            return True
            
        except Exception as e:
            print(f"Blad eksportu: {e}")
            return self._export_to_csv(matches)
    
    def export_value_bets(self, value_bets: List[Dict], sheet_name: str = 'Value Bets') -> bool:
        """Eksportuje value bets do arkusza"""
        if not self.service or not self.spreadsheet_id:
            return self._export_value_bets_csv(value_bets)
        
        try:
            headers = [
                'Home Team', 'Away Team', 'Prediction', 'Odds',
                'Probability', 'Implied Prob', 'EV', 'Edge', 'Kelly %'
            ]
            
            rows = [headers]
            for vb in value_bets:
                rows.append([
                    vb.get('home_team', ''),
                    vb.get('away_team', ''),
                    vb.get('prediction', ''),
                    vb.get('odds', ''),
                    vb.get('probability', ''),
                    vb.get('implied_prob', ''),
                    vb.get('expected_value', ''),
                    vb.get('edge', ''),
                    vb.get('kelly', '')
                ])
            
            range_name = f'{sheet_name}!A1'
            body = {'values': rows}
            
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption='RAW',
                body=body
            ).execute()
            
            print(f"Wyeksportowano {len(value_bets)} value bets")
            return True
            
        except Exception as e:
            print(f"Blad eksportu value bets: {e}")
            return False
    
    def _export_to_csv(self, matches: List[Dict]) -> bool:
        """Fallback: eksport do CSV"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            filename = f'exports/predictions_{today}.csv'
            
            os.makedirs('exports', exist_ok=True)
            
            headers = ['Date', 'Time', 'Home Team', 'Away Team', 'League', 'Sport', 
                      'H2H Win Rate', 'Forebet', 'Qualifies']
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(','.join(headers) + '\n')
                
                for m in matches:
                    h2h = m.get('h2h', {})
                    forebet = m.get('forebet', {})
                    
                    row = [
                        m.get('date', ''),
                        m.get('time', ''),
                        m.get('homeTeam', m.get('home_team', '')),
                        m.get('awayTeam', m.get('away_team', '')),
                        m.get('league', ''),
                        m.get('sport', ''),
                        str(h2h.get('winRate', '')),
                        forebet.get('prediction', ''),
                        'Yes' if m.get('qualifies') else 'No'
                    ]
                    f.write(','.join([f'"{v}"' for v in row]) + '\n')
            
            print(f"Wyeksportowano do {filename}")
            return True
            
        except Exception as e:
            print(f"Blad eksportu CSV: {e}")
            return False
    
    def _export_value_bets_csv(self, value_bets: List[Dict]) -> bool:
        """Eksport value bets do CSV"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            filename = f'exports/value_bets_{today}.csv'
            
            os.makedirs('exports', exist_ok=True)
            
            with open(filename, 'w', encoding='utf-8') as f:
                headers = ['Home', 'Away', 'Prediction', 'Odds', 'EV', 'Edge', 'Kelly']
                f.write(','.join(headers) + '\n')
                
                for vb in value_bets:
                    row = [
                        vb.get('home_team', ''),
                        vb.get('away_team', ''),
                        vb.get('prediction', ''),
                        str(vb.get('odds', '')),
                        str(vb.get('expected_value', '')),
                        str(vb.get('edge', '')),
                        str(vb.get('kelly', ''))
                    ]
                    f.write(','.join([f'"{v}"' for v in row]) + '\n')
            
            print(f"Wyeksportowano do {filename}")
            return True
            
        except Exception as e:
            print(f"Blad eksportu CSV: {e}")
            return False
    
    def load_matches(self, date: str = None) -> List[Dict]:
        """Wczytuje mecze z plików"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        matches = []
        outputs_dir = os.path.join(os.path.dirname(__file__), 'outputs')
        
        for sport in ['football', 'basketball', 'volleyball', 'handball', 'hockey', 'tennis']:
            filepath = os.path.join(outputs_dir, f'matches_{date}_{sport}.json')
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for m in data.get('matches', []):
                            m['sport'] = sport
                            m['date'] = date
                            matches.append(m)
                except Exception:
                    pass
        
        return matches


def main():
    """Główna funkcja CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Google Sheets Exporter dla BigOne')
    parser.add_argument('--export', action='store_true', help='Eksportuj predykcje')
    parser.add_argument('--value-bets', action='store_true', help='Eksportuj value bets')
    parser.add_argument('--date', type=str, help='Data (YYYY-MM-DD)')
    parser.add_argument('--create', action='store_true', help='Utworz nowy arkusz')
    parser.add_argument('--csv', action='store_true', help='Eksport tylko do CSV')
    
    args = parser.parse_args()
    
    exporter = SheetsExporter()
    
    if args.create:
        exporter.create_spreadsheet()
        return
    
    if args.export or args.csv:
        matches = exporter.load_matches(args.date)
        print(f"Wczytano {len(matches)} meczow")
        
        if args.csv or not exporter.service:
            exporter._export_to_csv(matches)
        else:
            exporter.export_predictions(matches)
    
    if args.value_bets:
        try:
            from value_calculator import ValueCalculator
            
            calculator = ValueCalculator()
            matches = exporter.load_matches(args.date)
            value_bets = calculator.analyze_matches(matches)
            
            vb_dicts = [vb.to_dict() for vb in value_bets]
            
            if args.csv or not exporter.service:
                exporter._export_value_bets_csv(vb_dicts)
            else:
                exporter.export_value_bets(vb_dicts)
                
        except ImportError:
            print("value_calculator.py niedostepny")


if __name__ == '__main__':
    main()
