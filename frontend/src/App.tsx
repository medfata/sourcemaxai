import { useCallback, useEffect, useState } from 'react'
import type { Session } from '@supabase/supabase-js'

import { api } from './api'
import { clearChannelProfilerState, setAccessToken } from './authState'
import AuthPage from './pages/AuthPage'
import LandingPage from './pages/LandingPage'
import StudioPage from './pages/StudioPage'
import WaitlistPage from './pages/WaitlistPage'
import { supabase } from './lib/supabase'

type AppRoute = '/' | '/waitlist' | '/login' | '/channels'

const PENDING_CHANNEL_URL_KEY = 'cp_pending_channel_url'

function normalizeRoute(pathname: string): AppRoute {
  if (pathname === '/waitlist') return '/waitlist'
  if (pathname === '/login') return '/login'
  if (pathname === '/channels') return '/channels'
  return '/'
}

function App() {
  const [authReady, setAuthReady] = useState(false)
  const [session, setSession] = useState<Session | null>(null)
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [route, setRoute] = useState<AppRoute>(() => normalizeRoute(window.location.pathname))
  const [channelInputUrl, setChannelInputUrl] = useState(() => sessionStorage.getItem(PENDING_CHANNEL_URL_KEY) ?? '')
  const [autoAnalyzeChannelInput, setAutoAnalyzeChannelInput] = useState(false)

  const navigate = useCallback((nextRoute: AppRoute, options?: { replace?: boolean }) => {
    const method = options?.replace ? 'replaceState' : 'pushState'
    if (window.location.pathname !== nextRoute) {
      window.history[method](null, '', nextRoute)
    }
    setRoute(nextRoute)
  }, [])

  const resetAppState = useCallback(() => {
    clearChannelProfilerState()
    setChannelInputUrl('')
    setAutoAnalyzeChannelInput(false)
  }, [])

  useEffect(() => {
    const normalized = normalizeRoute(window.location.pathname)
    if (normalized !== window.location.pathname) {
      window.history.replaceState(null, '', normalized)
    }

    const handlePopState = () => {
      setRoute(normalizeRoute(window.location.pathname))
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    if (!supabase) {
      setAuthReady(true)
      return
    }

    function applySession(nextSession: Session | null) {
      const nextUserId = nextSession?.user.id ?? null
      setAccessToken(nextSession?.access_token ?? null)
      if (nextUserId) {
        const previousUserId = localStorage.getItem('cp_auth_user_id')
        if (previousUserId !== nextUserId) {
          resetAppState()
        }
        localStorage.setItem('cp_auth_user_id', nextUserId)
      } else {
        resetAppState()
      }
      setSession(nextSession)
      setAuthReady(true)
    }

    let active = true
    supabase.auth.getSession().then(({ data }) => {
      if (active) applySession(data.session)
    })
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      applySession(nextSession)
    })

    return () => {
      active = false
      subscription.unsubscribe()
    }
  }, [resetAppState])

  useEffect(() => {
    api
      .health()
      .then((data) => setHealthy(data.ok === true))
      .catch(() => setHealthy(false))
  }, [])

  useEffect(() => {
    if (!authReady) return
    if (!session && route === '/channels') {
      navigate('/login', { replace: true })
    }
    if (session && route === '/login') {
      const pendingUrl = sessionStorage.getItem(PENDING_CHANNEL_URL_KEY)
      if (pendingUrl) {
        setChannelInputUrl(pendingUrl)
        setAutoAnalyzeChannelInput(true)
      }
      navigate('/channels', { replace: true })
    }
  }, [authReady, session, route, navigate])

  const handleLandingAnalyze = (url: string) => {
    sessionStorage.setItem(PENDING_CHANNEL_URL_KEY, url)
    setChannelInputUrl(url)
    setAutoAnalyzeChannelInput(true)
    navigate(session ? '/channels' : '/login')
  }

  const handleChannelInputConsumed = () => {
    sessionStorage.removeItem(PENDING_CHANNEL_URL_KEY)
    setChannelInputUrl('')
    setAutoAnalyzeChannelInput(false)
  }

  const handleSignOut = async () => {
    resetAppState()
    setAccessToken(null)
    setSession(null)
    await supabase?.auth.signOut()
    navigate('/login', { replace: true })
  }

  if (!authReady) {
    return (
      <div className="app-boot">
        <div className="app-boot-card">
          <span className="app-boot-mark">T</span>
          <span className="app-boot-spinner" aria-hidden />
          <span>Loading Trace</span>
        </div>
      </div>
    )
  }

  if (route === '/') {
    return (
      <LandingPage
        signedIn={Boolean(session)}
        onLogin={() => navigate('/login')}
        onOpenChannels={() => navigate(session ? '/channels' : '/login')}
        onAnalyze={handleLandingAnalyze}
        onJoinWaitlist={() => navigate('/waitlist')}
      />
    )
  }

  if (route === '/waitlist') {
    return (
      <WaitlistPage
        signedIn={Boolean(session)}
        onBackHome={() => navigate('/')}
        onLogin={() => navigate('/login')}
        onOpenChannels={() => navigate(session ? '/channels' : '/login')}
      />
    )
  }

  if (route === '/login' || !session) {
    return (
      <AuthPage
        onBackHome={() => navigate('/')}
        onJoinWaitlist={() => navigate('/waitlist')}
      />
    )
  }

  return (
    <StudioPage
      session={session}
      healthy={healthy}
      initialUrl={channelInputUrl}
      autoSubmitInitialUrl={autoAnalyzeChannelInput}
      onInitialUrlConsumed={handleChannelInputConsumed}
      onSignOut={handleSignOut}
    />
  )
}

export default App
