import { useState, useEffect, useCallback } from 'react';
import {
    TrendingUp,
    TrendingDown,
    BarChart3,
    PieChart,
    RefreshCw,
    Calendar,
    Target,
    Percent,
    DollarSign,
    Award,
    Activity,
    ChevronDown
} from 'lucide-react';

/**
 * StatsDashboard - Zaawansowany dashboard ze statystykami
 * 
 * Wyświetla:
 * - ROI w czasie
 * - Trafność per źródło
 * - Breakdown per sport
 * - Top performing sources
 */

const API_BASE = 'http://localhost:5000';

// Demo data
const DEMO_STATS = {
    roi: {
        current: 12.5,
        previous: 8.2,
        trend: 'up',
        history: [
            { date: '2024-12-10', value: 5.2 },
            { date: '2024-12-11', value: 6.8 },
            { date: '2024-12-12', value: 8.1 },
            { date: '2024-12-13', value: 7.5 },
            { date: '2024-12-14', value: 10.2 },
            { date: '2024-12-15', value: 11.8 },
            { date: '2024-12-16', value: 12.5 }
        ]
    },
    accuracy: {
        overall: 62.5,
        bySport: [
            { sport: 'football', accuracy: 65.2, total: 150 },
            { sport: 'basketball', accuracy: 58.4, total: 85 },
            { sport: 'volleyball', accuracy: 71.3, total: 42 },
            { sport: 'handball', accuracy: 54.8, total: 28 },
            { sport: 'hockey', accuracy: 60.0, total: 35 }
        ],
        bySource: [
            { source: 'Forebet', accuracy: 58.5, weight: 1.2 },
            { source: 'SofaScore', accuracy: 52.3, weight: 1.0 },
            { source: 'Gemini AI', accuracy: 68.7, weight: 1.5 },
            { source: 'H2H', accuracy: 61.2, weight: 1.0 },
            { source: 'Consensus', accuracy: 72.4, weight: 2.0 }
        ]
    },
    bets: {
        total: 342,
        wins: 214,
        losses: 128,
        pending: 15,
        streak: 4,
        bestStreak: 8
    }
};

