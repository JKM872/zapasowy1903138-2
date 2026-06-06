# -*- coding: utf-8 -*-
"""
🎯 OddsPortal / Betexplorer odds for table tennis — STAGE 1: diagnostics
========================================================================

Pinnacle/Livesport only price a handful of pro table-tennis matches, so the
amateur AiScore events (TT Cup, Liga Pro, Setka) end up without odds. OddsPortal
and its sister site Betexplorer DO cover those leagues from many bookmakers.

This module is STAGE 1 of a two-stage plan:

  • STAGE 1 (this file): a GENERIC Cloudflare-bypassing fetcher (FlareSolverr,
    which executes JS, with curl_cffi fallback) plus a diagnostic routine that
    fetches OddsPortal + Betexplorer table-tennis pages (and per-player search
    results) and DUMPS the raw rendered HTML to ``debug_html/``. The first CI
    run uploads those dumps as artifacts so we can see the real DOM.

  • STAGE 2 (next): write precise odds parsers against those captured fixtures,
    add tests, and wire the winner in as the primary odds source.

Nothing here blocks the pipeline: every function is best-effort and returns
quietly on failure. Enable the dump with env ``TT_ODDS_DIAGNOSTIC=1``.

The existing ``cloudflare_bypass._try_flaresolverr`` is hardcoded to validate
*Forebet* content, so it cannot be reused for these sites — hence the generic
fetcher below.
"""

from __future__ import annotations

import os
import re
import time
from typing import List, Optional

OUT_DIR = "debug_html"

ODDSPORTAL_TT = "https://www.oddsportal.com/table-tennis/"
BETEXPLORER_TT = "https://www.betexplorer.com/table-tennis/"


def _is_ci() -> bool:
    return os.getenv("CI") == "true" or os.getenv("GITHUB_ACTIONS") == "true"


def _looks_like_challenge(html: Optional[str]) -> bool:
    if not html:
        return True
    low = html.lower()
    return (
        "just a moment" in low
        or "checking your browser" in low
        or "verifying you are human" in low
        or "loading-verifying" in html
        or "lds-ring" in html
        or "enable javascript and cookies" in low
    )


# ---------------------------------------------------------------------------
# Generic Cloudflare-bypassing fetcher (NOT Forebet-specific)
# ---------------------------------------------------------------------------

def _flaresolverr_get(url: str, max_timeout_ms: int = 60000) -> Optional[str]:
    """Fetch a URL through FlareSolverr (real browser, executes JS, solves CF).

    Generic: returns the rendered HTML on success, regardless of site.
    """
    fs_url = os.getenv("FLARESOLVERR_URL", "").strip()
    if not fs_url:
        return None
    try:
        import requests
        resp = requests.post(
            fs_url,
            headers={"Content-Type": "application/json"},
            json={"cmd": "request.get", "url": url, "maxTimeout": max_timeout_ms},
            timeout=max_timeout_ms // 1000 + 60,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("status") != "ok":
            return None
        html = (data.get("solution") or {}).get("response", "")
        return html or None
    except Exception:
        return None


def _curl_get(url: str, timeout: int = 25) -> Optional[str]:
    """Fetch a URL with curl_cffi (Chrome TLS impersonation)."""
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, impersonate="chrome131", timeout=timeout, allow_redirects=True,
                     headers={"Accept-Language": "pl,en;q=0.9"})
        if r.status_code == 200:
            return r.text
    except Exception:
        return None
    return None


def cf_get(url: str) -> Optional[str]:
    """Best-effort CF-bypassing GET: FlareSolverr first (JS render), then curl_cffi.

    Returns rendered HTML, or None if everything failed / only a CF challenge
    came back.
    """
    # FlareSolverr renders JS — required for OddsPortal/Betexplorer odds.
    html = _flaresolverr_get(url)
    if html and not _looks_like_challenge(html):
        return html
    html = _curl_get(url)
    if html and not _looks_like_challenge(html):
        return html
    return None


# ---------------------------------------------------------------------------
# Diagnostics: dump raw HTML for parser development
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _surnames(name: str) -> List[str]:
    """Crude surname tokens (>=4 chars) for building search queries."""
    cleaned = re.sub(r"[^\w\s]", " ", name or "", flags=re.UNICODE).lower()
    return [t for t in cleaned.split() if len(t) >= 4]


def _save(html: Optional[str], path: str) -> bool:
    if not html:
        return False
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        return True
    except Exception:
        return False


def dump_diagnostics(players: List[str], date_str: str,
                     out_dir: str = OUT_DIR, max_search: int = 3) -> List[str]:
    """Fetch OddsPortal + Betexplorer TT pages (+ a few player searches) and dump
    the raw rendered HTML to ``out_dir`` for later parser development.

    Returns the list of files written. Best-effort, never raises.
    """
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []

    targets = [
        ("oddsportal_tt_upcoming", ODDSPORTAL_TT),
        ("betexplorer_tt", BETEXPLORER_TT),
    ]
    # Per-player search pages (these usually link straight to the match page).
    seen_q = set()
    for p in players:
        sn = _surnames(p)
        if not sn:
            continue
        q = "+".join(sn[:2])
        if q in seen_q:
            continue
        seen_q.add(q)
        targets.append((f"oddsportal_search_{_slug(p)}",
                        f"https://www.oddsportal.com/search/results/{q}/"))
        targets.append((f"betexplorer_search_{_slug(p)}",
                        f"https://www.betexplorer.com/search/?q={q}"))
        if len(seen_q) >= max_search:
            break

    print(f"   🔬 OddsPortal/Betexplorer diagnostyka: pobieram {len(targets)} stron...")
    for name, url in targets:
        html = cf_get(url)
        path = os.path.join(out_dir, f"{name}_{date_str}.html")
        if _save(html, path):
            # Quick signal: does the dump contain decimal-odds-looking tokens?
            odds_like = len(re.findall(r">\s*\d\.\d{2}\s*<", html or "")) if html else 0
            written.append(path)
            print(f"      ✓ {name}: {len(html)} znaków, ~{odds_like} kursopodobnych tokenów → {path}")
        else:
            print(f"      ✗ {name}: brak HTML (CF challenge / blokada / pusto) — {url}")
    return written


__all__ = ["cf_get", "dump_diagnostics", "ODDSPORTAL_TT", "BETEXPLORER_TT"]
