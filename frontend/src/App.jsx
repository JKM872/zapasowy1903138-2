import { useState, useEffect, useCallback, useMemo, useRef, memo } from 'react'
import './index.css'
import {
  // UI icons
  Target,
  Calendar as CalendarIcon,
  Clock,
  ChevronDown,
  ChevronUp,
  TrendingUp,
  TrendingDown,
  Minus,
  Star,
  Users,
  BarChart3,
  Activity,
  Filter,
  Search,
  Settings,
  Bell,
  ExternalLink,
  Check,
  X,
  AlertCircle,
  Info,
  ArrowUpRight,
  ArrowDownRight,
  Percent,
  Hash,
  MapPin,
  Flag,
  Loader2,
  RefreshCw,
  SortAsc,
  SortDesc,
  // New icons for Phase 3
  Sun,
  Moon,
  Download,
  FileText,
  FileSpreadsheet,
  Columns,
  XCircle,
  Plus,
  Trash2,
  // New icons for Phase 4 (Tabs)
  LayoutGrid,
  List,
  PieChart,
  // Phase 2 - Mobile menu
  Menu
} from 'lucide-react'

// Realistic Sport Icons (React Icons)
import { 
  MdSportsSoccer, 
  MdSportsBasketball, 
  MdSportsVolleyball, 
  MdSportsHandball, 
  MdSportsHockey, 
  MdSportsTennis,
  MdDashboard
} from 'react-icons/md'

// Import new components
import Calendar from './components/Calendar'
import AccuracyChart from './components/AccuracyChart'
import NotificationPrompt from './components/NotificationPrompt'
import StatsDashboard from './components/StatsDashboard'
import QuickBetCalculator from './components/QuickBetCalculator'
import Logo from './components/Logo'



// API Configuration
const API_BASE = 'http://localhost:5000'

// Get sport icon component
const SportIcons = {
  all: MdDashboard,
  football: MdSportsSoccer,
  basketball: MdSportsBasketball,
  volleyball: MdSportsVolleyball,
  handball: MdSportsHandball,
  hockey: MdSportsHockey,
  tennis: MdSportsTennis
}

function getSportIcon(sportId) {
  const id = sportId?.toLowerCase() || 'all'
  return SportIcons[id] || MdDashboard
}

// Favorites Hook with localStorage
function useFavorites() {
  const [favorites, setFavorites] = useState(() => {
    try {
      const saved = localStorage.getItem('bigone-favorites')
      return saved ? JSON.parse(saved) : []
    } catch {
      return []
    }
  })

  useEffect(() => {
    localStorage.setItem('bigone-favorites', JSON.stringify(favorites))
  }, [favorites])

  const addFavorite = useCallback((match) => {
    setFavorites(prev => {
      if (prev.some(m => m.id === match.id)) return prev
      return [...prev, match]
    })
  }, [])

  const removeFavorite = useCallback((matchId) => {
    setFavorites(prev => prev.filter(m => m.id !== matchId))
  }, [])

  const isFavorite = useCallback((matchId) => {
    return favorites.some(m => m.id === matchId)
  }, [favorites])

  const toggleFavorite = useCallback((match) => {
    if (isFavorite(match.id)) {
      removeFavorite(match.id)
    } else {
      addFavorite(match)
    }
  }, [isFavorite, addFavorite, removeFavorite])

  return { favorites, addFavorite, removeFavorite, isFavorite, toggleFavorite }
}

// Value Bet Calculator
function calculateValueBet(match) {
  if (!isValidNumber(match.odds?.home) || !isValidNumber(match.forebet?.probability)) return null

  const impliedProb = 1 / match.odds.home
  const forebetProb = match.forebet.probability / 100

  // EV = (Probability * Odds) - 1
  const ev = (forebetProb * match.odds.home) - 1

  if (ev > 0.05) { // 5% edge threshold
    return {
      ev: (ev * 100).toFixed(1),
      edge: ((forebetProb - impliedProb) * 100).toFixed(1)
    }
  }
  return null
}

// Helper: sprawdza czy wartość jest poprawną liczbą (nie null, nie undefined, nie NaN)
function isValidNumber(val) {
  return val != null && !Number.isNaN(val) && typeof val === 'number'
}

// API Functions
async function fetchMatches(date, sport) {
  try {
    const params = new URLSearchParams({ date, sport })
    const response = await fetch(`${API_BASE}/api/matches?${params}`)
    if (!response.ok) throw new Error('Network error')
    const data = await response.json()
    // Jeśli brak meczów, użyj przykładowych danych
    if (!data.matches || data.matches.length === 0) {
      const sampleResponse = await fetch(`${API_BASE}/api/sample`)
      if (sampleResponse.ok) return await sampleResponse.json()
    }
    return data
  } catch (error) {
    console.error('Failed to fetch matches:', error)
    const response = await fetch(`${API_BASE}/api/sample`)
    if (response.ok) return await response.json()
    return null
  }
}

