import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
from alert_filter import should_alert  # noqa: E402
def test_failure_and_timeout_alert():
    assert should_alert('failure', '', '')
    assert should_alert('timed_out', '', '')
def test_cancelled_depends_on_duration():
    assert should_alert('cancelled', '2026-11-01T10:00:00Z', '2026-11-01T10:40:00Z')
    assert not should_alert('cancelled', '2026-11-01T10:00:00Z', '2026-11-01T10:00:30Z')
    assert not should_alert('cancelled', '', '')
def test_success_never_alerts():
    assert not should_alert('success', '2026-11-01T10:00:00Z', '2026-11-01T11:00:00Z')
