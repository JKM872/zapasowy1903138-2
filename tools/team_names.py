"""Team / player name folding for team history (design K6).

One rule set shared by the index builder and the /api/teams endpoint, so a
name folds the same way when it is stored and when it is asked for.

- NFKD, accents stripped, lowercase; ``-`` ``.`` ``'`` become spaces; spaces
  collapsed. ``Al-Hilal`` == ``Al Hilal``, ``(SAU)`` == ``(Sau)``.
- Suffixes that name a DIFFERENT team are kept as tokens: women ``w``/``k``/
  ``women``, reserves ``ii``/``b``, youth ``u19``/``u23``, country tags
  ``(pol)``. ``Arsenal`` and ``Arsenal W`` never fold together. The three
  women's markers are one token ``w`` (Forebet writes ``W``, Livesport ``K``),
  so ``Arsenal W`` == ``Arsenal K`` != ``Arsenal``.
- Tennis / table tennis singles fold to ``surname initials``: Livesport
  ``Djokovic N.``, Forebet ``N. Djokovic`` and a full ``Novak Djokovic`` all
  become ``djokovic n``.
- Doubles ``A/B`` keep both players: ``djokovic n/sinner j``.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

# Sports whose competitors are people, written either "Surname I." or "I. Surname".
PLAYER_SPORTS = frozenset({'tennis', 'table_tennis'})

_SEP = re.compile(r"[-.'\u2019`_]")
_OTHER = re.compile(r'[^a-z0-9()/& ]+')
_TAG = re.compile(r'^\([a-z0-9 ]+\)$')
# Letters NFKD does not decompose (they would be dropped: "Białystok" -> "biaystok").
_TRANSLIT = str.maketrans({'ł': 'l', 'Ł': 'L', 'ø': 'o', 'Ø': 'O', 'æ': 'ae', 'Æ': 'AE',
                           'œ': 'oe', 'Œ': 'OE', 'ß': 'ss', 'đ': 'd', 'Đ': 'D', 'ð': 'd',
                           'Ð': 'D', 'þ': 'th', 'Þ': 'TH', 'ı': 'i', 'ħ': 'h', 'Ħ': 'H'})


def _base(name: Any) -> str:
    s = str(name or '').translate(_TRANSLIT)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = _SEP.sub(' ', s)
    s = _OTHER.sub(' ', s)
    s = re.sub(r'\s*\(\s*', ' (', s)
    s = re.sub(r'\s*\)', ')', s)
    s = re.sub(r'\s*/\s*', '/', s)
    return re.sub(r'\s+', ' ', s).strip()


def _player(s: str) -> str:
    """'n djokovic' / 'djokovic n' / 'novak djokovic' -> 'djokovic n'."""
    tokens = s.split()
    tags = [t for t in tokens if _TAG.match(t)]
    words = [t for t in tokens if not _TAG.match(t)]
    if len(words) >= 2:
        if len(words[-1]) == 1:
            pass                                       # already "surname i"
        elif len(words[0]) == 1:
            i = 0
            while i < len(words) and len(words[i]) == 1:
                i += 1
            words = words[i:] + words[:i]              # "f a gomez" -> "gomez f a"
        else:
            words = words[1:] + [words[0][0]]          # "lloyd harris" -> "harris l"
    return ' '.join(words + tags)


def _women(s: str) -> str:
    """Women's marker in one spelling: Livesport 'K' (kobiety) / 'Women' and
    Forebet 'W' all become a trailing 'w' (before a country tag)."""
    tokens = s.split()
    tags = []
    while tokens and _TAG.match(tokens[-1]):
        tags.insert(0, tokens.pop())
    if len(tokens) >= 2 and tokens[-1] in ('k', 'women'):
        tokens[-1] = 'w'
    return ' '.join(tokens + tags)


def fold(name: Any, sport: Any = None) -> str:
    """Sport-scoped folded key of a team or player name ('' for empty input)."""
    s = _base(name)
    if not s:
        return ''
    if str(sport or '').lower() in PLAYER_SPORTS:
        if '/' in s:
            return '/'.join(_player(p.strip()) for p in s.split('/') if p.strip())
        return _player(s)
    return _women(s)


def player_alternative(name: Any, sport: Any) -> str:
    """Second reading of a full player name written surname first
    ('Hajek Miroslav' -> 'hajek m'); '' when not applicable."""
    if str(sport or '').lower() not in PLAYER_SPORTS:
        return ''
    s = _base(name)
    words = [t for t in s.split() if not _TAG.match(t)]
    if '/' in s or len(words) < 2 or any(len(w) == 1 for w in words):
        return ''
    return ' '.join(words[:-1] + [words[-1][0]])


def strip_country_tag(key: str) -> str:
    """'legia warszawa (pol)' -> 'legia warszawa' (unchanged when no tag)."""
    return re.sub(r'\s*\([a-z0-9 ]+\)$', '', key).strip()


def split_match(match: Any) -> tuple:
    """'A vs B' -> ('A', 'B'); ('A vs B', '') when there is no separator."""
    parts = re.split(r'\s+vs\.?\s+', str(match or ''), maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (str(match or ''), '')
