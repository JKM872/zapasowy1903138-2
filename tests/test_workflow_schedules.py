"""C10: every workflow parses, no cron on minute 0/30, schedule checks match crons."""
import glob
import os
import re

import yaml

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')
FILES = sorted(glob.glob(os.path.join(WF, '*.yml')))


def _load(path):
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    doc = yaml.safe_load(text)
    on = doc.get('on', doc.get(True)) or {}
    crons = [c['cron'] for c in (on.get('schedule') or []) if isinstance(on, dict)]
    return text, crons


def test_files_exist():
    assert FILES


def test_all_parse_and_no_round_minutes():
    for path in FILES:
        _, crons = _load(path)
        for cron in crons:
            minute = cron.split()[0]
            for part in minute.split(','):
                assert part not in ('0', '30'), f'{os.path.basename(path)}: {cron}'


def test_schedule_strings_match_crons():
    for path in FILES:
        text, crons = _load(path)
        for m in re.finditer(r"github\.event\.schedule \}\}\"? (?:=|in)[^'\"]*['\"]([^'\"]+)['\"]", text):
            assert m.group(1) in crons, f'{os.path.basename(path)}: {m.group(1)}'
        for m in re.finditer(r"^\s*'([^']+)'\) MODE=", text, re.M):
            assert m.group(1) in crons, f'{os.path.basename(path)}: {m.group(1)}'
