import React, { useState, useEffect } from 'react'
import MatchCard from './MatchCard'
import MatchDetail from './MatchDetail'

const sportIcons = {
  football: '⚽',
  basketball: '🏀',
  tennis: '🎾',
  hockey: '🏒',
  volleyball: '🏐',
  handball: '🤾'
}

// Demo data for testing
const demoMatches = {
  football: [
    {
      id: 1,
      league: 'Champions League',
      country: 'Europa',
      home_team: 'Real Madrid',
      away_team: 'Manchester City',
      time: '21:00',
      date: 'Dziś',
      prediction: '1',
      confidence: 72,
      odds: { home: 2.10, draw: 3.40, away: 3.20 },
      form_home: ['W', 'W', 'D', 'W', 'L'],
      form_away: ['W', 'L', 'W', 'W', 'D'],
      fan_vote: { home: 45, draw: 22, away: 33 }
    },
    {
      id: 2,
      league: 'Champions League',
      country: 'Europa',
      home_team: 'Bayern Munich',
      away_team: 'Paris Saint-Germain',
      time: '21:00',
      date: 'Dziś',
      prediction: '1',
      confidence: 68,
      odds: { home: 1.85, draw: 3.60, away: 4.00 },
      form_home: ['W', 'W', 'W', 'D', 'W'],
      form_away: ['W', 'L', 'W', 'L', 'W'],
      fan_vote: { home: 52, draw: 20, away: 28 }
    },
    {
      id: 3,
      league: 'Premier League',
      country: 'Anglia',
      home_team: 'Arsenal',
      away_team: 'Liverpool',
      time: '17:30',
      date: 'Jutro',
      prediction: 'X',
      confidence: 58,
      odds: { home: 2.30, draw: 3.30, away: 3.00 },
      form_home: ['W', 'D', 'W', 'W', 'W'],
      form_away: ['W', 'W', 'D', 'W', 'W'],
      fan_vote: { home: 38, draw: 28, away: 34 }
    },
    {
      id: 4,
      league: 'Premier League',
      country: 'Anglia',
      home_team: 'Chelsea',
      away_team: 'Manchester United',
      time: '15:00',
      date: 'Jutro',
      prediction: '1',
      confidence: 61,
      odds: { home: 2.00, draw: 3.50, away: 3.60 },
      form_home: ['D', 'W', 'L', 'W', 'D'],
      form_away: ['L', 'D', 'W', 'L', 'W'],
      fan_vote: { home: 44, draw: 25, away: 31 }
    },
    {
      id: 5,
      league: 'La Liga',
      country: 'Hiszpania',
      home_team: 'FC Barcelona',
      away_team: 'Atletico Madrid',
      time: '20:00',
      date: 'Dziś',
      prediction: '1',
      confidence: 75,
      odds: { home: 1.65, draw: 3.80, away: 5.00 },
      form_home: ['W', 'W', 'W', 'W', 'D'],
      form_away: ['D', 'W', 'D', 'L', 'W'],
      fan_vote: { home: 58, draw: 22, away: 20 }
    }
  ],
  basketball: [
    {
      id: 101,
      league: 'NBA',
      country: 'USA',
      home_team: 'Los Angeles Lakers',
      away_team: 'Boston Celtics',
      time: '02:30',
      date: 'Jutro',
      prediction: '2',
      confidence: 65,
      odds: { home: 2.20, away: 1.70 },
      form_home: ['W', 'L', 'W', 'L', 'W'],
      form_away: ['W', 'W', 'W', 'D', 'W'],
      fan_vote: { home: 42, draw: 0, away: 58 }
    },
    {
      id: 102,
      league: 'Euroleague',
      country: 'Europa',
      home_team: 'Real Madrid',
      away_team: 'FC Barcelona',
      time: '20:45',
      date: 'Dziś',
      prediction: '1',
      confidence: 71,
      odds: { home: 1.75, away: 2.10 },
      form_home: ['W', 'W', 'D', 'W', 'W'],
      form_away: ['W', 'L', 'W', 'W', 'L'],
      fan_vote: { home: 55, draw: 0, away: 45 }
    }
  ],
  tennis: [
    {
      id: 201,
      league: 'ATP Finals',
      country: 'Włochy',
      home_team: 'C. Alcaraz',
      away_team: 'J. Sinner',
      time: '14:00',
      date: 'Dziś',
      prediction: '1',
      confidence: 56,
      odds: { home: 1.90, away: 1.95 },
      form_home: ['W', 'W', 'L', 'W', 'W'],
      form_away: ['W', 'W', 'W', 'W', 'L']
    }
  ],
  hockey: [
    {
      id: 301,
      league: 'NHL',
      country: 'USA/Kanada',
      home_team: 'Toronto Maple Leafs',
      away_team: 'Montreal Canadiens',
      time: '01:00',
      date: 'Jutro',
      prediction: '1',
      confidence: 68,
      odds: { home: 1.60, draw: 4.20, away: 5.00 },
      form_home: ['W', 'W', 'W', 'L', 'W'],
      form_away: ['L', 'L', 'W', 'L', 'D']
    }
  ],
  volleyball: [
    {
      id: 401,
      league: 'PlusLiga',
      country: 'Polska',
      home_team: 'Jastrzębski Węgiel',
      away_team: 'ZAKSA Kędzierzyn',
      time: '17:30',
      date: 'Dziś',
      prediction: '1',
      confidence: 62,
      odds: { home: 1.55, away: 2.40 },
      form_home: ['W', 'W', 'W', 'D', 'W'],
      form_away: ['W', 'L', 'W', 'W', 'L']
    }
  ],
  handball: [
    {
      id: 501,
      league: 'Superliga',
      country: 'Polska',
      home_team: 'Łomża Vive Kielce',
      away_team: 'Orlen Wisła Płock',
      time: '18:00',
      date: 'Dziś',
      prediction: '1',
      confidence: 78,
      odds: { home: 1.35, draw: 6.00, away: 7.50 },
      form_home: ['W', 'W', 'W', 'W', 'W'],
      form_away: ['W', 'L', 'W', 'L', 'L']
    }
  ]
}

