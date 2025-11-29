import React, { useState, useEffect } from 'react'

export default function Header() {
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  return (
    <header className="sticky top-0 z-50" style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border)' }}>
      <div className="max-w-7xl mx-auto px-4">
        <div className="flex items-center justify-between h-14">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="text-2xl">🏆</div>
            <div>
              <h1 className="text-lg font-bold text-white leading-tight">BetAnalyzer</h1>
              <p className="text-[10px] text-slate-400 -mt-0.5">AI Sports Predictions</p>
            </div>
          </div>

          {/* Stats Quick View */}
          <div className="hidden md:flex items-center gap-6">
            <div className="text-center">
              <div className="text-lg font-bold text-green-400">73%</div>
              <div className="text-[10px] text-slate-400">Win Rate</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-white">1,247</div>
              <div className="text-[10px] text-slate-400">Predictions</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-yellow-400">+18.5%</div>
              <div className="text-[10px] text-slate-400">ROI</div>
            </div>
          </div>

          {/* Time */}
          <div className="text-right">
            <div className="text-sm font-medium text-white">
              {time.toLocaleDateString('pl-PL', { weekday: 'short', day: 'numeric', month: 'short' })}
            </div>
            <div className="text-xs text-slate-400">
              {time.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' })}
            </div>
          </div>
        </div>
      </div>
    </header>
  )
}