function StatsDashboard({ apiBase = API_BASE }) {
    const [stats, setStats] = useState(DEMO_STATS);
    const [isLoading, setIsLoading] = useState(false);
    const [period, setPeriod] = useState(30);
    const [activeSection, setActiveSection] = useState('overview');

    const fetchStats = useCallback(async () => {
        setIsLoading(true);
        try {
            const [roiRes, accuracyRes] = await Promise.all([
                fetch(`${apiBase}/api/roi?days=${period}`),
                fetch(`${apiBase}/api/accuracy?days=${period}`)
            ]);

            if (roiRes.ok && accuracyRes.ok) {
                const roiData = await roiRes.json();
                const accData = await accuracyRes.json();

                setStats(prev => ({
                    ...prev,
                    roi: { ...prev.roi, ...roiData.stats },
                    accuracy: { ...prev.accuracy, ...accData }
                }));
            }
        } catch (err) {
            console.log('Using demo stats');
        } finally {
            setIsLoading(false);
        }
    }, [apiBase, period]);

    useEffect(() => {
        fetchStats();
    }, [period]);

    const winRate = stats.bets.total > 0
        ? ((stats.bets.wins / (stats.bets.wins + stats.bets.losses)) * 100).toFixed(1)
        : 0;

    return (
        <div className="stats-dashboard">
            {/* Header */}
            <div className="stats-header">
                <div className="stats-title">
                    <BarChart3 size={24} />
                    <h2>Statistics Dashboard</h2>
                </div>

                <div className="stats-controls">
                    <select
                        value={period}
                        onChange={(e) => setPeriod(Number(e.target.value))}
                        className="period-select"
                    >
                        <option value={7}>Last 7 days</option>
                        <option value={14}>Last 14 days</option>
                        <option value={30}>Last 30 days</option>
                        <option value={90}>Last 90 days</option>
                    </select>

                    <button
                        className="refresh-btn"
                        onClick={fetchStats}
                        disabled={isLoading}
                    >
                        <RefreshCw size={16} className={isLoading ? 'spin' : ''} />
                    </button>
                </div>
            </div>

            {/* KPI Cards */}
            <div className="kpi-grid">
                <div className="kpi-card roi">
                    <div className="kpi-icon">
                        <DollarSign size={20} />
                    </div>
                    <div className="kpi-content">
                        <span className="kpi-label">ROI</span>
                        <span className={`kpi-value ${stats.roi.current >= 0 ? 'positive' : 'negative'}`}>
                            {stats.roi.current >= 0 ? '+' : ''}{stats.roi.current}%
                        </span>
                        <span className="kpi-change">
                            {stats.roi.current > stats.roi.previous ? (
                                <><TrendingUp size={12} /> +{(stats.roi.current - stats.roi.previous).toFixed(1)}%</>
                            ) : (
                                <><TrendingDown size={12} /> {(stats.roi.current - stats.roi.previous).toFixed(1)}%</>
                            )}
                        </span>
                    </div>
                </div>

                <div className="kpi-card accuracy">
                    <div className="kpi-icon">
                        <Target size={20} />
                    </div>
                    <div className="kpi-content">
                        <span className="kpi-label">Accuracy</span>
                        <span className="kpi-value">{stats.accuracy.overall}%</span>
                        <span className="kpi-sub">{stats.bets.wins}W / {stats.bets.losses}L</span>
                    </div>
                </div>

                <div className="kpi-card bets">
                    <div className="kpi-icon">
                        <Activity size={20} />
                    </div>
                    <div className="kpi-content">
                        <span className="kpi-label">Total Bets</span>
                        <span className="kpi-value">{stats.bets.total}</span>
                        <span className="kpi-sub">{stats.bets.pending} pending</span>
                    </div>
                </div>

                <div className="kpi-card streak">
                    <div className="kpi-icon">
                        <Award size={20} />
                    </div>
                    <div className="kpi-content">
                        <span className="kpi-label">Win Streak</span>
                        <span className="kpi-value">{stats.bets.streak}</span>
                        <span className="kpi-sub">Best: {stats.bets.bestStreak}</span>
                    </div>
                </div>
            </div>

            {/* Accuracy by Source */}
            <div className="stats-section">
                <h3>
                    <PieChart size={18} />
                    Accuracy by Source
                </h3>
                <div className="source-bars">
                    {stats.accuracy.bySource.map((source, idx) => (
                        <div key={source.source} className="source-bar-item">
                            <div className="source-info">
                                <span className="source-name">{source.source}</span>
                                <span className="source-value">{source.accuracy}%</span>
                            </div>
                            <div className="source-bar-bg">
                                <div
                                    className="source-bar-fill"
                                    style={{
                                        width: `${source.accuracy}%`,
                                        background: `hsl(${120 * (source.accuracy / 100)}, 70%, 45%)`
                                    }}
                                />
                            </div>
                            <span className="source-weight">Weight: {source.weight}x</span>
                        </div>
                    ))}
                </div>
            </div>

            {/* Accuracy by Sport */}
            <div className="stats-section">
                <h3>
                    <BarChart3 size={18} />
                    Performance by Sport
                </h3>
                <div className="sport-grid">
                    {stats.accuracy.bySport.map((sport) => (
                        <div key={sport.sport} className="sport-card">
                            <div className="sport-name">{sport.sport}</div>
                            <div className="sport-accuracy">{sport.accuracy}%</div>
                            <div className="sport-total">{sport.total} predictions</div>
                            <div className="sport-bar">
                                <div
                                    className="sport-bar-fill"
                                    style={{ width: `${sport.accuracy}%` }}
                                />
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* ROI History Chart (simplified) */}
            <div className="stats-section">
                <h3>
                    <TrendingUp size={18} />
                    ROI History
                </h3>
                <div className="roi-chart">
                    {stats.roi.history.map((point, idx) => (
                        <div key={point.date} className="roi-bar-container">
                            <div
                                className={`roi-bar ${point.value >= 0 ? 'positive' : 'negative'}`}
                                style={{ height: `${Math.abs(point.value) * 4}px` }}
                            />
                            <span className="roi-date">{point.date.slice(-2)}</span>
                        </div>
                    ))}
                </div>
            </div>

            <style jsx>{`
        .stats-dashboard {
          padding: 20px;
          color: var(--text-primary, #e6edf3);
        }

        .stats-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 24px;
        }

        .stats-title {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .stats-title h2 {
          margin: 0;
          font-size: 1.25rem;
          font-weight: 600;
        }

        .stats-controls {
          display: flex;
          gap: 8px;
        }

        .period-select {
          background: var(--bg-tertiary, #21262d);
          border: 1px solid var(--border-color, #30363d);
          color: var(--text-primary);
          padding: 8px 12px;
          border-radius: 8px;
          font-size: 13px;
        }

        .refresh-btn {
          background: var(--bg-tertiary);
          border: 1px solid var(--border-color);
          color: var(--text-secondary);
          padding: 8px;
          border-radius: 8px;
          cursor: pointer;
        }

        .kpi-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 16px;
          margin-bottom: 24px;
        }

        .kpi-card {
          background: var(--bg-secondary, #161b22);
          border: 1px solid var(--border-color);
          border-radius: 12px;
          padding: 20px;
          display: flex;
          gap: 16px;
        }

        .kpi-icon {
          width: 44px;
          height: 44px;
          border-radius: 10px;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .kpi-card.roi .kpi-icon { background: rgba(46, 160, 67, 0.15); color: #2ea043; }
        .kpi-card.accuracy .kpi-icon { background: rgba(88, 166, 255, 0.15); color: #58a6ff; }
        .kpi-card.bets .kpi-icon { background: rgba(163, 113, 247, 0.15); color: #a371f7; }
        .kpi-card.streak .kpi-icon { background: rgba(210, 153, 34, 0.15); color: #d29922; }

        .kpi-content {
          display: flex;
          flex-direction: column;
        }

        .kpi-label {
          font-size: 12px;
          color: var(--text-muted, #6e7681);
          text-transform: uppercase;
        }

        .kpi-value {
          font-size: 1.5rem;
          font-weight: 700;
        }

        .kpi-value.positive { color: #2ea043; }
        .kpi-value.negative { color: #f85149; }

        .kpi-change, .kpi-sub {
          font-size: 12px;
          color: var(--text-muted);
          display: flex;
          align-items: center;
          gap: 4px;
        }

        .stats-section {
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: 12px;
          padding: 20px;
          margin-bottom: 16px;
        }

        .stats-section h3 {
          display: flex;
          align-items: center;
          gap: 8px;
          margin: 0 0 16px;
          font-size: 1rem;
          font-weight: 600;
        }

        .source-bars {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .source-bar-item {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .source-info {
          display: flex;
          justify-content: space-between;
        }

        .source-name { font-weight: 500; }
        .source-value { font-weight: 600; }

        .source-bar-bg {
          height: 8px;
          background: var(--bg-tertiary);
          border-radius: 4px;
          overflow: hidden;
        }

        .source-bar-fill {
          height: 100%;
          border-radius: 4px;
          transition: width 0.5s ease;
        }

        .source-weight {
          font-size: 11px;
          color: var(--text-muted);
        }

        .sport-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 12px;
        }

        .sport-card {
          background: var(--bg-tertiary);
          border-radius: 8px;
          padding: 16px;
          text-align: center;
        }

        .sport-name {
          text-transform: capitalize;
          font-weight: 500;
          margin-bottom: 4px;
        }

        .sport-accuracy {
          font-size: 1.5rem;
          font-weight: 700;
          color: var(--accent-green, #2ea043);
        }

        .sport-total {
          font-size: 11px;
          color: var(--text-muted);
          margin-bottom: 8px;
        }

        .sport-bar {
          height: 4px;
          background: var(--bg-secondary);
          border-radius: 2px;
          overflow: hidden;
        }

        .sport-bar-fill {
          height: 100%;
          background: var(--accent-green);
          transition: width 0.5s ease;
        }

        .roi-chart {
          display: flex;
          align-items: flex-end;
          gap: 8px;
          height: 100px;
          padding-top: 20px;
        }

        .roi-bar-container {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 4px;
        }

        .roi-bar {
          width: 100%;
          border-radius: 4px 4px 0 0;
          min-height: 4px;
        }

        .roi-bar.positive { background: var(--accent-green, #2ea043); }
        .roi-bar.negative { background: var(--accent-red, #f85149); }

        .roi-date {
          font-size: 10px;
          color: var(--text-muted);
        }

        .spin { animation: spin 1s linear infinite; }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
        </div>
    );
}

export default StatsDashboard;
