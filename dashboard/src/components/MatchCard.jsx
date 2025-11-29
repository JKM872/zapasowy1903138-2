import React, { useState } from 'react'

export default function MatchCard({ match, onClick }) {
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
    is_live = false,
    score_home = null,
    score_away = null,
    fan_vote = null
  } = match

  const renderForm = (form) => {
    if (!form || form.length === 0) return null
    return (
      <div className="flex gap-0.5">
        {form.slice(-5).map((result, idx) => (
          <span 
            key={idx} 
            className={`form-dot ${
              result === 'W' ? 'form-w' : 
              result === 'D' ? 'form-d' : 'form-l'
            }`}
            title={result === 'W' ? 'Wygrana' : result === 'D' ? 'Remis' : 'Przegrana'}
          />
        ))}
      </div>
    )
  }

  const getConfidenceColor = (conf) => {
    if (!conf) return 'text-slate-400'
    if (conf >= 80) return 'text-green-400'
    if (conf >= 65) return 'text-yellow-400'
    return 'text-slate-400'
  }

  const getPredictionBadge = () => {
    if (!prediction) return null
    const colors = {
      '1': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
      'X': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
      '2': 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    }
    return (
      <span className={`px-2 py-0.5 rounded text-xs font-bold border ${colors[prediction] || 'bg-slate-500/20 text-slate-400 border-slate-500/30'}`}>
        {prediction}
      </span>
    )
  }

  return (
    <div 
      className="match-row group cursor-pointer"
      onClick={() => onClick?.(match)}
    >
      {/* Time / Live indicator */}
      <div className="w-16 text-center shrink-0">
        {is_live ? (
          <div className="flex flex-col items-center">
            <span className="px-2 py-0.5 bg-red-500 text-white text-[10px] font-bold rounded animate-pulse">
              LIVE
            </span>
            <span className="text-xs text-slate-400 mt-0.5">{time}'</span>
          </div>
        ) : (
          <div className="flex flex-col items-center">
            <span className="text-sm font-medium text-white">{time}</span>
            {date && <span className="text-[10px] text-slate-500">{date}</span>}
          </div>
        )}
      </div>

      {/* Teams */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm text-white truncate flex-1">{home_team}</span>
          {renderForm(form_home)}
          {is_live && score_home !== null && (
            <span className="text-sm font-bold text-white w-5 text-center">{score_home}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-white truncate flex-1">{away_team}</span>
          {renderForm(form_away)}
          {is_live && score_away !== null && (
            <span className="text-sm font-bold text-white w-5 text-center">{score_away}</span>
          )}
        </div>
      </div>

      {/* Prediction */}
      <div className="w-20 flex flex-col items-center shrink-0">
        {getPredictionBadge()}
        {confidence && (
          <span className={`text-xs mt-0.5 ${getConfidenceColor(confidence)}`}>
            {confidence}%
          </span>
        )}
      </div>

      {/* Fan Vote */}
      {fan_vote && (
        <div className="w-24 hidden sm:flex flex-col gap-0.5 shrink-0">
          <div className="flex h-1.5 rounded-full overflow-hidden bg-slate-700">
            <div 
              className="bg-blue-500" 
              style={{ width: `${fan_vote.home || 0}%` }}
            />
            <div 
              className="bg-yellow-500" 
              style={{ width: `${fan_vote.draw || 0}%` }}
            />
            <div 
              className="bg-purple-500" 
              style={{ width: `${fan_vote.away || 0}%` }}
            />
          </div>
          <div className="flex justify-between text-[9px] text-slate-500">
            <span>{fan_vote.home}%</span>
            <span>{fan_vote.draw}%</span>
            <span>{fan_vote.away}%</span>
          </div>
        </div>
      )}

      {/* Odds */}
      <div className="flex gap-1 shrink-0">
        {odds.home ? (
          <>
            <button className="odds-btn" title="Wygrana gospodarzy">
              <span className="text-[9px] text-slate-500">1</span>
              <span className="font-semibold">{odds.home?.toFixed(2)}</span>
            </button>
            <button className="odds-btn" title="Remis">
              <span className="text-[9px] text-slate-500">X</span>
              <span className="font-semibold">{odds.draw?.toFixed(2) || '-'}</span>
            </button>
            <button className="odds-btn" title="Wygrana gości">
              <span className="text-[9px] text-slate-500">2</span>
              <span className="font-semibold">{odds.away?.toFixed(2)}</span>
            </button>
          </>
        ) : (
          <span className="text-xs text-slate-500 px-2">Brak kursów</span>
        )}
      </div>

      {/* Arrow */}
      <div className="w-6 flex items-center justify-center text-slate-500 group-hover:text-accent transition-colors shrink-0">
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </div>
    </div>
  )
}
