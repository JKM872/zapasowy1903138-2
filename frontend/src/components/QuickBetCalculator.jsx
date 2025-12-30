import { useState, useMemo } from 'react';
import { Calculator, X, DollarSign, TrendingUp, Plus, Trash2 } from 'lucide-react';

/**
 * QuickBetCalculator - Modal do szybkich obliczeń zakładów
 * 
 * Funkcje:
 * - Obliczanie potencjalnej wygranej
 * - Kalkulator akumulatorów
 * - Obliczanie ROI
 */

function QuickBetCalculator({ isOpen, onClose, initialOdds = null }) {
    const [stake, setStake] = useState(100);
    const [selections, setSelections] = useState(
        initialOdds ? [{ odds: initialOdds, id: 1 }] : [{ odds: 1.5, id: 1 }]
    );

    const addSelection = () => {
        const newId = Math.max(...selections.map(s => s.id), 0) + 1;
        setSelections([...selections, { odds: 1.5, id: newId }]);
    };

    const removeSelection = (id) => {
        if (selections.length > 1) {
            setSelections(selections.filter(s => s.id !== id));
        }
    };

    const updateOdds = (id, value) => {
        setSelections(selections.map(s =>
            s.id === id ? { ...s, odds: parseFloat(value) || 1 } : s
        ));
    };

    const totalOdds = useMemo(() => {
        return selections.reduce((acc, s) => acc * s.odds, 1);
    }, [selections]);

    const potentialWin = useMemo(() => {
        return stake * totalOdds;
    }, [stake, totalOdds]);

    const profit = useMemo(() => {
        return potentialWin - stake;
    }, [potentialWin, stake]);

    const impliedProbability = useMemo(() => {
        return (1 / totalOdds) * 100;
    }, [totalOdds]);

    if (!isOpen) return null;

    return (
        <div className="bet-calc-overlay" onClick={onClose}>
            <div className="bet-calc-modal" onClick={e => e.stopPropagation()}>
                <div className="bet-calc-header">
                    <div className="bet-calc-title">
                        <Calculator size={20} />
                        <h3>Quick Bet Calculator</h3>
                    </div>
                    <button className="close-btn" onClick={onClose}>
                        <X size={20} />
                    </button>
                </div>

                <div className="bet-calc-content">
                    {/* Stake Input */}
                    <div className="input-group">
                        <label>
                            <DollarSign size={14} />
                            Stake (PLN)
                        </label>
                        <input
                            type="number"
                            value={stake}
                            onChange={(e) => setStake(parseFloat(e.target.value) || 0)}
                            min="1"
                            step="10"
                        />
                    </div>

                    {/* Selections */}
                    <div className="selections-section">
                        <div className="section-header">
                            <span>Selections ({selections.length})</span>
                            <button className="add-btn" onClick={addSelection}>
                                <Plus size={14} /> Add
                            </button>
                        </div>

                        {selections.map((selection, idx) => (
                            <div key={selection.id} className="selection-row">
                                <span className="selection-num">{idx + 1}</span>
                                <input
                                    type="number"
                                    value={selection.odds}
                                    onChange={(e) => updateOdds(selection.id, e.target.value)}
                                    min="1.01"
                                    step="0.1"
                                />
                                {selections.length > 1 && (
                                    <button
                                        className="remove-btn"
                                        onClick={() => removeSelection(selection.id)}
                                    >
                                        <Trash2 size={14} />
                                    </button>
                                )}
                            </div>
                        ))}
                    </div>

                    {/* Results */}
                    <div className="results-section">
                        <div className="result-row">
                            <span>Total Odds:</span>
                            <span className="result-value">{totalOdds.toFixed(2)}</span>
                        </div>
                        <div className="result-row">
                            <span>Implied Probability:</span>
                            <span className="result-value">{impliedProbability.toFixed(1)}%</span>
                        </div>
                        <div className="result-row highlight">
                            <span>
                                <TrendingUp size={16} />
                                Potential Win:
                            </span>
                            <span className="result-value win">{potentialWin.toFixed(2)} PLN</span>
                        </div>
                        <div className="result-row profit">
                            <span>Profit:</span>
                            <span className="result-value">+{profit.toFixed(2)} PLN</span>
                        </div>
                    </div>
                </div>

                <style jsx>{`
          .bet-calc-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            backdrop-filter: blur(4px);
          }

          .bet-calc-modal {
            background: var(--bg-secondary, #161b22);
            border: 1px solid var(--border-color, #30363d);
            border-radius: 16px;
            width: 100%;
            max-width: 400px;
            max-height: 90vh;
            overflow: auto;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
          }

          .bet-calc-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-color);
          }

          .bet-calc-title {
            display: flex;
            align-items: center;
            gap: 10px;
            color: var(--text-primary, #e6edf3);
          }

          .bet-calc-title h3 {
            margin: 0;
            font-size: 1.1rem;
          }

          .close-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            padding: 4px;
            border-radius: 6px;
          }

          .close-btn:hover {
            background: var(--bg-tertiary);
            color: var(--text-primary);
          }

          .bet-calc-content {
            padding: 20px;
          }

          .input-group {
            margin-bottom: 20px;
          }

          .input-group label {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            color: var(--text-muted);
            margin-bottom: 8px;
          }

          .input-group input {
            width: 100%;
            background: var(--bg-tertiary, #21262d);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 12px;
            color: var(--text-primary);
            font-size: 1.2rem;
            font-weight: 600;
          }

          .input-group input:focus {
            outline: none;
            border-color: var(--accent-blue);
          }

          .selections-section {
            margin-bottom: 20px;
          }

          .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            font-size: 12px;
            color: var(--text-muted);
          }

          .add-btn {
            display: flex;
            align-items: center;
            gap: 4px;
            background: var(--accent-green);
            border: none;
            color: white;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            cursor: pointer;
          }

          .selection-row {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
          }

          .selection-num {
            width: 24px;
            height: 24px;
            background: var(--bg-tertiary);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            color: var(--text-muted);
          }

          .selection-row input {
            flex: 1;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 8px 12px;
            color: var(--text-primary);
            font-size: 1rem;
          }

          .remove-btn {
            background: transparent;
            border: none;
            color: var(--accent-red);
            cursor: pointer;
            padding: 6px;
          }

          .results-section {
            background: var(--bg-tertiary);
            border-radius: 12px;
            padding: 16px;
          }

          .result-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid var(--border-muted, #21262d);
            font-size: 13px;
          }

          .result-row:last-child {
            border-bottom: none;
          }

          .result-row span {
            display: flex;
            align-items: center;
            gap: 6px;
            color: var(--text-secondary);
          }

          .result-value {
            font-weight: 600;
            color: var(--text-primary) !important;
          }

          .result-row.highlight {
            padding: 12px 0;
          }

          .result-value.win {
            font-size: 1.25rem;
            color: var(--accent-green) !important;
          }

          .result-row.profit .result-value {
            color: var(--accent-green) !important;
          }
        `}</style>
            </div>
        </div>
    );
}

export default QuickBetCalculator;
