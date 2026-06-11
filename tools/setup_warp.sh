#!/usr/bin/env bash
# ============================================================================
# setup_warp.sh — Cloudflare WARP proxy z aktywna sonda SofaScore (v10.0)
# ----------------------------------------------------------------------------
# Stawia kontener caomingjun/warp jako SOCKS5 na :1080, czeka az tunel bedzie
# `warp=on`, a NASTEPNIE sprawdza czy SofaScore API faktycznie odpowiada 200
# przez to konkretne IP WARP. Gdy IP jest "spalone" (CF zwraca 403 mimo
# dzialajacego tunelu), kontener jest odtwarzany w celu rotacji IP i proba
# jest powtarzana.
#
# DLACZEGO sonda przez curl_cffi, a nie zwykly curl:
#   SofaScore (Cloudflare) blokuje po fingerprincie TLS. Zwykly `curl` dostaje
#   403 NIEZALEZNIE od IP, wiec nie nadaje sie do oceny czy IP jest czyste.
#   Scraper uzywa curl_cffi z impersonacja Chrome — sonda musi uzywac tego
#   samego klienta, zeby wynik byl reprezentatywny.
#
# Konfiguracja przez env (opcjonalna):
#   WARP_MAX_ATTEMPTS   — ile razy probowac nowego IP (domyslnie 3)
#   WARP_WAIT_TRIES     — ile 3s-petli czekac na warp=on (domyslnie 20 = 60s)
#   WARP_PROXY_PORT     — port SOCKS5 (domyslnie 1080)
#   WARP_PROBE_URL      — endpoint SofaScore do sondy
#
# Skrypt NIGDY nie konczy bledem (exit 0 zawsze) — brak czystego IP WARP nie
# powinien wywalac calego runu; scraper i tak ma fallbacky i lagodna degradacje.
# ============================================================================
set -u

WARP_MAX_ATTEMPTS="${WARP_MAX_ATTEMPTS:-3}"
WARP_WAIT_TRIES="${WARP_WAIT_TRIES:-20}"
WARP_PROXY_PORT="${WARP_PROXY_PORT:-1080}"
WARP_PROBE_URL="${WARP_PROBE_URL:-https://api.sofascore.com/api/v1/sport/football/events/live}"

start_warp() {
  docker rm -f warp >/dev/null 2>&1 || true
  echo "🌐 Starting Cloudflare WARP proxy container..."
  docker run -d --name warp \
    --restart=always \
    --device-cgroup-rule='c 10:200 rwm' \
    -p "${WARP_PROXY_PORT}:1080" \
    -e WARP_SLEEP=2 \
    --cap-add NET_ADMIN \
    --sysctl net.ipv6.conf.all.disable_ipv6=0 \
    --sysctl net.ipv4.conf.all.src_valid_mark=1 \
    -v /lib/modules:/lib/modules \
    caomingjun/warp:latest >/dev/null
}

wait_warp_on() {
  echo "⏳ Waiting for WARP to register and establish tunnel..."
  local i ip status
  for ((i = 1; i <= WARP_WAIT_TRIES; i++)); do
    sleep 3
    ip="$(curl -s --max-time 10 --socks5 "localhost:${WARP_PROXY_PORT}" https://api.ipify.org 2>/dev/null || echo "")"
    if [ -n "$ip" ]; then
      status="$(curl -s --max-time 10 --socks5 "localhost:${WARP_PROXY_PORT}" https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null | grep -E '^warp=' | cut -d= -f2 || echo off)"
      echo "WARP test ($i/${WARP_WAIT_TRIES}): IP=$ip, warp=$status"
      if [ "$status" = "on" ] || [ "$status" = "plus" ]; then
        echo "✅ WARP tunnel active - external IP $ip"
        return 0
      fi
    else
      echo "WARP not responding yet ($i/${WARP_WAIT_TRIES})..."
    fi
  done
  return 1
}

# Sonda przez curl_cffi (Chrome TLS). exit 0 = SofaScore 200, 1 = non-200,
# 2 = blad/biblioteka niedostepna (traktujemy jako "nie wiem" -> nie rotuj).
probe_sofascore() {
  WARP_PROXY_PORT="$WARP_PROXY_PORT" WARP_PROBE_URL="$WARP_PROBE_URL" python - <<'PY'
import os, sys
try:
    from curl_cffi import requests as cr
except Exception as e:
    print(f"probe: curl_cffi unavailable ({type(e).__name__}) — skipping probe")
    sys.exit(2)

port = os.environ.get("WARP_PROXY_PORT", "1080")
url = os.environ.get("WARP_PROBE_URL")
proxies = {"http": f"socks5://localhost:{port}", "https": f"socks5://localhost:{port}"}
try:
    r = cr.get(url, impersonate="chrome124", proxies=proxies, timeout=15)
    print(f"probe: SofaScore via WARP -> HTTP {r.status_code}")
    sys.exit(0 if r.status_code == 200 else 1)
except Exception as e:
    print(f"probe: error {type(e).__name__}: {str(e)[:120]}")
    sys.exit(2)
PY
}

OK=false
for ((attempt = 1; attempt <= WARP_MAX_ATTEMPTS; attempt++)); do
  echo "=== WARP attempt ${attempt}/${WARP_MAX_ATTEMPTS} ==="
  start_warp
  if ! wait_warp_on; then
    echo "::warning::WARP tunnel not up on attempt ${attempt}"
    docker logs warp 2>&1 | tail -30 || true
    continue
  fi

  probe_sofascore
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "✅ SofaScore reachable through WARP — IP not flagged."
    OK=true
    break
  elif [ "$rc" -eq 2 ]; then
    # Nie potrafimy ocenic IP (brak curl_cffi / blad sieci) — zostaw dzialajacy
    # tunel i nie marnuj kolejnych prob.
    echo "⚠️ SofaScore probe inconclusive — leaving WARP tunnel up as-is."
    OK=true
    break
  fi
  echo "⚠️ SofaScore 403 przez to IP WARP — rotuje IP (odtwarzam kontener)..."
done

if [ "$OK" != "true" ]; then
  echo "::warning::No clean WARP IP for SofaScore after ${WARP_MAX_ATTEMPTS} attempts."
  echo "::warning::SofaScore Fan Vote moze byc niedostepny w tym runie; inne zrodla dzialaja."
fi

# Zawsze sukces — brak czystego IP nie powinien wywalac calego runu.
exit 0
