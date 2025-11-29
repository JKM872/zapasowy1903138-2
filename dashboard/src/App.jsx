import React, { useState, useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import MatchesView from './components/MatchesView'
import Header from './components/Header'
import Sidebar from './components/Sidebar'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30000,
    },
  },
})

function AppContent() {
  const [activeSport, setActiveSport] = useState('football')
  const [matchCounts, setMatchCounts] = useState({})

  useEffect(() => {
    // Fetch match counts for sidebar
    const fetchCounts = async () => {
      try {
        const response = await fetch('http://localhost:5000/api/stats')
        if (response.ok) {
          const data = await response.json()
          setMatchCounts(data.sports || {})
        }
      } catch (err) {
        // Demo counts
        setMatchCounts({
          football: 5,
          basketball: 2,
          tennis: 1,
          hockey: 1,
          volleyball: 1,
          handball: 1
        })
      }
    }
    fetchCounts()
  }, [])

  return (
    <div className="min-h-screen flex flex-col" style={{ background: 'var(--bg-primary)' }}>
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar 
          activeSport={activeSport} 
          onSportChange={setActiveSport}
          matchCounts={matchCounts}
        />
        <main className="flex-1 overflow-hidden">
          <MatchesView activeSport={activeSport} />
        </main>
      </div>
    </div>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  )
}

export default App
