import forebet_listing as fbl
import forebet_pipeline as fp


def test_norm_time_12h_and_24h():
    assert fbl._norm_time('10/10/2026 1:10 pm') == '13:10'
    assert fbl._norm_time('1:10 PM') == '13:10'
    assert fbl._norm_time('12:05 am') == '00:05'
    assert fbl._norm_time('12:40 pm') == '12:40'
    assert fbl._norm_time('9:05') == '09:05'
    assert fbl._norm_time('19:30') == '19:30'
    assert fbl._norm_time('brak') is None


def test_repair_12h_without_ampm():
    html = [{'match_time': t} for t in ('10:05', '11:55', '12:40', '01:10', '02:00', '09:35')]
    fbl._repair_12h_clock(html, [])
    assert [m['match_time'] for m in html] == ['10:05', '11:55', '12:40', '13:10', '14:00', '21:35']


def test_repair_prefers_json_time_and_leaves_24h_alone():
    html = [{'forebet_id': 'a', 'match_time': '01:10'}, {'match_time': '19:00'}, {'match_time': '02:00'}]
    fbl._repair_12h_clock(html, [{'forebet_id': 'a', 'match_time': '13:10'}])
    assert [m['match_time'] for m in html] == ['13:10', '19:00', '02:00']


def test_localize_utc_to_warsaw():
    r = fp.localize_forebet_time({'match_date': '2026-10-10', 'match_time': '10:00'})
    assert (r['match_date'], r['match_time'], r['match_time_utc']) == ('2026-10-10', '12:00', '10:00')
    r = fp.localize_forebet_time({'match_date': '2026-10-10', 'match_time': '23:30'})
    assert (r['match_date'], r['match_time']) == ('2026-10-11', '01:30')
    assert fp.localize_forebet_time(r)['match_time'] == '01:30'  # idempotentne
    r = fp.localize_forebet_time({'match_date': '2026-12-10', 'match_time': '10:00'})
    assert r['match_time'] == '11:00'  # czas zimowy
