import json
import os

from tools import build_site as bs

DAY = '2026-10-20'


def _w(d, name, data):
    with open(os.path.join(d, name), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def _fixture(tmp_path):
    res = tmp_path / 'results'
    res.mkdir()
    _w(res, f'top_{DAY}.json', [
        {'sport': 'hockey', 'time': '01:00', 'league': 'AHL',
         'match': '<script>alert(1)</script> FC vs Utica', 'pick': 'Utica', 'odds': 2.25,
         'grade': 'A', 'form': 'WWWLW (12 pkt) vs DWWLW (10 pkt)', 'h2h': '4-1',
         'fanvote': '79%', 'signals': '6/6 za',
         'superbet': {'url': 'https://superbet.pl/kursy/hokej/x-vs-y-1'}}])
    _w(res, f'ai_analyst_{DAY}.json', [
        {'match': 'A & B vs C', 'pick': 'C', 'odds': 1.8, 'sport': 'football',
         'verdict': 'GRAJ', 'confidence': 4, 'reason': 'Dobra forma', 'risks': ['Kontuzja'],
         'source': 'TOP'}])
    _w(res, f'twierdza_{DAY}.json', [
        {'sport': 'basketball', 'time': '04:15', 'match': 'Astros vs Mineros', 'league': 'LBP',
         'pick': 'Astros', 'odds': 1.38, 'forebet': 74, 'fanvote': 91, 'form': 'WWWWW',
         'venue': 'WWWWL', 'grade': 'A', 'injuryLine': 'Mineros: brak lidera'}])
    _w(res, 'forebet_settled.json', {
        f'{DAY}|basketball|Astros|Mineros': {'status': 'settled', 'winner': 'home'},
        f'{DAY}|football|A & B|C': {'status': 'settled', 'winner': 'home'}})
    return res


def test_renders_fixture_and_escapes(tmp_path):
    res = _fixture(tmp_path)
    out = tmp_path / 'site'
    bs.build(str(res), str(out))
    idx = (out / 'index.html').read_text(encoding='utf-8')
    assert '<script>alert(1)</script>' not in idx
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in idx
    assert 'A &amp; B vs C' in idx
    assert 'GRAJ' in idx and '★★★★☆' in idx
    assert idx.index('Analityk AI') < idx.index('TOP') < idx.index('Twierdza')
    assert 'class="W"' in idx and 'width:79%' in idx
    assert 'Mineros: brak lidera' in idx and 'superbet.pl' in idx
    assert bs.FOOTER in idx
    assert (out / 'dzien' / f'{DAY}.html').exists()


def test_history_settlement(tmp_path):
    res = _fixture(tmp_path)
    cats = bs.history(str(res), [DAY])
    assert cats['Twierdza'] == [{'day': DAY, 'n': 1, 'hits': 1, 'profit': 0.38}]
    assert cats['AI GRAJ'] == [{'day': DAY, 'n': 1, 'hits': 0, 'profit': -1.0}]
    assert cats['TOP'] == []
    bs.build(str(res), str(tmp_path / 'site'))
    h = (tmp_path / 'site' / 'historia.html').read_text(encoding='utf-8')
    assert 'Mała próba' in h and '<svg' in h


def test_missing_files(tmp_path):
    res = tmp_path / 'results'
    res.mkdir()
    _w(res, f'top_{DAY}.json', {'broken': True})
    (res / f'twierdza_{DAY}.json').write_text('{not json', encoding='utf-8')
    out = tmp_path / 'site'
    bs.build(str(res), str(out))
    assert 'Brak danych' in (out / 'index.html').read_text(encoding='utf-8')
    empty = tmp_path / 'none'
    empty.mkdir()
    bs.build(str(empty), str(tmp_path / 's2'))
    assert (tmp_path / 's2' / 'historia.html').exists()
