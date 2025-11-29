import React, { Fragment } from 'react'
import { Dialog, Transition } from '@headlessui/react'
import { XMarkIcon, TrophyIcon, ChartBarIcon, BanknotesIcon } from '@heroicons/react/24/outline'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

export default function MatchDetailModal({ isOpen, closeModal, match }) {
  if (!match) return null

  const getFormColor = (result) => {
    if (result === 'W') return '#22c55e' // green-500
    if (result === 'D') return '#eab308' // yellow-500
    if (result === 'L') return '#ef4444' // red-500
    return '#94a3b8' // slate-400
  }

  const formatForm = (form) => {
    if (!form || !Array.isArray(form)) return []
    return form.map((result, idx) => ({
      name: `M${idx + 1}`,
      result,
      value: result === 'W' ? 3 : result === 'D' ? 1 : 0,
      color: getFormColor(result)
    }))
  }

  const homeForm = formatForm(match.home_form_overall)
  const awayForm = formatForm(match.away_form_overall)

  return (
    <Transition appear show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={closeModal}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-300"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-200"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-black/75" />
        </Transition.Child>

        <div className="fixed inset-0 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center p-4 text-center">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-300"
              enterFrom="opacity-0 scale-95"
              enterTo="opacity-100 scale-100"
              leave="ease-in duration-200"
              leaveFrom="opacity-100 scale-100"
              leaveTo="opacity-0 scale-95"
            >
              <Dialog.Panel className="w-full max-w-4xl transform overflow-hidden rounded-2xl bg-slate-800 p-6 text-left align-middle shadow-xl transition-all border border-slate-700">
                
                {/* Header */}
                <div className="flex justify-between items-start mb-6">
                  <div className="flex-1">
                    <div className="text-sm text-slate-400 mb-1">{match.match_time} • {match.match_date}</div>
                    <Dialog.Title as="h3" className="text-2xl font-bold text-white flex items-center gap-3">
                      <span>{match.home_team}</span>
                      <span className="text-slate-500 text-lg">vs</span>
                      <span>{match.away_team}</span>
                    </Dialog.Title>
                    <div className="mt-2 flex gap-2">
                      {match.qualifies && (
                        <span className="badge badge-success">Qualified</span>
                      )}
                      {match.form_advantage && (
                        <span className="badge badge-high">Form Advantage</span>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={closeModal}
                    className="text-slate-400 hover:text-white transition-colors"
                  >
                    <XMarkIcon className="h-6 w-6" />
                  </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  
                  {/* Left Column: Stats & Form */}
                  <div className="space-y-6">
                    
                    {/* H2H Summary */}
                    <div className="bg-slate-700/50 rounded-xl p-4">
                      <h4 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
                        <TrophyIcon className="h-5 w-5 text-yellow-500" />
                        H2H History
                      </h4>
                      <div className="flex justify-between items-center mb-4">
                        <div className="text-center">
                          <div className="text-3xl font-bold text-white">{match.home_wins}</div>
                          <div className="text-xs text-slate-400">Home Wins</div>
                        </div>
                        <div className="text-center px-4">
                          <div className="text-sm text-slate-400">out of</div>
                          <div className="text-xl font-bold text-white">{match.h2h_count}</div>
                          <div className="text-xs text-slate-400">Matches</div>
                        </div>
                        <div className="text-center">
                          <div className="text-3xl font-bold text-slate-400">
                            {match.h2h_count - match.home_wins}
                          </div>
                          <div className="text-xs text-slate-400">Other</div>
                        </div>
                      </div>
                      
                      {/* H2H List */}
                      <div className="space-y-2 max-h-40 overflow-y-auto pr-2 custom-scrollbar">
                        {match.h2h_details && match.h2h_details.map((h2h, idx) => (
                          <div key={idx} className="text-sm bg-slate-800 p-2 rounded flex justify-between items-center">
                            <span className="text-slate-400">{h2h.date}</span>
                            <span className="font-medium text-white">{h2h.score}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Form Charts */}
                    <div className="bg-slate-700/50 rounded-xl p-4">
                      <h4 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
                        <ChartBarIcon className="h-5 w-5 text-blue-500" />
                        Recent Form
                      </h4>
                      
                      <div className="mb-4">
                        <div className="text-sm text-slate-300 mb-1">{match.home_team}</div>
                        <div className="h-24 w-full">
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={homeForm}>
                              <Bar dataKey="value">
                                {homeForm.map((entry, index) => (
                                  <Cell key={`cell-${index}`} fill={entry.color} />
                                ))}
                              </Bar>
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      </div>

                      <div>
                        <div className="text-sm text-slate-300 mb-1">{match.away_team}</div>
                        <div className="h-24 w-full">
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={awayForm}>
                              <Bar dataKey="value">
                                {awayForm.map((entry, index) => (
                                  <Cell key={`cell-${index}`} fill={entry.color} />
                                ))}
                              </Bar>
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    </div>

                  </div>

                  {/* Right Column: Odds & AI */}
                  <div className="space-y-6">
                    
                    {/* Odds */}
                    <div className="bg-slate-700/50 rounded-xl p-4">
                      <h4 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
                        <BanknotesIcon className="h-5 w-5 text-green-500" />
                        Betting Odds
                      </h4>
                      <div className="grid grid-cols-3 gap-2">
                        <div className={`p-3 rounded-lg text-center ${match.home_odds < match.away_odds ? 'bg-green-500/20 border border-green-500/50' : 'bg-slate-800'}`}>
                          <div className="text-xs text-slate-400 mb-1">1 (Home)</div>
                          <div className="text-xl font-bold text-white">{match.home_odds?.toFixed(2) || '-'}</div>
                        </div>
                        <div className="p-3 rounded-lg text-center bg-slate-800">
                          <div className="text-xs text-slate-400 mb-1">X (Draw)</div>
                          <div className="text-xl font-bold text-white">-</div>
                        </div>
                        <div className={`p-3 rounded-lg text-center ${match.away_odds < match.home_odds ? 'bg-green-500/20 border border-green-500/50' : 'bg-slate-800'}`}>
                          <div className="text-xs text-slate-400 mb-1">2 (Away)</div>
                          <div className="text-xl font-bold text-white">{match.away_odds?.toFixed(2) || '-'}</div>
                        </div>
                      </div>
                    </div>

                    {/* AI Analysis */}
                    <div className="bg-slate-700/50 rounded-xl p-4 h-full">
                      <h4 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
                        ✨ Gemini AI Analysis
                      </h4>
                      {match.gemini_recommendation ? (
                        <div className="space-y-4">
                          <div className="flex items-center justify-between">
                            <span className="text-slate-300">Recommendation:</span>
                            <span className={`badge ${
                              match.gemini_recommendation === 'HIGH' ? 'badge-high' : 
                              match.gemini_recommendation === 'MEDIUM' ? 'badge-medium' : 'badge-low'
                            }`}>
                              {match.gemini_recommendation}
                            </span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-slate-300">Confidence:</span>
                            <span className="font-bold text-white">{match.gemini_confidence}%</span>
                          </div>
                          <div className="bg-slate-800 p-3 rounded-lg text-sm text-slate-300 leading-relaxed">
                            {match.gemini_reasoning}
                          </div>
                        </div>
                      ) : (
                        <div className="text-center py-8 text-slate-500">
                          No AI analysis available for this match.
                        </div>
                      )}
                    </div>

                  </div>
                </div>

              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition>
  )
}
