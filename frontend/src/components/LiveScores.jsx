import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Activity,
  RefreshCw,
  Clock,
  TrendingUp,
  AlertCircle,
  Play,
  Pause,
  Circle,
  Target,
  AlertTriangle,
  MapPin,
  Volume2,
  VolumeX,
  Flame,
  Snowflake
} from 'lucide-react';

/**
 * LiveScores - komponent do wyświetlania wyników na żywo
 * 
 * Funkcje:
 * - Auto-refresh co 30 sekund
 * - Animacje zmian wyniku
 * - Wskaźnik czasu meczu
 * - Filtrowanie po sportach
 * - Sound notifications for score changes
 */

const API_BASE = 'http://localhost:5000';

// Sound notification - goal sound (base64 encoded short beep)
const GOAL_SOUND_URL = 'data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2teleR8FA5nL1saQSTMpVnSTqZeAfnM/P0BLVkxVXHuYpYxrU0JDb4qgpoNmUUdPdZuun4p2YVFWbpitp4Z4aF5gdJOuqId2c3B2d4WZpJZ+eHeAhoiQmZqOfXyDiIuPlJiVjIaFiIuJioqKh4WFhoiIiIqIhYWDg4aIiIeHhoaFhYeIiIiIhYSFhoaGh4eHhoaHh4iIh4aGhoaGh4eHhoaGhoaHh4eHhoaGhoaGhoaGhg==';

// Event icon component
const EventIcon = ({ type }) => {
  switch (type) {
    case 'goal':
      return <Target size={12} className="event-icon-svg goal" />;
    case 'card':
      return <AlertTriangle size={12} className="event-icon-svg card" />;
    default:
      return <MapPin size={12} className="event-icon-svg" />;
  }
};

// Demo data dla testów
const DEMO_LIVE_MATCHES = [
  {
    id: 'live_1',
    homeTeam: 'Manchester United',
    awayTeam: 'Chelsea',
    homeScore: 2,
    awayScore: 1,
    minute: 67,
    status: 'live',
    sport: 'football',
    league: 'Premier League',
    homeStreak: 'hot',
    events: [
      { minute: 12, type: 'goal', team: 'home', player: 'Rashford' },
      { minute: 34, type: 'goal', team: 'away', player: 'Palmer' },
      { minute: 58, type: 'goal', team: 'home', player: 'Fernandes' }
    ]
  },
  {
    id: 'live_2',
    homeTeam: 'Real Madrid',
    awayTeam: 'Barcelona',
    homeScore: 1,
    awayScore: 1,
    minute: 45,
    status: 'halftime',
    sport: 'football',
    league: 'La Liga',
    awayStreak: 'cold',
    events: [
      { minute: 23, type: 'goal', team: 'home', player: 'Vinicius' },
      { minute: 41, type: 'goal', team: 'away', player: 'Lewandowski' }
    ]
  },
  {
    id: 'live_3',
    homeTeam: 'Lakers',
    awayTeam: 'Warriors',
    homeScore: 87,
    awayScore: 92,
    minute: 'Q3 4:32',
    status: 'live',
    sport: 'basketball',
    league: 'NBA',
    events: []
  }
];

