"""Wspólny filtr: pomijamy ligi, kluby i reprezentacje Rosji we wszystkich workflow.

Filtr działa na etapie listowania (przed pobieraniem H2H/formy/kursów),
żeby nie tracić czasu na mecze, których i tak nie gramy. Sprawdza:
  * kraj / ligę (Russia, Rosja, KHL, VHL, VTB…),
  * reprezentacje (Rosja, Russia U21, Rosja K…) — nazwa kraju w nazwie drużyny,
  * kluby — po rosyjskim mieście w nazwie (Spartak Moskwa, Rubin Kazań)
    albo po charakterystycznej nazwie klubu (Zenit, Achmat, Ak Bars…).
Działa też na slugach z URL Livesport (``spartak-moskwa``).
Wyłączenie: env ``SKIP_RUSSIA=0``.
"""
import os
import re
import unicodedata
from typing import Any, Iterable, List

_COUNTRY_LEAGUE = (
    r"russia|rosja|rosji|rosyjsk\w*|russian|rossiya|россия"
    r"|khl|vhl|mhl|vtb united league|vtb league|superliga rosji"
)

# Rosyjskie miasta (EN + polska transliteracja z Livesport, bez znaków PL).
# Celowo bez dwuznacznych nazw (np. Jarosław — jest polskie miasto).
_CITIES = (
    r"moscow|moskwa|moskva|st\.? petersburg|sankt petersburg|petersburg|kazan"
    r"|nizhny novgorod|nizny nowogrod|niznij nowgorod|yekaterinburg|ekaterinburg|jekaterynburg"
    r"|makhachkala|machaczkala|krasnodar|rostov|rostow|sochi|soczi|yaroslavl|omsk"
    r"|novosibirsk|nowosybirsk|chelyabinsk|czelabinsk|magnitogorsk|samara"
    r"|voronezh|woroniez|kaliningrad|togliatti|tolyatti|khabarovsk|chabarowsk"
    r"|vladivostok|wladywostok|ufa|perm|saratov|saratow|krasnoyarsk|krasnojarsk"
    r"|orenburg|volgograd|wolgograd|tyumen|tiumen|cherepovets|czerepowiec"
    r"|nizhnekamsk|niznekamsk|grozny|groznyj|izhevsk|izewsk|penza|irkutsk|surgut"
    r"|belgorod|bielgorod|lipetsk|lipieck|ryazan|riazan|tambov|tambow|barnaul|kursk"
)

# Charakterystyczne nazwy klubów (bez miasta w nazwie).
_CLUBS = (
    r"zenit|akhmat|achmat|krylia sovetov|krylja sowietow|skrzydla sowietow|fakel|fakiel"
    r"|pari nn|akron|baltika|ak bars|salavat yulaev|salawat julajew|severstal|siewierstal"
    r"|neftekhimik|nieftiechimik|unics|uniks|avtodor|awtodor|sibir|sybir"
    r"|ska st|ska petersburg|lokomotiv kuban|lokomotiw kuban|enisey|jenisiej|uralmash|ural"
)

_RE = re.compile(rf"\b({_COUNTRY_LEAGUE}|{_CITIES}|{_CLUBS})\b", re.IGNORECASE)


# Sporty indywidualne: Rosjan NIE pomijamy (decyzja użytkownika) — ani
# zawodników, ani turniejów/lig (np. Liga Pro w tenisie stołowym).
_INDIVIDUAL = {
    "tennis", "tenis", "table_tennis", "table-tennis", "table tennis", "tenis stolowy",
    "tenis-stolowy", "darts", "dart", "snooker", "mma", "boxing", "boks", "golf",
    "badminton", "squash", "cycling", "kolarstwo",
}
_INDIVIDUAL_URL_RE = re.compile(
    r"/(tenis|tennis|tenis-stolowy|table-tennis|dart|darts|snooker|mma|boks|boxing"
    r"|golf|badminton|squash|kolarstwo|cycling)/", re.IGNORECASE)


def is_individual_sport(sport: Any) -> bool:
    return bool(sport) and _norm(sport).strip() in {_norm(s) for s in _INDIVIDUAL}


def is_individual_url(url: Any) -> bool:
    return bool(url) and bool(_INDIVIDUAL_URL_RE.search(str(url)))


def enabled() -> bool:
    return os.environ.get("SKIP_RUSSIA", "1").strip().lower() not in ("0", "false", "no", "off")


def _norm(text: Any) -> str:
    s = str(text).replace("ł", "l").replace("Ł", "L")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[-_/]+", " ", s.lower())


def is_russian(*texts: Any) -> bool:
    """True, gdy kraj, liga, nazwa drużyny lub slug URL wskazuje Rosję."""
    if not enabled():
        return False
    return any(t and _RE.search(_norm(t)) for t in texts)


def is_russian_url(url: str) -> bool:
    """Sprawdza slugi drużyn w URL meczu Livesport (bez query i id)."""
    if not url:
        return False
    path = url.split("?", 1)[0].split("#", 1)[0]
    return is_russian(path)


def filter_rows(rows: Iterable[Any], *fields: str, label: str = "",
                sport: Any = None) -> List[Any]:
    """Odrzuca wiersze (dict lub obiekt), których pola wskazują Rosję.

    Sporty indywidualne zostają nietknięte: ``sport`` dla całej listy albo
    pole ``sport``/``sport_slug`` w wierszu.
    """
    rows = list(rows or [])
    if not enabled() or is_individual_sport(sport):
        return rows

    def _get(r, f):
        return r.get(f) if isinstance(r, dict) else getattr(r, f, None)

    def _drop(r):
        if is_individual_sport(_get(r, "sport")) or is_individual_sport(_get(r, "sport_slug")):
            return False
        return is_russian(*(_get(r, f) for f in fields))

    kept = [r for r in rows if not _drop(r)]
    dropped = len(rows) - len(kept)
    if dropped:
        print(f"   🇷🇺 Pominięto {dropped} meczów z Rosji{(' (' + label + ')') if label else ''}")
    return kept
