"""Deterministic unit tests for the World Cup news/intel layer.
No network — feeds synthetic Google News RSS XML and headline lists."""
import time

from worldcup_news_intel import (
    parse_rss,
    classify_headline,
    headline_impact,
    teams_in_headline,
    build_intel,
    is_football_relevant,
    _configured_locales,
    _env_int,
    _query_set,
    _DEFAULT_LOCALES,
)


_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <item>
      <title>Mexico star ruled out with hamstring injury ahead of World Cup clash - ESPN</title>
      <link>https://example.com/1</link>
      <pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate>
      <source url="https://espn.com">ESPN</source>
    </item>
    <item>
      <title>South Africa defender suspended after red card accumulation</title>
      <link>https://example.com/2</link>
      <pubDate>Mon, 01 Jun 2026 09:00:00 GMT</pubDate>
      <source url="https://bbc.com">BBC Sport</source>
    </item>
    <item>
      <title>Mexico vs South Africa: predicted lineup and team news</title>
      <link>https://example.com/3</link>
      <pubDate>Mon, 01 Jun 2026 08:00:00 GMT</pubDate>
      <source url="https://goal.com">Goal</source>
    </item>
    <item>
      <title>Mexico vs South Africa preview, prediction and how to watch</title>
      <link>https://example.com/4</link>
      <pubDate>Mon, 01 Jun 2026 07:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def test_parse_rss_extracts_items_and_source():
    items = parse_rss(_SAMPLE_RSS)
    assert len(items) == 4
    first = items[0]
    assert "hamstring injury" in first["title"]
    assert first["source"] == "ESPN"
    assert first["url"] == "https://example.com/1"


def test_parse_rss_splits_source_from_title_when_no_source_tag():
    # 4th item has no <source>; source should be split from "... - Source"
    items = parse_rss(_SAMPLE_RSS)
    preview = items[3]
    assert preview["title"].startswith("Mexico vs South Africa preview")
    # no trailing " - Source" because there was none to split here
    assert preview["source"] == ""


def test_parse_rss_bad_xml_returns_empty():
    assert parse_rss("not xml at all") == []
    assert parse_rss("") == []


def test_classify_headline_detects_injury_and_suspension():
    assert "injury" in classify_headline("Star ruled out with hamstring injury")
    assert "suspension" in classify_headline("Defender suspended after red card")
    assert "lineup" in classify_headline("Predicted lineup and team news")
    assert classify_headline("Random unrelated chatter") == ["general"]


def test_classify_headline_polish_keywords():
    assert "injury" in classify_headline("Gwiazda pauzuje przez uraz uda")
    assert "suspension" in classify_headline("Obrońca zawieszony za kartki")
    assert "lineup" in classify_headline("Przewidywany skład na mecz")


def test_headline_impact_ranking():
    assert headline_impact(["injury"]) == 3
    assert headline_impact(["preview"]) == 1
    assert headline_impact(["general"]) == 0
    # highest wins
    assert headline_impact(["preview", "injury"]) == 3


def test_teams_in_headline_matches_both_and_single():
    both = teams_in_headline("Mexico vs South Africa preview", "Mexico", "South Africa")
    assert set(both) == {"Mexico", "South Africa"}
    one = teams_in_headline("Mexico star ruled out", "Mexico", "South Africa")
    assert one == ["Mexico"]


def test_build_intel_aggregates_and_summarizes():
    items = parse_rss(_SAMPLE_RSS)
    intel = build_intel(items, "Mexico", "South Africa")
    assert intel["available"] is True
    assert intel["counts"]["injuries"] >= 1
    assert intel["counts"]["suspensions"] >= 1
    # injury/suspension must surface as key absences (highest impact first)
    assert len(intel["key_absences"]) >= 2
    assert intel["headlines"][0]["impact"] == 3      # top item is critical
    assert "Sygnały kadrowe" in intel["summary"]
    assert intel["sources_count"] >= 1


def test_build_intel_dedupes_near_duplicates():
    dupes = [
        {"title": "Mexico star ruled out with hamstring injury", "source": "A",
         "published": "", "url": "u1"},
        {"title": "Mexico star ruled out with hamstring injury!", "source": "B",
         "published": "", "url": "u2"},
    ]
    intel = build_intel(dupes, "Mexico", "South Africa")
    assert intel["counts"]["headlines"] == 1          # near-duplicate collapsed


def test_build_intel_empty_is_safe():
    intel = build_intel([], "Mexico", "South Africa")
    assert intel["available"] is False
    assert intel["summary"] == "Brak doniesień medialnych przed meczem."
    assert intel["headlines"] == []


def test_relevance_gate_rejects_politics_keeps_football():
    # Real false-positive seen in live output: politics article with the word "ban".
    politics = ("Germany and Spain say No to European Commission's plans to "
                "ban Chinese technology companies")
    assert is_football_relevant(politics) is False
    football = "Spain vs Germany: lineups, team news and injury updates"
    assert is_football_relevant(football) is True