function LiveScores({ apiBase = API_BASE }) {
  const [matches, setMatches] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selectedSport, setSelectedSport] = useState('all');
  const [changedScores, setChangedScores] = useState(new Set());
  const [soundEnabled, setSoundEnabled] = useState(true);

  // Audio ref for sound notifications
  const audioRef = useRef(null);

  // Play sound notification
  const playGoalSound = useCallback(() => {
    if (soundEnabled && audioRef.current) {
      audioRef.current.currentTime = 0;
      audioRef.current.play().catch(e => console.log('Audio play failed:', e));
    }
  }, [soundEnabled]);

  // Fetch live matches
  const fetchLiveMatches = useCallback(async () => {
    try {
      const response = await fetch(`${apiBase}/api/live`);

      if (response.ok) {
        const data = await response.json();

        // Detect score changes for animation
        if (matches.length > 0) {
          const changes = new Set();
          data.matches?.forEach(newMatch => {
            const oldMatch = matches.find(m => m.id === newMatch.id);
            if (oldMatch && (oldMatch.homeScore !== newMatch.homeScore || oldMatch.awayScore !== newMatch.awayScore)) {
              changes.add(newMatch.id);
              // Play sound for score change!
              playGoalSound();
            }
          });
          setChangedScores(changes);

          // Clear animation after 3 seconds
          setTimeout(() => setChangedScores(new Set()), 3000);
        }

        setMatches(data.matches || DEMO_LIVE_MATCHES);
        setError(null);
      } else {
        // Use demo data on API error
        setMatches(DEMO_LIVE_MATCHES);
      }
    } catch (err) {
      console.log('Live scores API error, using demo data');
      setMatches(DEMO_LIVE_MATCHES);
    } finally {
      setIsLoading(false);
      setLastUpdate(new Date());
    }
  }, [apiBase, matches, playGoalSound]);

  // Initial fetch
  useEffect(() => {
    fetchLiveMatches();
  }, []);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(fetchLiveMatches, 30000); // 30 seconds
    return () => clearInterval(interval);
  }, [autoRefresh, fetchLiveMatches]);

  // Filter matches
  const filteredMatches = matches.filter(match =>
    selectedSport === 'all' || match.sport === selectedSport
  );

  // Get unique sports
  const sports = ['all', ...new Set(matches.map(m => m.sport))];

  const getStatusColor = (status) => {
    switch (status) {
      case 'live': return 'var(--accent-green, #2ea043)';
      case 'halftime': return 'var(--accent-yellow, #d29922)';
      case 'finished': return 'var(--text-muted, #6e7681)';
      default: return 'var(--accent-blue, #58a6ff)';
    }
  };

  const getStatusText = (status, minute) => {
    switch (status) {
      case 'live': return typeof minute === 'number' ? `${minute}'` : minute;
      case 'halftime': return 'HT';
      case 'finished': return 'FT';
      default: return status;
    }
  };

  return (
    <div className="live-scores">
      {/* Hidden audio element for sound notifications */}
      <audio ref={audioRef} src={GOAL_SOUND_URL} preload="auto" />
      {/* Header */}
      <div className="live-header">
        <div className="live-title">
          <Activity size={20} className="pulse" style={{ color: 'var(--accent-green)' }} />
          <h2>Live Scores</h2>
          <span className="live-count">{filteredMatches.length}</span>
        </div>

        <div className="live-controls">
          {/* Sport filter */}
          <div className="sport-filter">
            {sports.map(sport => (
              <button
                key={sport}
                className={`filter-btn ${selectedSport === sport ? 'active' : ''}`}
                onClick={() => setSelectedSport(sport)}
              >
                {sport === 'all' ? 'All' : sport.charAt(0).toUpperCase() + sport.slice(1)}
              </button>
            ))}
          </div>

          {/* Auto-refresh toggle */}
          <button
            className={`refresh-toggle ${autoRefresh ? 'active' : ''}`}
            onClick={() => setAutoRefresh(!autoRefresh)}
            title={autoRefresh ? 'Auto-refresh ON' : 'Auto-refresh OFF'}
          >
            {autoRefresh ? <Play size={14} /> : <Pause size={14} />}
          </button>

          {/* Manual refresh */}
          <button
            className="refresh-btn"
            onClick={fetchLiveMatches}
            disabled={isLoading}
          >
            <RefreshCw size={16} className={isLoading ? 'spin' : ''} />
          </button>

          {/* Sound toggle */}
          <button
            className={`sound-toggle ${soundEnabled ? 'active' : ''}`}
            onClick={() => setSoundEnabled(!soundEnabled)}
            title={soundEnabled ? 'Sound ON' : 'Sound OFF'}
          >
            {soundEnabled ? <Volume2 size={14} /> : <VolumeX size={14} />}
          </button>
        </div>
      </div>

      {/* Last update timestamp */}
      {lastUpdate && (
        <div className="last-update">
          <Clock size={12} />
          <span>Updated: {lastUpdate.toLocaleTimeString()}</span>
        </div>
      )}

      {/* Matches list */}
      <div className="live-matches">
        {isLoading && matches.length === 0 ? (
          <div className="loading-state">
            <RefreshCw size={24} className="spin" />
            <p>Loading live matches...</p>
          </div>
        ) : filteredMatches.length === 0 ? (
          <div className="empty-state">
            <AlertCircle size={32} />
            <p>No live matches at the moment</p>
          </div>
        ) : (
          filteredMatches.map(match => (
            <div
              key={match.id}
              className={`live-match ${changedScores.has(match.id) ? 'score-changed' : ''}`}
            >
              {/* Status indicator */}
              <div className="match-status" style={{ '--status-color': getStatusColor(match.status) }}>
                <Circle size={8} className={match.status === 'live' ? 'pulse' : ''} />
                <span>{getStatusText(match.status, match.minute)}</span>
              </div>

              {/* Teams and score */}
              <div className="match-content">
                <div className="team home">
                  <span className="team-name">
                    {match.homeTeam}
                    {match.homeStreak === 'hot' && <Flame size={12} className="streak-icon hot" />}
                    {match.homeStreak === 'cold' && <Snowflake size={12} className="streak-icon cold" />}
                  </span>
                  <span className={`score ${changedScores.has(match.id) ? 'flash' : ''}`}>
                    {match.homeScore}
                  </span>
                </div>
                <div className="team away">
                  <span className="team-name">
                    {match.awayTeam}
                    {match.awayStreak === 'hot' && <Flame size={12} className="streak-icon hot" />}
                    {match.awayStreak === 'cold' && <Snowflake size={12} className="streak-icon cold" />}
                  </span>
                  <span className={`score ${changedScores.has(match.id) ? 'flash' : ''}`}>
                    {match.awayScore}
                  </span>
                </div>
              </div>

              {/* League */}
              <div className="match-league">
                {match.league}
              </div>

              {/* Recent events */}
              {match.events && match.events.length > 0 && (
                <div className="match-events">
                  {match.events.slice(-3).map((event, idx) => (
                    <div key={idx} className={`event ${event.type}`}>
                      <span className="event-minute">{event.minute}'</span>
                      <EventIcon type={event.type} />
                      <span className="event-player">{event.player}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <style jsx>{`
        .live-scores {
          background: var(--bg-secondary, #161b22);
          border: 1px solid var(--border-color, #30363d);
          border-radius: 12px;
          padding: 20px;
        }

        .live-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }

        .live-title {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .live-title h2 {
          font-size: 1.1rem;
          font-weight: 600;
          margin: 0;
          color: var(--text-primary, #e6edf3);
        }

        .live-count {
          background: var(--accent-green, #2ea043);
          color: white;
          font-size: 12px;
          font-weight: 600;
          padding: 2px 8px;
          border-radius: 10px;
        }

        .live-controls {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .sport-filter {
          display: flex;
          gap: 4px;
        }

        .filter-btn {
          background: transparent;
          border: 1px solid var(--border-color, #30363d);
          color: var(--text-secondary, #8b949e);
          padding: 4px 10px;
          border-radius: 6px;
          font-size: 12px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .filter-btn:hover {
          background: var(--bg-tertiary, #21262d);
        }

        .filter-btn.active {
          background: var(--accent-blue, #58a6ff);
          border-color: var(--accent-blue, #58a6ff);
          color: white;
        }

        .refresh-toggle, .refresh-btn {
          background: var(--bg-tertiary, #21262d);
          border: 1px solid var(--border-color, #30363d);
          color: var(--text-secondary, #8b949e);
          padding: 6px;
          border-radius: 6px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .refresh-toggle:hover, .refresh-btn:hover {
          color: var(--text-primary, #e6edf3);
        }

        .refresh-toggle.active {
          color: var(--accent-green, #2ea043);
        }

        .last-update {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 11px;
          color: var(--text-muted, #6e7681);
          margin-bottom: 12px;
        }

        .live-matches {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .live-match {
          background: var(--bg-tertiary, #21262d);
          border: 1px solid var(--border-muted, #21262d);
          border-radius: 8px;
          padding: 12px;
          transition: all 0.3s;
        }

        .live-match:hover {
          border-color: var(--border-color, #30363d);
        }

        .live-match.score-changed {
          animation: highlight 0.5s ease;
          border-color: var(--accent-green, #2ea043);
        }

        @keyframes highlight {
          0%, 100% { background: var(--bg-tertiary, #21262d); }
          50% { background: rgba(46, 160, 67, 0.2); }
        }

        .match-status {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-bottom: 8px;
          font-size: 12px;
          font-weight: 600;
          color: var(--status-color);
        }

        .match-content {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .team {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .team-name {
          font-weight: 500;
          color: var(--text-primary, #e6edf3);
        }

        .score {
          font-size: 1.2rem;
          font-weight: 700;
          color: var(--text-primary, #e6edf3);
          min-width: 24px;
          text-align: center;
        }

        .score.flash {
          animation: scoreFlash 0.5s ease 3;
        }

        @keyframes scoreFlash {
          0%, 100% { color: var(--text-primary, #e6edf3); }
          50% { color: var(--accent-green, #2ea043); transform: scale(1.2); }
        }

        .match-league {
          font-size: 11px;
          color: var(--text-muted, #6e7681);
          margin-top: 8px;
          padding-top: 8px;
          border-top: 1px solid var(--border-muted, #21262d);
        }

        .match-events {
          margin-top: 8px;
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .event {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 11px;
          background: var(--bg-secondary, #161b22);
          padding: 2px 6px;
          border-radius: 4px;
        }

        .event-minute {
          color: var(--text-muted, #6e7681);
        }

        .event-player {
          color: var(--text-secondary, #8b949e);
        }

        .event-icon-svg {
          flex-shrink: 0;
        }

        .event-icon-svg.goal {
          color: var(--accent-green, #2ea043);
        }

        .event-icon-svg.card {
          color: var(--accent-yellow, #d29922);
        }

        .loading-state, .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 32px;
          color: var(--text-muted, #6e7681);
          gap: 12px;
        }

        .pulse {
          animation: pulse 2s ease infinite;
        }

        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }

        .spin {
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }

        @media (max-width: 480px) {
          .sport-filter {
            display: none;
          }
        }
      `}</style>
    </div>
  );
}

export default LiveScores;
