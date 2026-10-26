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
  'top.html',
  'how-to-use.html',
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
  { pattern: /Sports/, name: 'SportSidebar heading' },
  { pattern: /lg:grid-cols-\[232px/i, name: 'EventsShell column template' },
  { pattern: /viewBox/i, name: 'Inline SVG icons' },
  // Text strings that survive minification
  { pattern: /Model picks/, name: 'CompactFilters: model picks chip' },
  { pattern: /["']Value["']/, name: 'CompactFilters: value chip' },
  { pattern: /BTTS/i, name: 'Forebet BTTS data' },
  { pattern: /groupMatchesByLeague|sortLeagueGroups/i, name: 'League grouping functions' },
  // Positioning: the bookmaker-style layout must state it is not a bookmaker.
  { pattern: /do not accept bets/i, name: 'Footer: not-a-bookmaker notice' },
]
for (const { pattern, name } of newMarkers) {
  assert(pattern.test(content), `Contains: ${name}`)
}

// ── 3b. TOP honesty / staking UI (design K5, K8) ──
section('TOP record, staking and disclaimer')
const DISCLAIMER = /Pickly provides statistical analysis, not guarantees/
assert(DISCLAIMER.test(indexHTML), 'Footer: risk disclaimer in index.html')
assert(/href="\/how-to-use"/.test(indexHTML), 'Footer: link to /how-to-use')
const topMarkers = [
  { pattern: /Closing line value/, name: 'ClvTile' },
  { pattern: /Suggested stakes/, name: 'BankrollChart legend' },
  { pattern: /of bankroll/, name: 'StakeChip label' },
  { pattern: /Withdrawn picks/, name: 'WithdrawnList heading' },
  { pattern: /Best price/, name: 'Best price line' },
  { pattern: /bet below/, name: "Don't bet below line" },
  { pattern: /Line-ups unverified/, name: 'Line-ups label' },
  { pattern: /Price includes overtime/, name: 'Hockey OT note' },
  { pattern: /Flat 1-unit record; withdrawn picks excluded; hockey priced 2-way incl\. OT/, name: 'Methodology line' },
]
for (const { pattern, name } of topMarkers) {
  assert(pattern.test(allJS), `Contains: ${name}`)
}
const howFile = path.join(OUT, 'how-to-use.html')
const howHTML = fs.existsSync(howFile) ? fs.readFileSync(howFile, 'utf-8') : ''
for (const [pattern, name] of [
  [/How to use our picks &amp; responsible gambling/, 'title'],
  [DISCLAIMER, 'risk disclaimer'],
  [/id="stake"/, 'stake section'],
  [/1 000 \$\/€/, 'worked bankroll example'],
  [/id="clv"/, 'CLV section'],
  [/begambleaware\.org/i, 'BeGambleAware link'],
  [/gamcare\.org\.uk/, 'GamCare link'],
  [/1-800-GAMBLER/, '1-800-GAMBLER'],
  [/anonimowihazardzisci\.org/, 'Anonimowi Hazardziści link'],
]) {
  assert(pattern.test(howHTML), `/how-to-use: ${name}`)
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