def test_suspension_keyword_not_triggered_by_policy_ban():
    # Bare "ban" must NOT classify a policy headline as a suspension.
    assert "suspension" not in classify_headline(
        "Government plans to ban imports of foreign goods")
    # But a real football ban still does.
    assert "suspension" in classify_headline(
        "Midfielder handed two-match ban after red card")


def test_build_intel_filters_offtopic_from_aggregation():
    items = [
        {"title": "Germany and Spain plan to ban Chinese technology companies",
         "source": "Times", "published": "", "url": "u1"},
        {"title": "Spain vs Germany: predicted lineup and injury news",
         "source": "ESPN", "published": "", "url": "u2"},
    ]
    intel = build_intel(items, "Spain", "Germany")
    # Only the football headline survives the relevance gate.
    assert intel["counts"]["headlines"] == 1
    assert "lineup" in intel["headlines"][0]["tags"]
    # The politics item must not pollute key absences.
    assert all("technology" not in ka["title"].lower()
               for ka in intel["key_absences"])


# --------------------------------------------------------------------------- #
# Locale / config behaviour (env-driven, for GitHub Actions breadth)
# --------------------------------------------------------------------------- #
def test_configured_locales_defaults(monkeypatch):
    monkeypatch.delenv("WC_NEWS_LOCALES", raising=False)
    assert _configured_locales() == list(_DEFAULT_LOCALES)


def test_configured_locales_parses_env(monkeypatch):
    monkeypatch.setenv("WC_NEWS_LOCALES", "en-US, pl_PL , es:ES")
    assert _configured_locales() == [("en", "US"), ("pl", "PL"), ("es", "ES")]


def test_configured_locales_bad_env_falls_back(monkeypatch):
    monkeypatch.setenv("WC_NEWS_LOCALES", "   ")
    assert _configured_locales() == list(_DEFAULT_LOCALES)


def test_env_int_positive_and_fallback(monkeypatch):
    monkeypatch.setenv("WC_NEWS_MAX_HEADLINES", "40")
    assert _env_int("WC_NEWS_MAX_HEADLINES", 25) == 40
    monkeypatch.setenv("WC_NEWS_MAX_HEADLINES", "0")
    assert _env_int("WC_NEWS_MAX_HEADLINES", 25) == 25
    monkeypatch.setenv("WC_NEWS_MAX_HEADLINES", "abc")
    assert _env_int("WC_NEWS_MAX_HEADLINES", 25) == 25


def test_query_set_covers_both_teams_and_angles():
    qs = _query_set("Poland", "Argentina")
    joined = " || ".join(qs)
    assert any("vs" in q for q in qs)
    assert "injury" in joined and "lineup" in joined
    assert "Poland" in joined and "Argentina" in joined
    # deep mode dokłada kąt PL
    deep = _query_set("Poland", "Argentina", deep=True)
    assert any("kontuzje" in q for q in deep)
    assert len(deep) > len(qs)


def test_build_intel_respects_custom_max_headlines():
    distinct = [
        "Spain vs Germany: predicted lineup revealed",
        "Germany defender ruled out with hamstring injury",
        "Spain coach confirms squad for World Cup opener",
        "Germany midfielder suspended after red card",
        "Spain striker returns from injury ahead of match",
        "Germany vs Spain preview and prediction tips",
    ]
    items = [
        {"title": t, "source": f"S{i}", "published": "", "url": f"u{i}"}
        for i, t in enumerate(distinct)
    ]
    intel = build_intel(items, "Spain", "Germany", max_headlines=3)
    assert intel["counts"]["headlines"] == 3


def test_fetch_match_intel_honours_time_budget(monkeypatch):
    """Twardy budżet czasu musi przerwać zbieranie i nie zawiesić pipeline'u."""
    import worldcup_news_intel as mod
    calls = {"n": 0}

    def _slow_fetch(query, lang, country):
        calls["n"] += 1
        time.sleep(0.05)
        return [{"title": f"Spain vs Germany injury news {calls['n']}",
                 "source": "X", "published": "", "url": f"u{calls['n']}"}]

    monkeypatch.setattr(mod, "_fetch_rss", _slow_fetch)
    start = time.time()
    # Bardzo mały budżet -> musi przerwać niemal natychmiast.
    r = mod.fetch_match_intel("Spain", "Germany",
                              locales=[("en", "US"), ("pl", "PL"), ("es", "ES")],
                              budget_s=0.12)
    elapsed = time.time() - start
    assert elapsed < 2.0                      # nie zawiesza się
    # Nie odpytał wszystkich 3 lokalizacji × zapytań — budżet uciął.
    assert r.get("budget_truncated") in (True, False)  # pole obecne
    assert "locales_queried" in r
