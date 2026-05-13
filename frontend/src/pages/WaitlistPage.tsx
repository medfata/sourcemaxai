import type { FormEvent } from 'react'
import { useRef, useState } from 'react'

import { api } from '../api'
import './WaitlistPage.css'

interface WaitlistPageProps {
  signedIn: boolean
  onBackHome: () => void
  onLogin: () => void
  onOpenChannels: () => void
}

type SubmitState = 'idle' | 'loading' | 'success' | 'error'

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const THEMES = [
  { name: 'Federal Reserve policy', pct: 34, color: '#E5322B' },
  { name: 'Treasury yields & duration', pct: 22, color: '#2A2A2E' },
  { name: 'Consumer credit cycle', pct: 17, color: '#6B5B95' },
  { name: 'Commodities & inflation', pct: 14, color: '#88B04B' },
  { name: 'Equity rotation', pct: 9, color: '#C7522A' },
]

function MailIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M20 6 9 17l-5-5" />
    </svg>
  )
}

function ArrowIcon() {
  return (
    <svg className="wl-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12h14" />
      <path d="m13 6 6 6-6 6" />
    </svg>
  )
}

function AlertIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 8v4" />
      <path d="M12 16h.01" />
    </svg>
  )
}

function SearchIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  )
}

function TraceMark({ onBackHome }: { onBackHome: () => void }) {
  return (
    <button type="button" className="wl-brand" onClick={onBackHome} aria-label="Trace home">
      <span className="wl-brand-mark" aria-hidden>T</span>
      <span>Trace</span>
    </button>
  )
}

function Nav({ signedIn, onBackHome, onLogin, onOpenChannels }: WaitlistPageProps) {
  return (
    <nav className="wl-nav">
      <TraceMark onBackHome={onBackHome} />
      <div className="wl-nav-actions">
        <button type="button" className="wl-nav-link" onClick={onBackHome}>
          Back to Trace
        </button>
        <button type="button" className="wl-nav-link wl-nav-link-strong" onClick={signedIn ? onOpenChannels : onLogin}>
          {signedIn ? 'Open app' : 'Sign in'}
        </button>
      </div>
    </nav>
  )
}

function SearchCard() {
  return (
    <div className="wl-card wl-search-card wl-layer wl-layer-search">
      <SearchIcon />
      <div className="wl-query">where does she stand on rate cuts<span className="wl-cursor" /></div>
      <span className="wl-kbd">K</span>
    </div>
  )
}

function ProfileCard() {
  return (
    <div className="wl-card wl-layer wl-layer-profile">
      <div className="wl-card-head">
        <div className="wl-card-title">
          <span className="wl-kicker">Channel profile</span>
        </div>
        <span className="wl-tag">
          <span className="wl-dot-green" />
          Indexed
        </span>
      </div>
      <div className="wl-profile">
        <div className="wl-profile-avatar">LR</div>
        <div className="wl-profile-body">
          <div className="wl-profile-name">
            Lyn Robinson Macro
            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
              <path d="M12 2 9.5 6 5 7l3.5 3.5L8 15l4-2 4 2-.5-4.5L19 7l-4.5-1z" />
            </svg>
          </div>
          <div className="wl-profile-handle">@lynmacro - 412K subs</div>
          <div className="wl-profile-stats">
            <span><b>238</b> videos</span>
            <span><b>1,847</b> claims</span>
            <span><b>14</b> themes</span>
          </div>
        </div>
      </div>
    </div>
  )
}

