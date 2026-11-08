import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import api_server  # noqa: E402
import top_feed  # noqa: E402

DAY = datetime.now().strftime('%Y-%m-%d')


def _fake_top(**_k):
    picks = [
        {'odds': 2.0, 'odds2': 2.5, 'result': {'status': 'won'}},
        {'odds': 2.0, 'odds2': 2.5, 'result': {'status': 'lost'}},
    ]
    return {'days': [{'date': DAY, 'picks': picks}], 'summary': {'settled': 2},
            'bySport': {'football': {'settled': 2, 'won': 1}, 'tennis': {'settled': 0, 'won': 0}}}


def test_roi_uses_odds2_and_sport_accuracy(tmp_path, monkeypatch):
    monkeypatch.setattr(top_feed, 'load_top', _fake_top)
    rec = api_server._top_track_record()
    assert rec['accuracy_7d'] == 50.0
    assert rec['roi_7d'] == 25.0  # (2.5 - 2) / 2
    assert rec['by_sport_accuracy'] == {'football': 0.5, 'tennis': None}

    import json
    (tmp_path / f'matches_{DAY}_football.json').write_text(
        json.dumps([{'home_team': 'A', 'away_team': 'B'}]), encoding='utf-8')
    monkeypatch.setattr(api_server, 'RESULTS_DIR', str(tmp_path))
    api_server.app.config['TESTING'] = True
    body = api_server.app.test_client().get('/api/stats?days=1').get_json()
    fb = [s for s in body['sport_breakdown'] if s['sport'] == 'football'][0]
    assert fb['accuracy'] == 0.5
    assert 'by_sport_accuracy' not in body
