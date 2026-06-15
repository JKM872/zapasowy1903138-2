#!/usr/bin/env bash
# ============================================================================
# setup_tor.sh — Tor jako SOCKS5 :9050 z aktywna sonda SofaScore (v10.9)
# ----------------------------------------------------------------------------
# SofaScore blokuje IP datacenter (GitHub Actions/Azure) oraz Cloudflare WARP
# na poziomie reputacji IP — nawet z poprawnym tokenem X-Requested-With zwraca
# 403 {"reason":"challenge"}. Tor daje IP wyjsciowe spoza tych pul i przechodzi.
#
# Skrypt: instaluje Tor, czeka na bootstrap, a NASTEPNIE sprawdza czy SofaScore
# API faktycznie odpowiada (!=403) przez aktualny exit node. Gdy exit jest
# zablokowany (403), restartuje Tor po nowy obwod/exit i powtarza.
#
# Sonda uzywa curl_cffi (Chrome TLS) + naglowka X-Requested-With — dokladnie
# tak jak scraper, zeby wynik byl reprezentatywny.
#
# Konfiguracja przez env (opcjonalna):
#   TOR_SOCKS_PORT     — port SOCKS5 (domyslnie 9050)
#   TOR_MAX_ATTEMPTS   — ile exitow sprobowac (domyslnie 4)
#   SOFASCORE_XRW      — token X-Requested-With (domyslnie 61544a)
#
# Skrypt NIGDY nie konczy bledem (exit 0) — brak czystego exitu nie powinien
# wywalac calego runu; scraper ma lagodna degradacje.
# ============================================================================
set -u

TOR_PORT="${TOR_SOCKS_PORT:-9050}"
TOR_MAX_ATTEMPTS="${TOR_MAX_ATTEMPTS:-4}"
XRW="${SOFASCORE_XRW:-61544a}"
PROBE_URL="${SOFASCORE_PROBE_URL:-https://api.sofascore.com/api/v1/sport/football/scheduled-events/$(date +%Y-%m-%d)}"

echo "🧅 Instaluje Tor..."
sudo apt-get update -qq && sudo apt-get install -y -qq tor || true

start_tor() {
  # restart => nowy obwod/exit przy kolejnych probach
  sudo service tor restart 2>/dev/null \
    || sudo /etc/init.d/tor restart 2>/dev/null \
    || { sudo service tor start 2>/dev/null; sudo /etc/init.d/tor start 2>/dev/null; } \
    || true
}

wait_boot() {
  local i ip
  for ((i = 1; i <= 30; i++)); do
    ip="$(curl -s --max-time 12 --socks5-hostname "localhost:${TOR_PORT}" https://api.ipify.org 2>/dev/null || echo "")"
    if [ -n "$ip" ]; then
      echo "  Tor exit IP ${ip}"
      return 0
    fi
    sleep 3
  done
  return 1
}

probe_sofascore() {
  TOR_PORT="$TOR_PORT" PURL="$PROBE_URL" XRW="$XRW" python - <<'PY'
import os, sys
try:
    from curl_cffi import requests as cr
except Exception as e:
    print(f"  probe: curl_cffi unavailable ({type(e).__name__}) — pomijam")
    sys.exit(2)
port = os.environ.get("TOR_PORT", "9050")
url = os.environ["PURL"]
xrw = os.environ["XRW"]
px = {"http": f"socks5h://localhost:{port}", "https": f"socks5h://localhost:{port}"}
hdr = {"X-Requested-With": xrw, "Referer": "https://www.sofascore.com/",
       "Accept": "*/*"}
try:
    r = cr.get(url, impersonate="chrome131", proxies=px, timeout=20, headers=hdr)
    print(f"  probe: SofaScore via Tor -> HTTP {r.status_code}")
    # 200/404 = przeszlismy anty-bota (404 = brak meczow danego dnia); 403 = blok
    sys.exit(0 if r.status_code != 403 else 1)
except Exception as e:
    print(f"  probe: error {type(e).__name__}: {str(e)[:100]}")
    sys.exit(2)
PY
}

OK=false
for ((attempt = 1; attempt <= TOR_MAX_ATTEMPTS; attempt++)); do
  echo "=== Tor attempt ${attempt}/${TOR_MAX_ATTEMPTS} ==="
  start_tor
  if ! wait_boot; then
    echo "::warning::Tor nie wstal na probie ${attempt}"
    continue
  fi
  probe_sofascore
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "✅ SofaScore osiagalny przez Tor — exit czysty."
    OK=true
    break
  elif [ "$rc" -eq 2 ]; then
    echo "⚠️ Sonda niejednoznaczna (brak curl_cffi/blad) — zostawiam Tor jak jest."
    OK=true
    break
  fi
  echo "⚠️ SofaScore 403 przez ten exit Tora — rotuje exit (restart Tor)..."
done

if [ "$OK" != "true" ]; then
  echo "::warning::Brak czystego exitu Tora po ${TOR_MAX_ATTEMPTS} probach — SofaScore moze byc niedostepny w tym runie."
fi

exit 0