async function fetchSports(date) {
  try {
    const response = await fetch(`${API_BASE}/api/sports?date=${date}`)
    if (!response.ok) throw new Error('Network error')
    return await response.json()
  } catch {
    return [
      { id: 'all', name: 'All Sports', icon: 'MdDashboard', count: 0 },
      { id: 'football', name: 'Football', icon: 'MdSportsSoccer', count: 0 },
      { id: 'basketball', name: 'Basketball', icon: 'MdSportsBasketball', count: 0 },
      { id: 'volleyball', name: 'Volleyball', icon: 'MdSportsVolleyball', count: 0 },
      { id: 'handball', name: 'Handball', icon: 'MdSportsHandball', count: 0 },
      { id: 'hockey', name: 'Hockey', icon: 'MdSportsHockey', count: 0 },
      { id: 'tennis', name: 'Tennis', icon: 'MdSportsTennis', count: 0 }
    ]
  }
}

// Export Functions
function exportToCSV(matches, filename = 'matches.csv') {
  const headers = ['Home Team', 'Away Team', 'Time', 'League', 'H2H Home', 'H2H Away', 'Home Odds', 'Away Odds', 'Bookmaker', 'Qualifies']
  const rows = matches.map(m => [
    m.homeTeam,
    m.awayTeam,
    m.time,
    m.league,
    m.h2h?.home || 0,
    m.h2h?.away || 0,
    m.odds?.home || '',
    m.odds?.away || '',
    m.odds?.bookmaker || '',
    m.qualifies ? 'Yes' : 'No'
  ])

  const csv = [headers, ...rows].map(row => row.join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function exportToJSON(matches, filename = 'matches.json') {
  const json = JSON.stringify(matches, null, 2)
  const blob = new Blob([json], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// Theme Hook
function useTheme() {
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem('bigone-theme') || 'dark'
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('bigone-theme', theme)
  }, [theme])

  const toggleTheme = () => setTheme(t => t === 'dark' ? 'light' : 'dark')

  return { theme, toggleTheme }
}

// Components
function Header({ date, onDateChange, searchQuery, onSearch, onRefresh, isLoading, theme, toggleTheme, onExport, compareMode, onToggleCompare, searchInputRef, onToggleMobileMenu, onOpenCalculator }) {
  const [showExportMenu, setShowExportMenu] = useState(false)

  return (
    <header className="header">
      {/* Mobile menu button */}
      <button className="mobile-menu-btn" onClick={onToggleMobileMenu}>
        <Menu size={24} />
      </button>

      <div className="header-logo">
        <Logo className="logo-icon" size={32} />
        <span>BigOne</span>
      </div>

      <div className="header-search">
        <Search size={16} className="search-icon" />
        <input
          ref={searchInputRef}
          type="text"
          placeholder="Search matches, teams, leagues... (Ctrl+F)"
          value={searchQuery}
          onChange={(e) => onSearch(e.target.value)}
          className="search-input"
        />
      </div>

      <div className="header-actions">
        {/* Compare Mode Toggle */}
        <button
          className={`icon-btn ${compareMode ? 'active' : ''}`}
          onClick={onToggleCompare}
          title="Compare Matches"
        >
          <Columns size={18} />
        </button>

        {/* Export Menu */}
        <div className="export-menu-wrapper">
          <button
            className="icon-btn"
            onClick={() => setShowExportMenu(!showExportMenu)}
            title="Export"
          >
            <Download size={18} />
          </button>
          {showExportMenu && (
            <div className="export-menu">
              <button onClick={() => { onExport('csv'); setShowExportMenu(false) }}>
                <FileSpreadsheet size={14} />
                Export CSV
              </button>
              <button onClick={() => { onExport('json'); setShowExportMenu(false) }}>
                <FileText size={14} />
                Export JSON
              </button>
            </div>
          )}
        </div>

        <button className="icon-btn" onClick={onRefresh} disabled={isLoading}>
          <RefreshCw size={18} className={isLoading ? 'spin' : ''} />
        </button>

        <div className="date-selector-wrapper">
          <CalendarIcon size={16} />
          <input
            type="date"
            className="date-selector"
            value={date}
            onChange={(e) => onDateChange(e.target.value)}
          />
        </div>

        {/* Theme Toggle */}
        <button className="icon-btn" onClick={toggleTheme} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>

        <button className="icon-btn">
          <Bell size={18} />
        </button>
      </div>
    </header>
  )
}

function Sidebar({ sports, activeSport, onSportChange, filters, onFilterChange }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-section">
        <h3 className="sidebar-title">
          <Activity size={14} />
          Sports
        </h3>
        <ul className="sport-list">
          {sports.map(sport => {
            const IconComponent = getSportIcon(sport.id)
            return (
              <li
                key={sport.id}
                className={`sport-item ${activeSport === sport.id ? 'active' : ''}`}
                onClick={() => onSportChange(sport.id)}
              >
                <IconComponent size={16} className="sport-icon" />
                <span className="sport-name">{sport.name}</span>
                <span className="sport-count">{sport.count}</span>
              </li>
            )
          })}
        </ul>
      </div>

      <div className="sidebar-section">
        <h3 className="sidebar-title">
          <Filter size={14} />
          Quick Filters
        </h3>
        <div className="quick-filters">
          <button
            className={`quick-filter-btn ${filters.qualifying ? 'active' : ''}`}
            onClick={() => onFilterChange('qualifying', !filters.qualifying)}
          >
            <Check size={14} />
            Only Qualifying
          </button>
          <button
            className={`quick-filter-btn ${filters.formAdvantage ? 'active' : ''}`}
            onClick={() => onFilterChange('formAdvantage', !filters.formAdvantage)}
          >
            <TrendingUp size={14} />
            Form Advantage
          </button>
          <button
            className={`quick-filter-btn ${filters.withOdds ? 'active' : ''}`}
            onClick={() => onFilterChange('withOdds', !filters.withOdds)}
          >
            <Star size={14} />
            With Odds
          </button>
        </div>
      </div>

      <div className="sidebar-section">
        <h3 className="sidebar-title">
          <SortAsc size={14} />
          Sort By
        </h3>
        <div className="quick-filters">
          <button
            className={`quick-filter-btn ${filters.sortBy === 'time' ? 'active' : ''}`}
            onClick={() => onFilterChange('sortBy', 'time')}
          >
            <Clock size={14} />
            Time
          </button>
          <button
            className={`quick-filter-btn ${filters.sortBy === 'h2h' ? 'active' : ''}`}
            onClick={() => onFilterChange('sortBy', 'h2h')}
          >
            <BarChart3 size={14} />
            H2H Win Rate
          </button>
          <button
            className={`quick-filter-btn ${filters.sortBy === 'odds' ? 'active' : ''}`}
            onClick={() => onFilterChange('sortBy', 'odds')}
          >
            <Percent size={14} />
            Best Odds
          </button>
        </div>
      </div>
    </aside>
  )
}

function FormDot({ result }) {
  const icon = result === 'W' ? Check : result === 'D' ? Minus : X
  const IconComponent = icon
  const className = result === 'W' ? 'win' : result === 'D' ? 'draw' : 'loss'
  return (
    <span className={`form-dot ${className}`} title={result === 'W' ? 'Win' : result === 'D' ? 'Draw' : 'Loss'}>
      <IconComponent size={10} />
    </span>
  )
}

function OddBox({ label, value, isBest }) {
  if (!value) return null
  return (
    <div className={`odd-box ${isBest ? 'favorite' : ''}`}>
      <div className="odd-label">{label}</div>
      <div className={`odd-value ${isBest ? 'best' : ''}`}>{typeof value === 'number' ? value.toFixed(2) : value}</div>
    </div>
  )
}

const MatchCard = memo(function MatchCard({ match, compareMode, isSelected, onToggleSelect, isFavorite, onToggleFavorite, onPlaceBet }) {
  const [expanded, setExpanded] = useState(false)
  const hasDraw = match.sport === 'football'

  // Memoized calculations - filtruje NaN i null wartości
  const allOdds = useMemo(() => {
    const odds = hasDraw
      ? [match.odds?.home, match.odds?.draw, match.odds?.away]
      : [match.odds?.home, match.odds?.away]
    return odds.filter(isValidNumber)
  }, [match.odds, hasDraw])

  const minOdd = allOdds.length > 0 ? Math.min(...allOdds) : null
  const valueBet = useMemo(() => calculateValueBet(match), [match])

  const handleClick = () => {
    if (compareMode) {
      onToggleSelect(match)
    } else {
      setExpanded(!expanded)
    }
  }

  const handleFavoriteClick = (e) => {
    e.stopPropagation()
    onToggleFavorite?.(match)
  }

  return (
    <div className={`match-card ${match.qualifies ? 'qualifies' : ''} ${expanded ? 'expanded' : ''} ${isSelected ? 'selected' : ''}`}>
      <div className="match-main" onClick={handleClick}>
        {/* Compare checkbox */}
        {compareMode && (
          <div className="compare-checkbox">
            {isSelected ? <Check size={16} /> : <Plus size={16} />}
          </div>
        )}

        {/* Time & Status */}
        <div className="match-time">
          <Clock size={12} className="time-icon" />
          <div className="match-time-value">{match.time || '—'}</div>
          {match.qualifies && (
            <div className="qualify-badge" title="Qualifies">
              <Check size={10} />
            </div>
          )}
          {valueBet && (
            <div className="value-bet-badge" title={`EV: +${valueBet.ev}%`}>
              VALUE
            </div>
          )}
        </div>

        {/* Favorite Star */}
        <button
          className={`favorite-btn ${isFavorite ? 'active' : ''}`}
          onClick={handleFavoriteClick}
          title={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
        >
          <Star size={16} fill={isFavorite ? 'currentColor' : 'none'} />
        </button>

        {/* Teams */}
        <div className="match-teams">
          <div className={`team-row ${match.focusTeam === 'home' ? 'focus' : ''}`}>
            <span className="team-name">{match.homeTeam}</span>
            <div className="team-form">
              {match.homeForm?.slice(0, 5).map((f, i) => <FormDot key={i} result={f} />)}
            </div>
          </div>
          <div className={`team-row ${match.focusTeam === 'away' ? 'focus' : ''}`}>
            <span className="team-name">{match.awayTeam}</span>
            <div className="team-form">
              {match.awayForm?.slice(0, 5).map((f, i) => <FormDot key={i} result={f} />)}
            </div>
          </div>
        </div>

        {/* H2H Quick */}
        <div className="match-h2h-quick">
          <div className="h2h-label">H2H</div>
          <div className="h2h-score">
            <span className="h2h-home">{match.h2h?.home || 0}</span>
            {hasDraw && <span className="h2h-draw">-{match.h2h?.draw || 0}-</span>}
            <span className="h2h-away">{match.h2h?.away || 0}</span>
          </div>
          {match.h2h?.winRate > 0 && <div className="h2h-winrate">{match.h2h.winRate}%</div>}
        </div>

        {/* Odds */}
        <div className="match-odds">
          {isValidNumber(match.odds?.home) && (
            <OddBox label="1" value={match.odds.home} isBest={match.odds.home === minOdd} />
          )}
          {hasDraw && isValidNumber(match.odds?.draw) && (
            <OddBox label="X" value={match.odds.draw} isBest={match.odds.draw === minOdd} />
          )}
          {isValidNumber(match.odds?.away) && (
            <OddBox label="2" value={match.odds.away} isBest={match.odds.away === minOdd} />
          )}
          {!isValidNumber(match.odds?.home) && !isValidNumber(match.odds?.away) && (
            <span className="no-odds">No odds</span>
          )}
        </div>

        {/* Expand arrow */}
        {!compareMode && (
          <div className="match-expand">
            {expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </div>
        )}
      </div>

      {/* Expanded Details */}
      {expanded && !compareMode && (
        <div className="match-details">
          {/* H2H Section */}
          <div className="detail-section">
            <div className="detail-header">
              <BarChart3 size={14} />
              <span>Head to Head</span>
            </div>
            <div className="h2h-bar">
              <div className="h2h-segment home" style={{ width: `${(match.h2h?.home || 0) * 20}%` }} />
              {hasDraw && <div className="h2h-segment draw" style={{ width: `${(match.h2h?.draw || 0) * 20}%` }} />}
              <div className="h2h-segment away" style={{ width: `${(match.h2h?.away || 0) * 20}%` }} />
            </div>
            <div className="h2h-stats">
              <div className="h2h-stat">
                <ArrowUpRight size={12} className="icon-green" />
                <span>{match.h2h?.home || 0} Home Wins</span>
              </div>
              {hasDraw && (
                <div className="h2h-stat">
                  <Minus size={12} className="icon-yellow" />
                  <span>{match.h2h?.draw || 0} Draws</span>
                </div>
              )}
              <div className="h2h-stat">
                <ArrowDownRight size={12} className="icon-red" />
                <span>{match.h2h?.away || 0} Away Wins</span>
              </div>
            </div>
          </div>

          {/* Form Section */}
          <div className="detail-section">
            <div className="detail-header">
              <TrendingUp size={14} />
              <span>Form Analysis</span>
              {match.formAdvantage && <span className="badge badge-green">ADV</span>}
            </div>
            <div className="form-comparison">
              <div className="form-team">
                <span className="form-team-name">{match.homeTeam}</span>
                <div className="form-icons">
                  {match.homeForm?.map((f, i) => <FormDot key={i} result={f} />)}
                </div>
              </div>
              <div className="form-team">
                <span className="form-team-name">{match.awayTeam}</span>
                <div className="form-icons">
                  {match.awayForm?.map((f, i) => <FormDot key={i} result={f} />)}
                </div>
              </div>
            </div>
          </div>

          {/* Forebet */}
          {match.forebet?.prediction && (
            <div className="detail-section">
              <div className="detail-header">
                <Target size={14} />
                <span>Forebet</span>
              </div>
              <div className="prediction-main">
                <span className={`prediction-badge ${match.forebet.prediction === '1' ? 'home' : match.forebet.prediction === 'X' ? 'draw' : 'away'}`}>
                  {match.forebet.prediction === '1' ? 'HOME' : match.forebet.prediction === 'X' ? 'DRAW' : 'AWAY'}
                </span>
                {match.forebet.probability && (
                  <span className="prediction-prob">{match.forebet.probability}%</span>
                )}
              </div>
            </div>
          )}

          {/* SofaScore */}
          {isValidNumber(match.sofascore?.home) && (
            <div className="detail-section">
              <div className="detail-header">
                <Users size={14} />
                <span>Fan Vote</span>
                {isValidNumber(match.sofascore?.votes) && match.sofascore.votes > 0 && (
                  <span className="vote-count">({match.sofascore.votes.toLocaleString()} głosów)</span>
                )}
              </div>
              <div className="vote-bar">
                <div className="vote-segment home" style={{ width: `${match.sofascore.home}%` }}>
                  {match.sofascore.home}%
                </div>
                {isValidNumber(match.sofascore?.draw) && match.sofascore.draw > 0 && (
                  <div className="vote-segment draw" style={{ width: `${match.sofascore.draw}%` }}>
                    {match.sofascore.draw}%
                  </div>
                )}
                {isValidNumber(match.sofascore?.away) && (
                <div className="vote-segment away" style={{ width: `${match.sofascore.away}%` }}>
                  {match.sofascore.away}%
                </div>
                )}
              </div>
            </div>
          )}

          {/* Match Actions */}
          <div className="match-actions">
            {match.matchUrl && (
              <a href={match.matchUrl} target="_blank" rel="noopener noreferrer" className="action-btn secondary">
                <ExternalLink size={14} />
                View Details
              </a>
            )}
            
            {/* Bet Buttons */}
            <div className="bet-buttons">
              <button
                className="bet-btn home"
                onClick={(e) => {
                  e.stopPropagation()
                  onPlaceBet?.(match, '1', match.odds?.home)
                }}
                disabled={!isValidNumber(match.odds?.home)}
                title={`Postaw na ${match.homeTeam}`}
              >
                <span className="bet-label">1</span>
                <span className="bet-odds">{isValidNumber(match.odds?.home) ? match.odds.home.toFixed(2) : '—'}</span>
              </button>
              {hasDraw && (
                <button
                  className="bet-btn draw"
                  onClick={(e) => {
                    e.stopPropagation()
                    onPlaceBet?.(match, 'X', match.odds?.draw)
                  }}
                  disabled={!isValidNumber(match.odds?.draw)}
                  title="Postaw na remis"
                >
                  <span className="bet-label">X</span>
                  <span className="bet-odds">{isValidNumber(match.odds?.draw) ? match.odds.draw.toFixed(2) : '—'}</span>
                </button>
              )}
              <button
                className="bet-btn away"
                onClick={(e) => {
                  e.stopPropagation()
                  onPlaceBet?.(match, '2', match.odds?.away)
                }}
                disabled={!isValidNumber(match.odds?.away)}
                title={`Postaw na ${match.awayTeam}`}
              >
                <span className="bet-label">2</span>
                <span className="bet-odds">{isValidNumber(match.odds?.away) ? match.odds.away.toFixed(2) : '—'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
})

// Compare Panel Component
function ComparePanel({ selectedMatches, onRemove, onClear }) {
  if (selectedMatches.length === 0) return null

  return (
    <div className="compare-panel">
      <div className="compare-header">
        <h3><Columns size={16} /> Comparing {selectedMatches.length} matches</h3>
        <button className="clear-btn" onClick={onClear}>
          <Trash2 size={14} />
          Clear All
        </button>
      </div>
      <div className="compare-grid">
        {selectedMatches.map(match => (
          <div key={match.id} className="compare-card">
            <button className="remove-btn" onClick={() => onRemove(match)}>
              <XCircle size={14} />
            </button>
            <div className="compare-teams">
              <span>{match.homeTeam}</span>
              <span className="vs">vs</span>
              <span>{match.awayTeam}</span>
            </div>
            <div className="compare-stats">
              <div className="compare-row">
                <span>H2H</span>
                <span className="value">{match.h2h?.home || 0}-{match.h2h?.draw || 0}-{match.h2h?.away || 0}</span>
              </div>
              <div className="compare-row">
                <span>Win Rate</span>
                <span className="value">{match.h2h?.winRate || 0}%</span>
              </div>
              <div className="compare-row">
                <span>Odds</span>
                <span className="value">{isValidNumber(match.odds?.home) ? match.odds.home.toFixed(2) : '—'} / {isValidNumber(match.odds?.away) ? match.odds.away.toFixed(2) : '—'}</span>
              </div>
              {match.forebet?.prediction && isValidNumber(match.forebet?.probability) && (
                <div className="compare-row">
                  <span>Forebet</span>
                  <span className="value">{match.forebet.prediction} ({match.forebet.probability}%)</span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function LeagueGroup({ league, matches, country, compareMode, selectedMatches, onToggleSelect, isFavorite, onToggleFavorite, onPlaceBet }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className="league-group">
      <div className="league-header" onClick={() => setCollapsed(!collapsed)}>
        <Flag size={14} className="league-flag" />
        <span className="league-name">{league}</span>
        <span className="league-country">{country}</span>
        <span className="league-count">{matches.length}</span>
        {collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
      </div>
      {!collapsed && matches.map(match => (
        <MatchCard
          key={match.id}
          match={match}
          compareMode={compareMode}
          isSelected={selectedMatches.some(m => m.id === match.id)}
          onToggleSelect={onToggleSelect}
          isFavorite={isFavorite(match.id)}
          onToggleFavorite={onToggleFavorite}
          onPlaceBet={onPlaceBet}
        />
      ))}
    </div>
  )
}

function StatsBar({ stats, isLoading }) {
  return (
    <div className="stats-bar">
      <div className="stat-item">
        <Activity size={16} />
        <span className="stat-value">{isLoading ? '—' : stats.total}</span>
        <span className="stat-label">Total</span>
      </div>
      <div className="stat-item highlight">
        <Check size={16} />
        <span className="stat-value">{isLoading ? '—' : stats.qualifying}</span>
        <span className="stat-label">Qualifying</span>
      </div>
      <div className="stat-item">
        <TrendingUp size={16} />
        <span className="stat-value">{isLoading ? '—' : stats.formAdvantage}</span>
        <span className="stat-label">Form Adv.</span>
      </div>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="loading-state">
      <Loader2 size={48} className="spin" />
      <p>Loading matches...</p>
    </div>
  )
}

function ErrorState({ error, onRetry }) {
  return (
    <div className="error-state">
      <AlertCircle size={48} />
      <h3>Failed to load</h3>
      <p>{error}</p>
      <button className="retry-btn" onClick={onRetry}>
        <RefreshCw size={16} />
        Retry
      </button>
    </div>
  )
}

// Main App
function App() {
  const { theme, toggleTheme } = useTheme()
  const [activeSport, setActiveSport] = useState('all')
  const [date, setDate] = useState(new Date().toISOString().split('T')[0])
  const [searchQuery, setSearchQuery] = useState('')
  const [filters, setFilters] = useState({
    qualifying: false,
    formAdvantage: false,
    withOdds: false,
    sortBy: 'time'
  })

  const [matches, setMatches] = useState([])
  const [sports, setSports] = useState([])
  const [stats, setStats] = useState({ total: 0, qualifying: 0, formAdvantage: 0 })
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)

  // Compare mode state
  const [compareMode, setCompareMode] = useState(false)
  const [selectedMatches, setSelectedMatches] = useState([])

  // Tab navigation state
  const [activeTab, setActiveTab] = useState('matches') // 'matches' | 'calendar' | 'accuracy' | 'stats' | 'favorites'
  const [showNotificationPrompt, setShowNotificationPrompt] = useState(false)

  // Favorites
  const { favorites, isFavorite, toggleFavorite } = useFavorites()

  // Refs for keyboard shortcuts
  const searchInputRef = useRef(null)

  // Mobile sidebar state
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)

  // Bet calculator state
  const [showBetCalculator, setShowBetCalculator] = useState(false)
  const [betCalculatorOdds, setBetCalculatorOdds] = useState(null)

  // Bet modal state
  const [betModalOpen, setBetModalOpen] = useState(false)
  const [betModalData, setBetModalData] = useState(null)
  const [betStake, setBetStake] = useState(10)
  const [betSubmitting, setBetSubmitting] = useState(false)

  // Handle placing a bet
  const handlePlaceBet = useCallback((match, selection, odds) => {
    if (!odds) return
    setBetModalData({
      match,
      selection,
      odds
    })
    setBetStake(10) // Reset stake
    setBetModalOpen(true)
  }, [])

  // Submit bet to API
  const submitBet = async () => {
    if (!betModalData) return
    
    setBetSubmitting(true)
    try {
      const response = await fetch(`${API_BASE}/api/bets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          home_team: betModalData.match.homeTeam,
          away_team: betModalData.match.awayTeam,
          match_date: betModalData.match.date || date,
          match_time: betModalData.match.time,
          sport: betModalData.match.sport || 'football',
          league: betModalData.match.league,
          bet_selection: betModalData.selection,
          odds_at_bet: betModalData.odds,
          stake: betStake
        })
      })
      
      if (response.ok) {
        setBetModalOpen(false)
        setBetModalData(null)
        // Optionally show success notification
        alert(`Zakład zapisany: ${betModalData.match.homeTeam} vs ${betModalData.match.awayTeam} - ${betModalData.selection} @ ${betModalData.odds.toFixed(2)}`)
      } else {
        const errorData = await response.json()
        alert(`Błąd: ${errorData.error || 'Nie udało się zapisać zakładu'}`)
      }
    } catch (err) {
      console.error('Error placing bet:', err)
      alert('Błąd połączenia z serwerem')
    } finally {
      setBetSubmitting(false)
    }
  }

  // Load data - MUSI być przed useEffect który go używa!
  const loadData = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      const [matchData, sportsData] = await Promise.all([
        fetchMatches(date, activeSport),
        fetchSports(date)
      ])

      if (matchData) {
        setMatches(matchData.matches || [])
        setStats(matchData.stats || { total: 0, qualifying: 0, formAdvantage: 0 })
      }

      if (sportsData) {
        setSports(sportsData)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setIsLoading(false)
    }
  }, [date, activeSport])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ctrl+F - focus search
      if (e.ctrlKey && e.key === 'f') {
        e.preventDefault()
        searchInputRef.current?.focus()
      }
      // Ctrl+R - refresh
      if (e.ctrlKey && e.key === 'r') {
        e.preventDefault()
        loadData()
      }
      // Escape - clear search / close compare
      if (e.key === 'Escape') {
        if (searchQuery) setSearchQuery('')
        if (compareMode) {
          setCompareMode(false)
          setSelectedMatches([])
        }
      }
      // 1-5 - switch sports quickly
      if (!e.ctrlKey && !e.altKey && !e.metaKey) {
        const sportKeys = { '1': 'all', '2': 'football', '3': 'basketball', '4': 'volleyball', '5': 'tennis' }
        if (sportKeys[e.key] && document.activeElement.tagName !== 'INPUT') {
          setActiveSport(sportKeys[e.key])
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [searchQuery, compareMode, loadData])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Filter and sort matches
  const filteredMatches = matches.filter(m => {
    if (filters.qualifying && !m.qualifies) return false
    if (filters.formAdvantage && !m.formAdvantage) return false
    if (filters.withOdds && !isValidNumber(m.odds?.home)) return false
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      return m.homeTeam?.toLowerCase().includes(q) ||
        m.awayTeam?.toLowerCase().includes(q) ||
        m.league?.toLowerCase().includes(q)
    }
    return true
  }).sort((a, b) => {
    switch (filters.sortBy) {
      case 'h2h':
        return (b.h2h?.winRate || 0) - (a.h2h?.winRate || 0)
      case 'odds':
        // Sortuj od największego kursu do najmniejszego (najlepsze kursy pierwsze)
        const aOdds = isValidNumber(a.odds?.home) ? a.odds.home : 0
        const bOdds = isValidNumber(b.odds?.home) ? b.odds.home : 0
        return bOdds - aOdds
      case 'time':
      default:
        return (a.time || '').localeCompare(b.time || '')
    }
  })

  // Group by league
  const matchesByLeague = filteredMatches.reduce((acc, match) => {
    const key = `${match.country || 'Unknown'}-${match.league || 'Unknown'}`
    if (!acc[key]) acc[key] = { league: match.league || 'Unknown', country: match.country || '', matches: [] }
    acc[key].matches.push(match)
    return acc
  }, {})

  const handleFilterChange = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }))
  }

  const handleExport = (format) => {
    const dataToExport = selectedMatches.length > 0 ? selectedMatches : filteredMatches
    const filename = `bigone_${date}_${activeSport}`
    if (format === 'csv') {
      exportToCSV(dataToExport, `${filename}.csv`)
    } else {
      exportToJSON(dataToExport, `${filename}.json`)
    }
  }

  const handleToggleSelect = (match) => {
    setSelectedMatches(prev => {
      if (prev.some(m => m.id === match.id)) {
        return prev.filter(m => m.id !== match.id)
      }
      if (prev.length >= 4) return prev // Max 4 matches
      return [...prev, match]
    })
  }

  const handleToggleCompare = () => {
    setCompareMode(!compareMode)
    if (compareMode) {
      setSelectedMatches([])
    }
  }

  return (
    <div className={`app theme-${theme}`}>
      {/* Mobile overlay */}
      {mobileSidebarOpen && (
        <div className="mobile-overlay" onClick={() => setMobileSidebarOpen(false)} />
      )}

      <div className={`sidebar-wrapper ${mobileSidebarOpen ? 'open' : ''}`}>
        <Sidebar
          sports={sports}
          activeSport={activeSport}
          onSportChange={(sport) => { setActiveSport(sport); setMobileSidebarOpen(false); }}
          filters={filters}
          onFilterChange={handleFilterChange}
        />
      </div>

      <div className="main-content">
        <Header
          date={date}
          onDateChange={setDate}
          searchQuery={searchQuery}
          onSearch={setSearchQuery}
          onRefresh={loadData}
          isLoading={isLoading}
          theme={theme}
          toggleTheme={toggleTheme}
          onExport={handleExport}
          compareMode={compareMode}
          onToggleCompare={handleToggleCompare}
          searchInputRef={searchInputRef}
          onToggleMobileMenu={() => setMobileSidebarOpen(!mobileSidebarOpen)}
          onOpenCalculator={() => setShowBetCalculator(true)}
        />

        <div className="content-area">
          {/* Tab Navigation */}
          <div className="tabs-nav">
            <button
              className={`tab-btn ${activeTab === 'matches' ? 'active' : ''}`}
              onClick={() => setActiveTab('matches')}
            >
              <List size={16} />
              <span>Mecze</span>
            </button>
            <button
              className={`tab-btn ${activeTab === 'calendar' ? 'active' : ''}`}
              onClick={() => setActiveTab('calendar')}
            >
              <CalendarIcon size={16} />
              <span>Kalendarz</span>
            </button>
            <button
              className={`tab-btn ${activeTab === 'accuracy' ? 'active' : ''}`}
              onClick={() => setActiveTab('accuracy')}
            >
              <PieChart size={16} />
              <span>Trafność</span>
            </button>
            <button
              className={`tab-btn ${activeTab === 'stats' ? 'active' : ''}`}
              onClick={() => setActiveTab('stats')}
            >
              <BarChart3 size={16} />
              <span>Stats</span>
            </button>
            <button
              className={`tab-btn ${activeTab === 'favorites' ? 'active' : ''}`}
              onClick={() => setActiveTab('favorites')}
            >
              <Star size={16} />
              <span>Ulubione ({favorites.length})</span>
            </button>
          </div>

          <StatsBar stats={stats} isLoading={isLoading} />

          {/* Tab Content */}
          {activeTab === 'matches' && (
            <>
              {/* Compare Panel */}
              {compareMode && (
                <ComparePanel
                  selectedMatches={selectedMatches}
                  onRemove={(m) => setSelectedMatches(prev => prev.filter(x => x.id !== m.id))}
                  onClear={() => setSelectedMatches([])}
                />
              )}

              {isLoading ? (
                <LoadingState />
              ) : error ? (
                <ErrorState error={error} onRetry={loadData} />
              ) : Object.keys(matchesByLeague).length === 0 ? (
                <div className="empty-state">
                  <AlertCircle size={48} />
                  <h3>No matches found</h3>
                  <p>Try adjusting your filters</p>
                </div>
              ) : (
                Object.entries(matchesByLeague).map(([key, data]) => (
                  <LeagueGroup
                    key={key}
                    league={data.league}
                    country={data.country}
                    matches={data.matches}
                    compareMode={compareMode}
                    selectedMatches={selectedMatches}
                    onToggleSelect={handleToggleSelect}
                    isFavorite={isFavorite}
                    onToggleFavorite={toggleFavorite}
                    onPlaceBet={handlePlaceBet}
                  />
                ))
              )}
            </>
          )}

          {activeTab === 'calendar' && (
            <Calendar
              matches={matches}
              onDateSelect={(newDate) => setDate(newDate)}
              selectedDate={date}
            />
          )}

          {activeTab === 'accuracy' && (
            <AccuracyChart apiBase={API_BASE} />
          )}

          {activeTab === 'stats' && (
            <StatsDashboard apiBase={API_BASE} />
          )}

          {activeTab === 'favorites' && (
            <div className="favorites-tab">
              <h3 className="favorites-title">
                <Star size={20} />
                Ulubione mecze ({favorites.length})
              </h3>
              {favorites.length === 0 ? (
                <div className="empty-state">
                  <Star size={48} />
                  <h3>Brak ulubionych meczów</h3>
                  <p>Kliknij ⭐ przy meczu, aby dodać do ulubionych</p>
                </div>
              ) : (
                <div className="favorites-list">
                  {favorites.map(match => (
                    <MatchCard
                      key={match.id}
                      match={match}
                      compareMode={false}
                      isSelected={false}
                      onToggleSelect={() => { }}
                      isFavorite={true}
                      onToggleFavorite={toggleFavorite}
                      onPlaceBet={handlePlaceBet}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Notification Prompt */}
          {showNotificationPrompt && (
            <NotificationPrompt onClose={() => setShowNotificationPrompt(false)} />
          )}
        </div>
      </div>

      {/* Quick Bet Calculator Modal */}
      <QuickBetCalculator
        isOpen={showBetCalculator}
        onClose={() => setShowBetCalculator(false)}
        initialOdds={betCalculatorOdds}
      />

      {/* Bet Placement Modal */}
      {betModalOpen && betModalData && (
        <div className="modal-overlay" onClick={() => setBetModalOpen(false)}>
          <div className="bet-modal" onClick={(e) => e.stopPropagation()}>
            <div className="bet-modal-header">
              <h3>Postaw zakład</h3>
              <button className="close-btn" onClick={() => setBetModalOpen(false)}>
                <X size={20} />
              </button>
            </div>
            <div className="bet-modal-content">
              <div className="bet-match-info">
                <span className="bet-teams">{betModalData.match.homeTeam} vs {betModalData.match.awayTeam}</span>
                <span className="bet-league">{betModalData.match.league || 'Unknown League'}</span>
                <span className="bet-time">{betModalData.match.date} • {betModalData.match.time}</span>
              </div>
              
              <div className="bet-selection-info">
                <div className="bet-selection-label">
                  Twój wybór: <span className={`selection-badge ${betModalData.selection === '1' ? 'home' : betModalData.selection === 'X' ? 'draw' : 'away'}`}>
                    {betModalData.selection === '1' ? `${betModalData.match.homeTeam} (1)` : 
                     betModalData.selection === 'X' ? 'Remis (X)' : 
                     `${betModalData.match.awayTeam} (2)`}
                  </span>
                </div>
                <div className="bet-odds-display">
                  Kurs: <strong>{betModalData.odds.toFixed(2)}</strong>
                </div>
              </div>

              <div className="bet-stake-section">
                <label htmlFor="stake">Stawka (PLN)</label>
                <div className="stake-input-wrapper">
                  <input
                    type="number"
                    id="stake"
                    min="1"
                    step="1"
                    value={betStake}
                    onChange={(e) => setBetStake(Math.max(1, parseFloat(e.target.value) || 0))}
                  />
                  <div className="stake-presets">
                    {[10, 25, 50, 100].map(amount => (
                      <button
                        key={amount}
                        className={`stake-preset ${betStake === amount ? 'active' : ''}`}
                        onClick={() => setBetStake(amount)}
                      >
                        {amount}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="bet-potential-win">
                <span>Potencjalna wygrana:</span>
                <strong className="win-amount">{(betStake * betModalData.odds).toFixed(2)} PLN</strong>
                <span className="profit">(+{(betStake * (betModalData.odds - 1)).toFixed(2)} PLN profit)</span>
              </div>

              <div className="bet-modal-actions">
                <button className="btn-secondary" onClick={() => setBetModalOpen(false)}>
                  Anuluj
                </button>
                <button 
                  className="btn-primary" 
                  onClick={submitBet}
                  disabled={betSubmitting || betStake <= 0}
                >
                  {betSubmitting ? (
                    <>
                      <Loader2 size={16} className="spin" />
                      Zapisuję...
                    </>
                  ) : (
                    <>
                      <Check size={16} />
                      Postaw zakład
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
