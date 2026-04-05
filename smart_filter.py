"""
🔥 Smart Filter - Advanced Filtering Engine
-------------------------------------------
Multi-layered filtering system for H2H + Forebet + Gemini predictions

Filter Strategies:
1. BEST_PICKS: Gemini HIGH + Forebet >60% + H2H >=60%
2. HIGH_CONFIDENCE: Gemini confidence >=85% regardless of Forebet
3. VALUE_PLAYS: Away team focus + form advantage + reasonable odds
4. LOCKED_PICKS: H2H >=80% + Gemini >=70% + Forebet >=65%

Sport-Specific Rules:
- Football: Odds >= 1.80, confidence >= 75%
- Basketball: Over/Under logic, confidence >= 70%
- Volleyball: H2H >= 70%, form advantage required
- Tennis: Advanced scoring >= 50 points
- Handball/Rugby: Custom thresholds

Usage:
    python smart_filter.py outputs/livesport_h2h_2025-11-17.csv
    python smart_filter.py outputs/livesport_h2h_2025-11-17.csv --strategy best_picks
    python smart_filter.py outputs/livesport_h2h_2025-11-17.csv --sport football
"""

import sys
import argparse
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime
import json


class SmartFilter:
    """Advanced filtering engine for match predictions"""
    
    # Sport-specific thresholds
    SPORT_CONFIGS = {
        'football': {
            'min_confidence': 75,
            'min_forebet': 55,
            'min_h2h': 60,
            'min_odds': 1.80,
            'max_odds': 3.50,
        },
        'basketball': {
            'min_confidence': 70,
            'min_forebet': 60,
            'min_h2h': 60,
            'min_odds': 1.70,
            'max_odds': 4.00,
        },
        'volleyball': {
            'min_confidence': 70,
            'min_forebet': None,  # Forebet nie wspiera volleyball
            'min_h2h': 70,
            'form_required': True,
        },
        'tennis': {
            'min_confidence': 65,
            'min_advanced_score': 50,
            'h2h_weight': 0.4,
        },
        'handball': {
            'min_confidence': 70,
            'min_h2h': 65,
        },
        'rugby': {
            'min_confidence': 70,
            'min_h2h': 65,
        },
        'hockey': {
            'min_confidence': 70,
            'min_forebet': 60,
            'min_h2h': 60,
        },
        'baseball': {
            'min_confidence': 75,
            'min_forebet': 55,
            'min_h2h': 55,
            'min_odds': 1.40,
            'max_odds': 3.00,
            'pitcher_required': True,
        }
    }
    
    def __init__(self, df: pd.DataFrame):
        """Initialize filter with DataFrame"""
        self.df = df.copy()
        self.results = {
            'best_picks': [],
            'high_confidence': [],
            'value_plays': [],
            'locked_picks': [],
        }
        
    def detect_sport(self, row) -> str:
        """Detect sport from URL or other indicators"""
        url = str(row.get('match_url', ''))
        
        sport_keywords = {
            'football': ['pilka-nozna', 'football', 'soccer'],
            'basketball': ['koszykowka', 'basketball'],
            'volleyball': ['siatkowka', 'volleyball'],
            'tennis': ['tenis', 'tennis'],
            'handball': ['pilka-reczna', 'handball'],
            'rugby': ['rugby'],
            'hockey': ['hokej', 'hockey', 'ice-hockey']
        }
        
        for sport, keywords in sport_keywords.items():
            if any(kw in url.lower() for kw in keywords):
                return sport
        
        return 'unknown'
    
    def filter_best_picks(self) -> pd.DataFrame:
        """
        BEST PICKS Strategy:
        - Gemini recommendation = HIGH
        - Forebet probability > 60%
        - H2H win rate >= 60%
        - Gemini confidence >= 80%
        """
        filtered = self.df[
            (self.df['gemini_recommendation'] == 'HIGH') &
            (self.df['gemini_confidence'] >= 80) &
            (self.df['win_rate'] >= 0.60) &
            (
                (self.df['forebet_probability'] > 60) |
                (self.df['forebet_probability'].isna())  # Allow if no Forebet
            )
        ].copy()
        
        filtered['strategy'] = 'BEST_PICK'
        filtered['priority'] = 1
        return filtered
    
    def filter_high_confidence(self) -> pd.DataFrame:
        """
        HIGH CONFIDENCE Strategy:
        - Gemini confidence >= 85%
        - Recommendation = HIGH or MEDIUM
        - Ignores Forebet (AI is very confident)
        """
        filtered = self.df[
            (self.df['gemini_confidence'] >= 85) &
            (self.df['gemini_recommendation'].isin(['HIGH', 'MEDIUM']))
        ].copy()
        
        filtered['strategy'] = 'HIGH_CONFIDENCE'
        filtered['priority'] = 2
        return filtered
    
    def filter_value_plays(self) -> pd.DataFrame:
        """
        VALUE PLAYS Strategy:
        - Away team focus with form advantage
        - Reasonable odds (1.80-3.50)
        - H2H >= 60%
        - Confidence >= 70%
        """
        filtered = self.df[
            (self.df['focus_team'] == 'away') &
            (self.df['gemini_confidence'] >= 70) &
            (self.df['win_rate'] >= 0.60)
        ].copy()
        
        # Check odds if available
        if 'away_odds' in self.df.columns:
            filtered = filtered[
                (filtered['away_odds'].isna()) |
                ((filtered['away_odds'] >= 1.80) & (filtered['away_odds'] <= 3.50))
            ]
        
        filtered['strategy'] = 'VALUE_PLAY'
        filtered['priority'] = 3
        return filtered
    
    def filter_locked_picks(self) -> pd.DataFrame:
        """
        LOCKED PICKS Strategy:
        - H2H >= 80% (dominant history)
        - Gemini confidence >= 70%
        - Forebet >= 65% (if available)
        - Any recommendation except SKIP
        """
        filtered = self.df[
            (self.df['win_rate'] >= 0.80) &
            (self.df['gemini_confidence'] >= 70) &
            (self.df['gemini_recommendation'] != 'SKIP') &
            (
                (self.df['forebet_probability'] >= 65) |
                (self.df['forebet_probability'].isna())
            )
        ].copy()
        
        filtered['strategy'] = 'LOCKED_PICK'
        filtered['priority'] = 1  # Same priority as BEST_PICK
        return filtered
    
    def apply_sport_specific_rules(self, filtered_df: pd.DataFrame, sport: str = None) -> pd.DataFrame:
        """Apply sport-specific filtering rules"""
        if filtered_df.empty:
            return filtered_df
        
        result_rows = []
        
        for idx, row in filtered_df.iterrows():
            detected_sport = sport or self.detect_sport(row)
            config = self.SPORT_CONFIGS.get(detected_sport, {})
            
            # Apply sport-specific rules
            passes = True
            
            # Min confidence check
            if 'min_confidence' in config:
                if row['gemini_confidence'] < config['min_confidence']:
                    passes = False
            
            # Min Forebet check
            if 'min_forebet' in config and config['min_forebet'] is not None:
                if pd.notna(row.get('forebet_probability')):
                    if row['forebet_probability'] < config['min_forebet']:
                        passes = False
            
            # Min H2H check
            if 'min_h2h' in config:
                if row['win_rate'] * 100 < config['min_h2h']:
                    passes = False
            
            # Odds range check (football)
            if 'min_odds' in config and 'max_odds' in config:
                odds_col = 'home_odds' if row.get('focus_team') == 'home' else 'away_odds'
                if pd.notna(row.get(odds_col)):
                    odds = row[odds_col]
                    if odds < config['min_odds'] or odds > config['max_odds']:
                        passes = False
            
            # Form required check (volleyball)
            if config.get('form_required'):
                home_form = row.get('home_form', [])
                away_form = row.get('away_form', [])
                if not home_form or not away_form:
                    passes = False
            
            # Tennis advanced score check
            if 'min_advanced_score' in config:
                if pd.notna(row.get('advanced_score')):
                    if row['advanced_score'] < config['min_advanced_score']:
                        passes = False
            
            if passes:
                row_copy = row.copy()
                row_copy['sport'] = detected_sport
                result_rows.append(row_copy)
        
        if result_rows:
            return pd.DataFrame(result_rows)
        return pd.DataFrame()
    
    def run_all_strategies(self, sport: str = None) -> Dict[str, pd.DataFrame]:
        """Run all filtering strategies"""
        print("\n🔍 Running Smart Filter strategies...")
        
        strategies = {
            'best_picks': self.filter_best_picks(),
            'high_confidence': self.filter_high_confidence(),
            'value_plays': self.filter_value_plays(),
            'locked_picks': self.filter_locked_picks(),
        }
        
        # Apply sport-specific rules
        for strategy_name, strategy_df in strategies.items():
            if not strategy_df.empty:
                strategies[strategy_name] = self.apply_sport_specific_rules(strategy_df, sport)
        
        return strategies
    
    def generate_ranked_output(self, strategies: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Combine all strategies and rank by priority"""
        all_matches = []
        
        for strategy_name, df in strategies.items():
            if not df.empty:
                all_matches.append(df)
        
        if not all_matches:
            return pd.DataFrame()
        
        combined = pd.concat(all_matches, ignore_index=True)
        
        # Remove duplicates (keep highest priority)
        combined = combined.sort_values('priority').drop_duplicates(
            subset=['match_url'], keep='first'
        )
        
        # Sort by priority then confidence
        combined = combined.sort_values(
            ['priority', 'gemini_confidence'], ascending=[True, False]
        )
        
        # Add rank
        combined['rank'] = range(1, len(combined) + 1)
        
        return combined


def main():
    parser = argparse.ArgumentParser(description='🔥 Smart Filter - Advanced Match Filtering')
    parser.add_argument('csv_file', help='Path to CSV file with Gemini predictions')
    parser.add_argument('--strategy', choices=['best_picks', 'high_confidence', 'value_plays', 'locked_picks', 'all'],
                       default='all', help='Filter strategy to apply')
    parser.add_argument('--sport', choices=['football', 'basketball', 'volleyball', 'tennis', 'handball', 'rugby', 'hockey'],
                       help='Sport-specific filtering rules')
    parser.add_argument('--output', '-o', help='Output CSV file path')
    parser.add_argument('--json', action='store_true', help='Export as JSON')
    
    args = parser.parse_args()
    
    # Load CSV
    if not Path(args.csv_file).exists():
        print(f"❌ File not found: {args.csv_file}")
        sys.exit(1)
    
    print(f"\n📂 Loading: {args.csv_file}")
    df = pd.read_csv(args.csv_file)
    
    # Check for required columns
    required_cols = ['gemini_confidence', 'gemini_recommendation', 'win_rate']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        print(f"❌ Missing columns: {missing}")
        print("   This CSV doesn't have Gemini predictions!")
        sys.exit(1)
    
    print(f"✅ Loaded {len(df)} matches")
    
    # Initialize filter
    smart_filter = SmartFilter(df)
    
    # Run strategies
    if args.strategy == 'all':
        strategies = smart_filter.run_all_strategies(args.sport)
        result_df = smart_filter.generate_ranked_output(strategies)
        
        # Print summary
        print("\n" + "="*70)
        print("📊 STRATEGY SUMMARY")
        print("="*70)
        for strategy_name, strategy_df in strategies.items():
            count = len(strategy_df)
            print(f"   {strategy_name.upper():20s}: {count:3d} matches")
        print(f"\n   TOTAL UNIQUE PICKS: {len(result_df)}")
        
    else:
        # Single strategy
        strategy_func = getattr(smart_filter, f'filter_{args.strategy}')
        result_df = strategy_func()
        result_df = smart_filter.apply_sport_specific_rules(result_df, args.sport)
        print(f"\n✅ {args.strategy.upper()}: {len(result_df)} matches")
    
    # Display top picks
    if not result_df.empty:
        print("\n" + "="*70)
        print("🏆 TOP PICKS")
        print("="*70)
        
        # Build display columns dynamically
        display_cols = ['home_team', 'away_team', 'gemini_confidence', 
                       'gemini_recommendation', 'win_rate', 'strategy']
        
        # Add optional columns if they exist
        if 'rank' in result_df.columns:
            display_cols.insert(0, 'rank')
        if 'sport' in result_df.columns:
            display_cols.insert(1 if 'rank' in result_df.columns else 0, 'sport')
        if 'forebet_probability' in result_df.columns:
            display_cols.insert(-1, 'forebet_probability')
        if 'priority' in result_df.columns:
            display_cols.append('priority')
        
        display_df = result_df[display_cols].head(10)
        print(display_df.to_string(index=False))
        
        # Export
        if args.output:
            output_path = args.output
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"outputs/smart_filter_{timestamp}.csv"
        
        if args.json:
            output_path = output_path.replace('.csv', '.json')
            result_df.to_json(output_path, orient='records', indent=2)
            print(f"\n💾 Saved to: {output_path} (JSON)")
        else:
            result_df.to_csv(output_path, index=False)
            print(f"\n💾 Saved to: {output_path}")
    else:
        print("\n⚠️ No matches passed the filter criteria")


if __name__ == "__main__":
    main()
