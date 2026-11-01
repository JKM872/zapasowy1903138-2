/**
 * API Contract Test
 * ──────────────────
 * Validates that the production API at Heroku returns the expected data shape.
 * The newest day can still be empty, so the test reads /api/dates and checks
 * the first of the newest MAX_DATES days that has matches.
 * Tests:
 *  1. /api/dates and /api/matches?date=<day> return 200
 *  2. Response shape has required top-level keys
 *  3. Match items have required fields
 *  4. sportCounts is populated
 *  5. Nullable fields don't crash (nulls allowed but structure valid)
 */

const API_BASE = process.env.API_URL || 'https://pickly-67e87ed00f70.herokuapp.com'
const MAX_DATES = 5

let failures = 0

function assert(condition, msg) {
  if (condition) {
    console.log(`  ✅ ${msg}`)
  } else {
    console.error(`  ❌ ${msg}`)
    failures++
  }
}

function section(title) {
  console.log(`\n── ${title} ──`)
}

async function get(path) {
  try {
    return await fetch(`${API_BASE}${path}`)
  } catch (err) {
    throw new Error(`Failed to connect: ${err.message}`)
  }
}

// process.exitCode instead of process.exit(): on Windows, Node 24 before
// 24.20 aborts with 0xC0000409 when process.exit() follows fetch calls
// (nodejs/node#56645).
function summary() {
  console.log('\n' + '═'.repeat(40))
  if (failures === 0) {
    console.log('✅ All API contract tests PASSED')
    process.exitCode = 0
  } else {
    console.error(`❌ ${failures} test(s) FAILED`)
    process.exitCode = 1
  }
}

async function main() {
  // ── 1. Find the newest day with matches ──
  section('API Connectivity')
  const datesResponse = await get('/api/dates')
  assert(datesResponse.ok, `GET /api/dates → ${datesResponse.status} (expected 2xx)`)
  const dates = datesResponse.ok ? ((await datesResponse.json()).dates || []).slice(0, MAX_DATES) : []

  let json = null
  let date = null
  for (const d of dates) {
    const response = await get(`/api/matches?date=${encodeURIComponent(d)}`)
    assert(response.ok, `GET /api/matches?date=${d} → ${response.status} (expected 2xx)`)
    if (!response.ok) continue
    const body = await response.json()
    if (Array.isArray(body?.data) && body.data.length > 0) {
      json = body
      date = d
      break
    }
    console.log(`  ⚠️  ${d}: no matches, trying the previous date`)
  }
  if (!json) {
    assert(false, `one of the newest ${dates.length} dates has matches (${dates.join(', ')})`)
    return summary()
  }

  // ── 2. Parse JSON ──
  assert(typeof json === 'object' && json !== null, 'Response is a JSON object')

  // ── 3. Top-level shape ──
  section('Top-level response shape')
  assert(Array.isArray(json.data), '"data" is an array')
  assert(typeof json.meta === 'object', '"meta" is an object')
  assert(typeof json.stats === 'object', '"stats" is an object')
  assert(
    typeof json.sportCounts === 'object' && json.sportCounts !== null,
    '"sportCounts" is an object',
  )

  // ── 4. sportCounts validation ──
  section('sportCounts')
  const counts = json.sportCounts || {}
  const totalFromCounts = Object.values(counts).reduce((a, b) => a + b, 0)
  assert(totalFromCounts > 0, `sportCounts total = ${totalFromCounts} (> 0)`)

  // ── 5. Match item fields ──
  section('Match item structure')
  const sample = json.data[0]
  const requiredFields = [
    'id', 'homeTeam', 'awayTeam', 'sport', 'time',
  ]
  for (const field of requiredFields) {
    assert(field in sample, `Match has "${field}" field`)
  }

  // Nullable but structurally valid fields
  const nullableFields = ['odds', 'forebet', 'sofascore', 'gemini', 'h2h']
  for (const field of nullableFields) {
    const value = sample[field]
    assert(
      value === null || value === undefined || typeof value === 'object',
      `"${field}" is null/undefined/object (got ${typeof value})`,
    )
  }

  // ── 6. Sub-object shapes (when present) ──
  section('Sub-object shapes (on sample match)')

  // Odds
  if (sample.odds && typeof sample.odds === 'object') {
    assert('home' in sample.odds, 'odds.home exists')
    assert('away' in sample.odds, 'odds.away exists')
  }

  // Forebet
  if (sample.forebet && typeof sample.forebet === 'object') {
    assert('prediction' in sample.forebet, 'forebet.prediction exists')
  }

  // SofaScore
  if (sample.sofascore && typeof sample.sofascore === 'object') {
    assert('home' in sample.sofascore, 'sofascore.home exists')
  }

  console.log(`\n  ℹ️  Tested ${json.data.length} matches from API (date ${date})`)

  // ── Summary ──
  summary()
}

main().catch((err) => {
  console.error(`Fatal: ${err.message}`)
  process.exitCode = 1
})