export default function MatchesView({ activeSport = 'football' }) {
  const [matches, setMatches] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedMatch, setSelectedMatch] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchMatches()
  }, [activeSport])

  const fetchMatches = async () => {
    setLoading(true)
    setError(null)
    
    try {
      const response = await fetch(`http://localhost:5000/api/matches?sport=${activeSport}`)
      
      if (response.ok) {
        const data = await response.json()
        if (data.matches && data.matches.length > 0) {
          setMatches(data.matches)
        } else {
          // Use demo data if no real data
          setMatches(demoMatches[activeSport] || [])
        }
      } else {
        // Use demo data on error
        setMatches(demoMatches[activeSport] || [])
      }
    } catch (err) {
      console.log('API not available, using demo data')
      setMatches(demoMatches[activeSport] || [])
    } finally {
      setLoading(false)
    }
  }

  // Group matches by league
  const groupedMatches = matches.reduce((acc, match) => {
    const key = `${match.country || 'Inne'} - ${match.league || 'Liga'}`
    if (!acc[key]) acc[key] = []
    acc[key].push(match)
    return acc
  }, {})

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 border-2 border-accent border-t-transparent rounded-full animate-spin"></div>
          <span className="text-slate-400 text-sm">Ładowanie meczów...</span>
        </div>
      </div>
    )
  }

  if (matches.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="text-4xl mb-3">{sportIcons[activeSport]}</div>
          <div className="text-slate-400">Brak meczów do wyświetlenia</div>
          <div className="text-slate-500 text-sm mt-1">Sprawdź później lub wybierz inną dyscyplinę</div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto">
      {/* Sport header */}
      <div className="sticky top-0 z-10 p-4" style={{ background: 'var(--bg-primary)' }}>
        <div className="flex items-center gap-3">
          <span className="text-2xl">{sportIcons[activeSport]}</span>
          <div>
            <h2 className="text-lg font-bold text-white capitalize">
              {activeSport === 'football' ? 'Piłka nożna' :
               activeSport === 'basketball' ? 'Koszykówka' :
               activeSport === 'tennis' ? 'Tenis' :
               activeSport === 'hockey' ? 'Hokej' :
               activeSport === 'volleyball' ? 'Siatkówka' :
               activeSport === 'handball' ? 'Piłka ręczna' : activeSport}
            </h2>
            <p className="text-xs text-slate-400">{matches.length} meczów z predykcjami</p>
          </div>
        </div>
      </div>

      {/* Matches grouped by league */}
      <div className="px-4 pb-4">
        {Object.entries(groupedMatches).map(([league, leagueMatches]) => (
          <div key={league} className="mb-4">
            <div className="league-header">
              <span>{league}</span>
              <span className="text-slate-500 text-xs font-normal ml-2">
                ({leagueMatches.length})
              </span>
            </div>
            <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-card)' }}>
              {leagueMatches.map((match, idx) => (
                <MatchCard 
                  key={match.id || idx} 
                  match={match} 
                  onClick={setSelectedMatch}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Match Detail Modal */}
      {selectedMatch && (
        <MatchDetail 
          match={selectedMatch} 
          onClose={() => setSelectedMatch(null)} 
        />
      )}
    </div>
  )
}
