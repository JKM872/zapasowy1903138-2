import React from 'react'

export default function MatchDetail({ match, onClose }) {
  if (!match) return null

  const {
    home_team = 'Team A',
    away_team = 'Team B',
    time = '20:00',
    date = '',
    league = '',
    country = '',
    prediction = null,
    confidence = null,
    odds = {},
    form_home = [],
    form_away = [],
    h2h = [],
    stats = {},
    fan_vote = null
  } = match

  const renderForm = (form, teamName) => {
    if (!form || form.length === 0) return <span className="text-slate-500 text-sm">Brak danych</span>
    return (
      <div className="flex gap-1.5">
        {form.slice(-5).map((result, idx) => (
          <div 
            key={idx} 
            className={`w-7 h-7 rounded flex items-center justify-center text-xs font-bold ${
              result === 'W' ? 'bg-green-500/20 text-green-400 border border-green-500/30' : 
              result === 'D' ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' : 
              'bg-red-500/20 text-red-400 border border-red-500/30'
            }`}
          >
            {result}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.8)' }}>
      <div 
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl shadow-2xl"
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between p-4" style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border)' }}>
          <div>
            <div className="text-xs text-slate-400 mb-0.5">{country} • {league}</div>
            <div className="text-white font-medium">{home_team} vs {away_team}</div>
          </div>
          <button 
            onClick={onClose}
            className="w-8 h-8 rounded-full flex items-center justify-center text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-6">
          {/* Match Info */}
          <div className="flex items-center justify-center gap-8 py-6">
            <div className="text-center">
              <div className="w-16 h-16 rounded-full bg-slate-700 flex items-center justify-center text-2xl mb-2 mx-auto">
                ⚽
              </div>
              <div className="text-white font-medium">{home_team}</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-bold text-white">{time}</div>
              <div className="text-sm text-slate-400">{date}</div>
            </div>
            <div className="text-center">
              <div className="w-16 h-16 rounded-full bg-slate-700 flex items-center justify-center text-2xl mb-2 mx-auto">
                ⚽
              </div>
              <div className="text-white font-medium">{away_team}</div>
            </div>
          </div>

          {/* Prediction Box */}
          {prediction && (
            <div className="p-4 rounded-lg" style={{ background: 'var(--bg-secondary)' }}>
              <div className="text-xs text-slate-400 uppercase tracking-wider mb-2">Predykcja AI</div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <span className={`text-3xl font-bold ${
                    prediction === '1' ? 'text-blue-400' :
                    prediction === 'X' ? 'text-yellow-400' : 'text-purple-400'
                  }`}>
                    {prediction === '1' ? home_team : prediction === '2' ? away_team : 'Remis'}
                  </span>
                  <span className="text-2xl font-bold text-accent">{prediction}</span>
                </div>
                {confidence && (
                  <div className="text-right">
                    <div className={`text-3xl font-bold ${
                      confidence >= 80 ? 'text-green-400' :
                      confidence >= 65 ? 'text-yellow-400' : 'text-slate-400'
                    }`}>
                      {confidence}%
                    </div>
                    <div className="text-xs text-slate-400">pewność</div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Odds */}
          {odds.home && (
            <div>
              <div className="text-xs text-slate-400 uppercase tracking-wider mb-2">Kursy bukmacherskie</div>
              <div className="grid grid-cols-3 gap-2">
                <div className="p-3 rounded-lg text-center" style={{ background: 'var(--bg-secondary)' }}>
                  <div className="text-xs text-slate-400 mb-1">1 (gospodarze)</div>
                  <div className="text-xl font-bold text-white">{odds.home?.toFixed(2)}</div>
                </div>
                <div className="p-3 rounded-lg text-center" style={{ background: 'var(--bg-secondary)' }}>
                  <div className="text-xs text-slate-400 mb-1">X (remis)</div>
                  <div className="text-xl font-bold text-white">{odds.draw?.toFixed(2) || '-'}</div>
                </div>
                <div className="p-3 rounded-lg text-center" style={{ background: 'var(--bg-secondary)' }}>
                  <div className="text-xs text-slate-400 mb-1">2 (goście)</div>
                  <div className="text-xl font-bold text-white">{odds.away?.toFixed(2)}</div>
                </div>
              </div>
            </div>
          )}

          {/* Fan Vote */}
          {fan_vote && (
            <div>
              <div className="text-xs text-slate-400 uppercase tracking-wider mb-2">Głosowanie fanów</div>
              <div className="p-3 rounded-lg" style={{ background: 'var(--bg-secondary)' }}>
                <div className="flex h-3 rounded-full overflow-hidden bg-slate-700 mb-2">
                  <div className="bg-blue-500" style={{ width: `${fan_vote.home || 0}%` }} />
                  <div className="bg-yellow-500" style={{ width: `${fan_vote.draw || 0}%` }} />
                  <div className="bg-purple-500" style={{ width: `${fan_vote.away || 0}%` }} />
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-blue-400">{home_team}: {fan_vote.home}%</span>
                  <span className="text-yellow-400">Remis: {fan_vote.draw}%</span>
                  <span className="text-purple-400">{away_team}: {fan_vote.away}%</span>
                </div>
              </div>
            </div>
          )}

          {/* Form */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-xs text-slate-400 uppercase tracking-wider mb-2">Forma {home_team}</div>
              <div className="p-3 rounded-lg" style={{ background: 'var(--bg-secondary)' }}>
                {renderForm(form_home, home_team)}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-400 uppercase tracking-wider mb-2">Forma {away_team}</div>
              <div className="p-3 rounded-lg" style={{ background: 'var(--bg-secondary)' }}>
                {renderForm(form_away, away_team)}
              </div>
            </div>
          </div>

          {/* H2H */}
          {h2h && h2h.length > 0 && (
            <div>
              <div className="text-xs text-slate-400 uppercase tracking-wider mb-2">Bezpośrednie mecze (H2H)</div>
              <div className="space-y-1">
                {h2h.slice(0, 5).map((game, idx) => (
                  <div 
                    key={idx}
                    className="flex items-center justify-between p-2 rounded text-sm"
                    style={{ background: 'var(--bg-secondary)' }}
                  >
                    <span className="text-slate-400 text-xs">{game.date}</span>
                    <span className="text-white">{game.home} {game.score} {game.away}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
