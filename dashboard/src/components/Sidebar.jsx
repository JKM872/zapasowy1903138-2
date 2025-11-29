import React from 'react'

const sports = [
  { id: 'football', name: 'Piłka nożna', icon: '⚽', count: 0 },
  { id: 'basketball', name: 'Koszykówka', icon: '🏀', count: 0 },
  { id: 'tennis', name: 'Tenis', icon: '🎾', count: 0 },
  { id: 'hockey', name: 'Hokej', icon: '🏒', count: 0 },
  { id: 'volleyball', name: 'Siatkówka', icon: '🏐', count: 0 },
  { id: 'handball', name: 'Piłka ręczna', icon: '🤾', count: 0 }
]

const favorites = [
  { name: 'Champions League', icon: '🏆' },
  { name: 'Premier League', icon: '🏴󠁧󠁢󠁥󠁮󠁧󠁿' },
  { name: 'La Liga', icon: '🇪🇸' },
  { name: 'Serie A', icon: '🇮🇹' },
  { name: 'Bundesliga', icon: '🇩🇪' },
]

export default function Sidebar({ activeSport, onSportChange, matchCounts = {} }) {
  // Update counts from props
  const sportsWithCounts = sports.map(sport => ({
    ...sport,
    count: matchCounts[sport.id] || 0
  }))

  return (
    <aside 
      className="w-56 shrink-0 hidden lg:block overflow-y-auto"
      style={{ 
        background: 'var(--bg-secondary)', 
        borderRight: '1px solid var(--border)',
        height: 'calc(100vh - 56px)'
      }}
    >
      {/* Sports */}
      <div className="p-3">
        <h3 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
          Dyscypliny sportowe
        </h3>
        <div className="space-y-0.5">
          {sportsWithCounts.map(sport => (
            <button
              key={sport.id}
              onClick={() => onSportChange(sport.id)}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded text-sm transition-colors ${
                activeSport === sport.id 
                  ? 'bg-accent/20 text-accent' 
                  : 'text-slate-300 hover:bg-white/5'
              }`}
            >
              <span className="text-lg">{sport.icon}</span>
              <span className="flex-1 text-left">{sport.name}</span>
              {sport.count > 0 && (
                <span className={`text-xs px-1.5 py-0.5 rounded ${
                  activeSport === sport.id 
                    ? 'bg-accent/30 text-accent' 
                    : 'bg-white/10 text-slate-400'
                }`}>
                  {sport.count}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Separator */}
      <div className="h-px mx-3 my-2" style={{ background: 'var(--border)' }}></div>

      {/* Favorites */}
      <div className="p-3">
        <h3 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
          Ulubione ligi
        </h3>
        <div className="space-y-0.5">
          {favorites.map((league, idx) => (
            <button
              key={idx}
              className="w-full flex items-center gap-3 px-3 py-2 rounded text-sm text-slate-400 hover:bg-white/5 transition-colors"
            >
              <span>{league.icon}</span>
              <span className="flex-1 text-left text-xs">{league.name}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Separator */}
      <div className="h-px mx-3 my-2" style={{ background: 'var(--border)' }}></div>

      {/* Filters */}
      <div className="p-3">
        <h3 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
          Filtry
        </h3>
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer hover:text-slate-300">
            <input type="checkbox" className="rounded border-slate-600 bg-transparent text-accent focus:ring-accent" />
            <span>Tylko dzisiaj</span>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer hover:text-slate-300">
            <input type="checkbox" className="rounded border-slate-600 bg-transparent text-accent focus:ring-accent" />
            <span>Wysoka pewność (&gt;75%)</span>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer hover:text-slate-300">
            <input type="checkbox" className="rounded border-slate-600 bg-transparent text-accent focus:ring-accent" />
            <span>Value bets</span>
          </label>
        </div>
      </div>

      {/* Legend */}
      <div className="p-3 mt-auto">
        <h3 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
          Legenda formy
        </h3>
        <div className="flex items-center gap-3 text-xs">
          <div className="flex items-center gap-1">
            <span className="form-dot form-w"></span>
            <span className="text-slate-400">Wygrana</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="form-dot form-d"></span>
            <span className="text-slate-400">Remis</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="form-dot form-l"></span>
            <span className="text-slate-400">Przegrana</span>
          </div>
        </div>
      </div>
    </aside>
  )
}
