import { useState, type FormEvent } from 'react'

import { supabase, supabaseConfigError } from '../lib/supabase'
import './AuthPage.css'

type AuthMode = 'login' | 'signup'

interface AuthPageProps {
  onBackHome: () => void
  onJoinWaitlist: () => void
}

function MailIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </svg>
  )
}

function LockIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="4" y="11" width="16" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  )
}

function ArrowIcon() {
  return (
    <svg className="auth-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12h14" />
      <path d="m13 6 6 6-6 6" />
    </svg>
  )
}

function AlertIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 8v4" />
      <path d="M12 16h.01" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M20 6 9 17l-5-5" />
    </svg>
  )
}

function TraceMark({ onBackHome }: { onBackHome: () => void }) {
  return (
    <button type="button" className="auth-brand" onClick={onBackHome} aria-label="Trace home">
      <span className="auth-brand-mark" aria-hidden>T</span>
      <span>Trace</span>
    </button>
  )
}

export default function AuthPage({ onBackHome, onJoinWaitlist }: AuthPageProps) {
  const [mode, setMode] = useState<AuthMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const isSignup = mode === 'signup'

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')
    setNotice('')
    if (!supabase) {
      setError(supabaseConfigError ?? 'Supabase is not configured.')
      return
    }
    if (!email.trim() || !password || (isSignup && !confirmPassword)) {
      setError(isSignup ? 'Email, password, and confirmation are required.' : 'Email and password are required.')
      return
    }
    if (isSignup && password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setLoading(true)
    const result = isSignup
      ? await supabase.auth.signUp({ email: email.trim(), password })
      : await supabase.auth.signInWithPassword({ email: email.trim(), password })
    setLoading(false)

    if (result.error) {
      setError(result.error.message)
      return
    }
    if (isSignup && !result.data.session) {
      setNotice('Check your email to confirm your account, then sign in.')
    }
  }

  return (
    <div className="auth-page">
      <nav className="auth-nav">
        <TraceMark onBackHome={onBackHome} />
        <div className="auth-nav-actions">
          <button type="button" className="auth-nav-link" onClick={onBackHome}>
            Back to Trace
          </button>
          <button type="button" className="auth-nav-link auth-nav-waitlist" onClick={onJoinWaitlist}>
            <span className="auth-nav-dot" aria-hidden />
            <span>Join waitlist</span>
          </button>
        </div>
      </nav>

      <main className="auth-shell">
        <section className="auth-hero">
          <div className="auth-badge auth-fade-up d1">
            <span className="auth-badge-dot" aria-hidden />
            <span>Secure Trace workspace</span>
          </div>

          <h1 className="auth-headline auth-fade-up d2">
            {isSignup ? 'Create your creator research workspace.' : 'Return to your creator maps.'}
          </h1>

          <p className="auth-sub auth-fade-up d3">
            {isSignup
              ? 'Save channels, citations, and chat history under one Trace account.'
              : 'Open your saved YouTube channel profiles, cited answers, and pipeline history.'}
          </p>

          <div className="auth-mini-stats auth-fade-up d4" aria-label="Workspace capabilities">
            <span><b>Channels</b> saved</span>
            <span><b>Claims</b> cited</span>
            <span><b>Chats</b> synced</span>
          </div>
        </section>

        <section className="auth-panel auth-fade-up d4" aria-label={isSignup ? 'Create account form' : 'Sign in form'}>
          <div className="auth-panel-head">
            <span className="auth-kicker">{isSignup ? 'Create workspace' : 'Secure access'}</span>
            <h2>{isSignup ? 'Create account' : 'Sign in'}</h2>
            <p>{isSignup ? 'Use email and password to start a private Trace workspace.' : 'Use email and password to continue where you left off.'}</p>
          </div>

          <div className="auth-mode" role="tablist" aria-label="Authentication mode">
            <button
              type="button"
              role="tab"
              aria-selected={!isSignup}
              className={!isSignup ? 'active' : ''}
              onClick={() => {
                setMode('login')
                setConfirmPassword('')
                setError('')
                setNotice('')
              }}
            >
              Sign in
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={isSignup}
              className={isSignup ? 'active' : ''}
              onClick={() => {
                setMode('signup')
                setError('')
                setNotice('')
              }}
            >
              Sign up
            </button>
          </div>

          {supabaseConfigError && (
            <div className="auth-alert auth-alert-error" role="alert">
              <AlertIcon />
              <span>{supabaseConfigError}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="auth-form" noValidate>
            <label className="auth-field">
              <span className="auth-label">Email</span>
              <div className="auth-input-wrap">
                <span className="auth-input-icon">
                  <MailIcon />
                </span>
                <input
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value)
                    setError('')
                    setNotice('')
                  }}
                  placeholder="you@studio.dev"
                  className={error ? 'auth-input is-error' : 'auth-input'}
                  disabled={loading}
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? 'auth-error' : undefined}
                />
              </div>
            </label>

            <label className="auth-field">
              <span className="auth-label">Password</span>
              <div className="auth-input-wrap">
                <span className="auth-input-icon">
                  <LockIcon />
                </span>
                <input
                  type="password"
                  autoComplete={isSignup ? 'new-password' : 'current-password'}
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value)
                    setError('')
                    setNotice('')
                  }}
                  placeholder="password"
                  className={error ? 'auth-input is-error' : 'auth-input'}
                  disabled={loading}
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? 'auth-error' : undefined}
                />
              </div>
            </label>

            {isSignup && (
              <label className="auth-field">
                <span className="auth-label">Confirm password</span>
                <div className="auth-input-wrap">
                  <span className="auth-input-icon">
                    <LockIcon />
                  </span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(e) => {
                      setConfirmPassword(e.target.value)
                      setError('')
                      setNotice('')
                    }}
                    placeholder="repeat password"
                    className={error ? 'auth-input is-error' : 'auth-input'}
                    disabled={loading}
                    aria-invalid={Boolean(error)}
                    aria-describedby={error ? 'auth-error' : undefined}
                  />
                </div>
              </label>
            )}

            {error && (
              <div id="auth-error" className="auth-alert auth-alert-error" role="alert">
                <AlertIcon />
                <span>{error}</span>
              </div>
            )}

            {notice && (
              <div className="auth-alert auth-alert-success" role="status" aria-live="polite">
                <CheckIcon />
                <span>{notice}</span>
              </div>
            )}

            <button type="submit" disabled={loading || Boolean(supabaseConfigError)} className="auth-button">
              {loading ? (
                <>
                  <span className="auth-spinner" aria-hidden />
                  <span>{isSignup ? 'Creating...' : 'Signing in...'}</span>
                </>
              ) : (
                <>
                  <span>{isSignup ? 'Create account' : 'Sign in'}</span>
                  <ArrowIcon />
                </>
              )}
            </button>
          </form>

          <div className="auth-switch">
            <span>{isSignup ? 'Already have an account?' : 'Need an account?'}</span>
            <button
              type="button"
              onClick={() => {
                setMode(isSignup ? 'login' : 'signup')
                if (isSignup) setConfirmPassword('')
                setError('')
                setNotice('')
              }}
            >
              {isSignup ? 'Sign in' : 'Sign up'}
            </button>
          </div>
        </section>
      </main>
    </div>
  )
}
