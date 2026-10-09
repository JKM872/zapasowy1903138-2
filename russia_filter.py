"""Wspólny filtr: pomijamy ligi rosyjskie we wszystkich workflow.

Filtr działa na etapie listowania (przed pobieraniem H2H/formy/kursów),
żeby nie tracić czasu na mecze, których i tak nie gramy.
Wyłączenie: env ``SKIP_RUSSIA=0``.
"""
import os
import re
from typing import Any, Iterable, List

_RUSSIA_RE = re.compile(
    r"\b(russia|rosja|rosji|russian|rosyjsk\w*|россия)\b"
    # ligi rosyjskie bez nazwy kraju w tytule (hokej, koszykówka)
    r"|\b(khl|vhl|mhl|vtb united league|vtb league)\b",
    re.IGNORECASE,
)


def enabled() -> bool:
    return os.environ.get("SKIP_RUSSIA", "1").strip().lower() not in ("0", "false", "no", "off")


def is_russian(*texts: Any) -> bool:
    """True, gdy którykolwiek z tekstów (kraj, liga, nagłówek) wskazuje Rosję."""
    if not enabled():
        return False
    for t in texts:
        if t and _RUSSIA_RE.search(str(t)):
            return True
    return False


def filter_rows(rows: Iterable[Any], *fields: str, label: str = "") -> List[Any]:
    """Odrzuca wiersze (dict lub obiekt), których pola wskazują Rosję."""
    rows = list(rows or [])
    if not enabled():
        return rows

    def _get(r, f):
        return r.get(f) if isinstance(r, dict) else getattr(r, f, None)

    kept = [r for r in rows if not is_russian(*(_get(r, f) for f in fields))]
    dropped = len(rows) - len(kept)
    if dropped:
        print(f"   🇷🇺 Pominięto {dropped} meczów z lig rosyjskich{(' (' + label + ')') if label else ''}")
    return kept
