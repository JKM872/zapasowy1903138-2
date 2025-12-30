import { useState, useEffect } from 'react';
import { TrendingUp, Target, Award, RefreshCw } from 'lucide-react';

/**
 * AccuracyChart Component - Wykres historycznej trafności predykcji
 * Wyświetla porównanie skuteczności różnych źródeł danych
 */
const AccuracyChart = ({ apiBase = 'http://localhost:5000' }) => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [timeRange, setTimeRange] = useState(30);

    // Kolory źródeł
    const sourceColors = {
        forebet: { bg: 'bg-purple-500', text: 'text-purple-400', hex: '#a855f7' },
        sofascore: { bg: 'bg-blue-500', text: 'text-blue-400', hex: '#3b82f6' },
        gemini: { bg: 'bg-emerald-500', text: 'text-emerald-400', hex: '#10b981' },
        h2h: { bg: 'bg-orange-500', text: 'text-orange-400', hex: '#f97316' },
        consensus: { bg: 'bg-yellow-500', text: 'text-yellow-400', hex: '#eab308' }
    };

    // Pobierz dane z API
    const fetchAccuracy = async () => {
        setLoading(true);
        setError(null);

        try {
            const response = await fetch(`${apiBase}/api/accuracy?days=${timeRange}`);
            if (!response.ok) throw new Error('Błąd pobierania danych');

            const result = await response.json();
            setData(result);
        } catch (err) {
            setError(err.message);
            // Dane demonstracyjne w przypadku błędu
            setData({
                sources: [
                    { name: 'Forebet', key: 'forebet', accuracy: 62, total: 145, correct: 90 },
                    { name: 'SofaScore Fan Vote', key: 'sofascore', accuracy: 58, total: 130, correct: 75 },
                    { name: 'Gemini AI', key: 'gemini', accuracy: 65, total: 120, correct: 78 },
                    { name: 'H2H Stats', key: 'h2h', accuracy: 55, total: 150, correct: 83 },
                    { name: 'Consensus (3/4)', key: 'consensus', accuracy: 72, total: 80, correct: 58 }
                ],
                period: `${timeRange} dni`,
                lastUpdated: new Date().toISOString()
            });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchAccuracy();
    }, [timeRange]);

    // Znajdź najlepsze źródło
    const bestSource = data?.sources?.reduce((best, current) =>
        !best || current.accuracy > best.accuracy ? current : best
        , null);

    // Renderuj pasek trafności
    const AccuracyBar = ({ source }) => {
        const color = sourceColors[source.key] || sourceColors.h2h;
        const barWidth = Math.min(source.accuracy, 100);

        return (
            <div className="accuracy-bar-container">
                <div className="flex justify-between items-center mb-1">
                    <span className={`text-sm font-medium ${color.text}`}>
                        {source.name}
                    </span>
                    <span className="text-sm text-gray-400">
                        {source.accuracy}% ({source.correct}/{source.total})
                    </span>
                </div>
                <div className="accuracy-bar-bg h-3 rounded-full bg-white/10 overflow-hidden">
                    <div
                        className={`accuracy-bar-fill h-full rounded-full ${color.bg} transition-all duration-500`}
                        style={{ width: `${barWidth}%` }}
                    />
                </div>
            </div>
        );
    };

    if (loading) {
        return (
            <div className="accuracy-chart glass-card p-6 animate-pulse">
                <div className="h-6 bg-white/10 rounded w-1/3 mb-4"></div>
                <div className="space-y-4">
                    {[1, 2, 3, 4, 5].map(i => (
                        <div key={i}>
                            <div className="h-4 bg-white/10 rounded w-1/4 mb-2"></div>
                            <div className="h-3 bg-white/10 rounded"></div>
                        </div>
                    ))}
                </div>
            </div>
        );
    }

    return (
        <div className="accuracy-chart glass-card p-6">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-gradient-to-br from-green-500/20 to-emerald-500/20">
                        <Target className="text-green-400" size={24} />
                    </div>
                    <div>
                        <h3 className="text-lg font-semibold">Trafność Predykcji</h3>
                        <p className="text-sm text-gray-400">Ostatnie {timeRange} dni</p>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    {/* Time range selector */}
                    <select
                        value={timeRange}
                        onChange={(e) => setTimeRange(Number(e.target.value))}
                        className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-accent/50"
                    >
                        <option value={7}>7 dni</option>
                        <option value={14}>14 dni</option>
                        <option value={30}>30 dni</option>
                        <option value={90}>90 dni</option>
                    </select>

                    <button
                        onClick={fetchAccuracy}
                        className="p-2 rounded-lg hover:bg-white/10 transition-colors"
                        title="Odśwież"
                    >
                        <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>
            </div>

            {/* Best source badge */}
            {bestSource && (
                <div className="best-source-badge flex items-center gap-2 p-3 rounded-lg bg-gradient-to-r from-yellow-500/20 to-orange-500/20 border border-yellow-500/30 mb-6">
                    <Award className="text-yellow-400" size={20} />
                    <span className="text-sm">
                        Najlepsza trafność: <strong className="text-yellow-400">{bestSource.name}</strong> z {bestSource.accuracy}%
                    </span>
                </div>
            )}

            {/* Error message */}
            {error && (
                <div className="error-message p-3 rounded-lg bg-red-500/10 border border-red-500/30 mb-4 text-sm text-red-400">
                    ⚠️ {error} - wyświetlam dane demonstracyjne
                </div>
            )}

            {/* Accuracy bars */}
            <div className="accuracy-bars space-y-4">
                {data?.sources?.map((source) => (
                    <AccuracyBar key={source.key} source={source} />
                ))}
            </div>

            {/* Stats summary */}
            <div className="stats-summary grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-white/10">
                <div className="stat-item text-center">
                    <div className="text-2xl font-bold text-green-400">
                        {data?.sources?.reduce((sum, s) => sum + s.correct, 0) || 0}
                    </div>
                    <div className="text-xs text-gray-400">Trafione</div>
                </div>
                <div className="stat-item text-center">
                    <div className="text-2xl font-bold text-red-400">
                        {data?.sources?.reduce((sum, s) => sum + (s.total - s.correct), 0) || 0}
                    </div>
                    <div className="text-xs text-gray-400">Nietrafione</div>
                </div>
                <div className="stat-item text-center">
                    <div className="text-2xl font-bold text-blue-400">
                        {data?.sources?.reduce((sum, s) => sum + s.total, 0) || 0}
                    </div>
                    <div className="text-xs text-gray-400">Łącznie</div>
                </div>
            </div>

            {/* Last updated */}
            {data?.lastUpdated && (
                <div className="text-xs text-gray-500 text-center mt-4">
                    Ostatnia aktualizacja: {new Date(data.lastUpdated).toLocaleString('pl-PL')}
                </div>
            )}
        </div>
    );
};

export default AccuracyChart;
