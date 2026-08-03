/**
 * Build Smoke Test
 * ─────────────────
 * Runs after `npm run build` (static export) and validates:
 *  1. out/index.html exists
 *  2. JS bundles contain new FlashScore-style components
 *  3. JS bundles do NOT contain old sidebar/card UI patterns
 *  4. All expected route pages generated
 */
/* eslint-disable @typescript-eslint/no-require-imports */
const fs = require('fs')
const path = require('path')

const OUT = path.resolve(__dirname, '..', 'out')
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

// ── 1. Check critical output files exist ──
section('Output files')
const requiredFiles = [
  'index.html',
  'stats.html',
  'my-bets.html',
  'leaderboard.html',
  '404.html',
]
for (const file of requiredFiles) {
  assert(fs.existsSync(path.join(OUT, file)), `${file} exists`)
}

// Check _next directory
const nextDir = path.join(OUT, '_next', 'static', 'chunks')
assert(fs.existsSync(nextDir), '_next/static/chunks/ directory exists')

// ── 2. Read all JS bundles and index.html ──
section('Bundle content analysis')
let allJS = ''
if (fs.existsSync(nextDir)) {
  const jsFiles = fs.readdirSync(nextDir).filter(f => f.endsWith('.js'))
  assert(jsFiles.length > 5, `Found ${jsFiles.length} JS chunks (expected > 5)`)
  for (const file of jsFiles) {
    allJS += fs.readFileSync(path.join(nextDir, file), 'utf-8')
  }
}
const indexHTML = fs.readFileSync(path.join(OUT, 'index.html'), 'utf-8')
const content = allJS + indexHTML

// ── 3. Verify NEW UI markers present ──
section('New UI markers (must be present)')
const newMarkers = [
  // Sticky layout markers (CSS classes survive minification). The date strip now
  // anchors under the 56px header because the sport tabs moved into the sidebar.
  { pattern: /sticky.*top-14.*z-30/i, name: 'DateCarousel sticky class' },
  { pattern: /SportTabs|sportCounts|sport-tab/i, name: 'SportTabs reference' },
  { pattern: /LeagueGroup|CollapsibleTrigger/i, name: 'LeagueGroup reference' },
  // Three-column bookmaker shell
  { pattern: /Dyscypliny/i, name: 'SportSidebar heading' },
  { pattern: /lg:grid-cols-\[232px/i, name: 'EventsShell column template' },
  { pattern: /viewBox/i, name: 'Inline SVG icons' },
  // Text strings that survive minification
  { pattern: /Typy modelu/i, name: 'CompactFilters: model picks chip' },
  { pattern: /Warto[śs][ćc]/i, name: 'CompactFilters: value chip' },
  { pattern: /BTTS/i, name: 'Forebet BTTS data' },
  { pattern: /groupMatchesByLeague|sortLeagueGroups/i, name: 'League grouping functions' },
  // Positioning: the bookmaker-style layout must state it is not a bookmaker.
  { pattern: /nie przyjmujemy zak[łl]ad[óo]w/i, name: 'Footer: not-a-bookmaker notice' },
]
for (const { pattern, name } of newMarkers) {
  assert(pattern.test(content), `Contains: ${name}`)
}

// ── 4. Verify OLD UI artifacts are NOT dominant ──
section('Old UI patterns (should be absent from page route)')
// These patterns would only appear if the old sidebar/card layout is rendered
const oldPatterns = [
  // Old FilterBar sidebar had these class patterns
  { pattern: /class="[^"]*FilterBar[^"]*"/i, name: 'Old FilterBar component class' },
  // Old MatchCard grid used lg:grid-cols-3
  { pattern: /lg:grid-cols-3.*MatchCard/i, name: 'Old 3-column MatchCard grid' },
  // Regression guard: the Material Symbols icon font rendered its glyph names as
  // visible text whenever the font failed to load, so "sports_soccer" and the
  // like appeared all over the UI. Icons are inline SVG now; the names must not
  // be shipped as content again.
  { pattern: /sports_soccer|sports_basketball|material-symbol/i, name: 'Icon font glyph names' },
]
for (const { pattern, name } of oldPatterns) {
  assert(!pattern.test(content), `Absent: ${name}`)
}

// ── 5. Check HTML structure ──
section('HTML structure')
assert(indexHTML.includes('<!DOCTYPE html>'), 'Valid HTML doctype')
assert(indexHTML.includes('<script'), 'Contains script tags')
assert(indexHTML.includes('_next/static'), 'References _next/static assets')

// ── Summary ──
console.log('\n' + '═'.repeat(40))
if (failures === 0) {
  console.log('✅ All build smoke tests PASSED')
  process.exit(0)
} else {
  console.error(`❌ ${failures} test(s) FAILED`)
  process.exit(1)
}