function ThemesCard() {
  return (
    <div className="wl-card wl-layer wl-layer-themes">
      <div className="wl-card-head">
        <div className="wl-card-title">
          <span className="wl-card-dot" />
          <span className="wl-kicker">Recurring themes - last 90d</span>
        </div>
        <div className="wl-card-actions">
          <span />
          <span />
        </div>
      </div>
      <div className="wl-themes">
        {THEMES.map((theme) => (
          <div className="wl-theme" key={theme.name}>
            <div className="wl-theme-label">
              <span className="wl-theme-dot" style={{ background: theme.color }} />
              <span className="wl-theme-name">{theme.name}</span>
            </div>
            <div className="wl-theme-meta">
              <span className="wl-theme-bar">
                <span style={{ width: `${(theme.pct / 34) * 100}%`, background: theme.color }} />
              </span>
              <span className="wl-theme-pct">{theme.pct}%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ClaimCard() {
  return (
    <div className="wl-card wl-layer wl-layer-claim">
      <div className="wl-card-head">
        <div className="wl-card-title">
          <span className="wl-kicker">Claim - extracted</span>
        </div>
        <span className="wl-tag">
          <span className="wl-dot-red" />
          Cited 3x
        </span>
      </div>
      <div className="wl-claim">
        <div className="wl-claim-quote">
          The Fed will cut <span>at least two times before September</span>, even if core inflation prints above 3.
        </div>
        <div className="wl-claim-meta">
          <span className="wl-tag wl-tag-confidence">
            <span className="wl-dot-green" />
            High confidence
          </span>
          <span className="wl-tag">topic - Fed policy</span>
          <span className="wl-tag">stance - directional</span>
        </div>
      </div>
    </div>
  )
}

function Thumb() {
  return (
    <div className="wl-thumb">
      <div className="wl-thumb-image" />
      <svg className="wl-thumb-play" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
        <path d="M8 5v14l11-7z" />
      </svg>
      <span className="wl-thumb-time">12:43</span>
    </div>
  )
}

function EvidenceCard() {
  return (
    <div className="wl-card wl-layer wl-layer-evidence">
      <div className="wl-card-head">
        <div className="wl-card-title">
          <span className="wl-kicker">Evidence - jump to source</span>
        </div>
      </div>
      <div className="wl-evidence">
        <Thumb />
        <div className="wl-evidence-body">
          <div className="wl-evidence-title">Why I am still long duration - March macro update</div>
          <div className="wl-evidence-meta">
            <span>12:43</span>
            <span>-</span>
            <span>transcript line 184</span>
          </div>
        </div>
      </div>
    </div>
  )
}

function ProductPreview() {
  return (
    <aside className="wl-preview fade-up d6" aria-label="Product preview">
      <SearchCard />
      <ProfileCard />
      <ThemesCard />
      <ClaimCard />
      <EvidenceCard />
    </aside>
  )
}

export default function WaitlistPage(props: WaitlistPageProps) {
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState<SubmitState>('idle')
  const [message, setMessage] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const isLoading = status === 'loading'
  const isSuccess = status === 'success'

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (isLoading || isSuccess) return

    const nextEmail = email.trim().toLowerCase()
    if (!EMAIL_RE.test(nextEmail)) {
      setStatus('error')
      setMessage("That email doesn't look right. Try again.")
      inputRef.current?.focus()
      return
    }

    setStatus('loading')
    setMessage('')

    try {
      const result = await api.waitlistJoin(nextEmail)
      if (!result.ok) {
        setStatus('error')
        setMessage(result.error || 'Could not join waitlist. Please try again.')
        return
      }

      setEmail(nextEmail)
      setStatus('success')
      setMessage("You're on the list. Your 1,000 minutes will be ready at launch.")
    } catch {
      setStatus('error')
      setMessage('Could not reach Trace. Please try again.')
    }
  }

  return (
    <div className="waitlist-page">
      <Nav {...props} />

      <main className="wl-page">
        <section className="wl-hero">
          <div className="wl-badge fade-up d1">
            <span className="wl-badge-dot" aria-hidden />
            <span>1,000 free transcript minutes</span>
          </div>

          <h1 className="wl-headline fade-up d2">Join the Trace waitlist.</h1>

          <p className="wl-sub fade-up d3">Get 1,000 free transcript minutes when we launch.</p>

          <p className="wl-supporting fade-up d3">
            Profile YouTube creators with cited themes, claims, tone, and recurring ideas, built from the original videos.
          </p>

          <div className="fade-up d4">
            {isSuccess ? (
              <div className="wl-success" role="status" aria-live="polite">
                <div className="wl-success-check">
                  <CheckIcon />
                </div>
                <div className="wl-success-body">
                  <div className="wl-success-title">You&apos;re on the list.</div>
                  <div className="wl-success-text">
                    Your 1,000 minutes will be ready at launch. We&apos;ll email <b>{email || 'you'}</b> the day access opens.
                  </div>
                  <span className="wl-success-tag">
                    <MailIcon size={11} />
                    confirmation ready
                  </span>
                </div>
              </div>
            ) : (
              <>
                <form className="wl-form" onSubmit={handleSubmit} noValidate>
                  <div className="wl-input-wrap">
                    <span className="wl-input-icon">
                      <MailIcon />
                    </span>
                    <input
                      ref={inputRef}
                      className={`wl-input${status === 'error' ? ' is-error' : ''}`}
                      type="email"
                      inputMode="email"
                      autoComplete="email"
                      placeholder="you@studio.dev"
                      value={email}
                      onChange={(event) => {
                        setEmail(event.target.value)
                        if (status === 'error') {
                          setStatus('idle')
                          setMessage('')
                        }
                      }}
                      disabled={isLoading}
                      aria-invalid={status === 'error'}
                      aria-describedby={status === 'error' ? 'waitlist-error' : undefined}
                    />
                  </div>
                  <button className="wl-button" type="submit" disabled={isLoading}>
                    {isLoading ? (
                      <>
                        <span className="wl-spinner" aria-hidden />
                        <span>Joining...</span>
                      </>
                    ) : (
                      <>
                        <span>Join waitlist</span>
                        <ArrowIcon />
                      </>
                    )}
                  </button>
                </form>

                {status === 'error' ? (
                  <div id="waitlist-error" className="wl-error" role="alert">
                    <AlertIcon />
                    {message}
                  </div>
                ) : (
                  <div className="wl-form-meta">
                    <span>No spam.</span>
                    <span className="wl-meta-dot" aria-hidden />
                    <span>One email at launch.</span>
                    <span className="wl-meta-dot" aria-hidden />
                    <span>Unsubscribe in one click.</span>
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        <ProductPreview />
      </main>
    </div>
  )
}
