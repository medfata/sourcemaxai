import type { FormEvent } from 'react'
import { useRef, useState } from 'react'

import './LandingPage.css'

interface LandingPageProps {
  signedIn: boolean
  onLogin: () => void
  onOpenChannels: () => void
  onAnalyze: (url: string) => void
  onJoinWaitlist: () => void
}

type AnalyzeState = 'idle' | 'loading' | 'error'

const CHANNEL_RE = /^(https?:\/\/)?(www\.)?(youtube\.com\/(@?[\w.-]+)|youtu\.be\/[\w-]+|@[\w.-]+)/i

const EXAMPLE_CHIPS = [
  { label: '@mkbhd', value: 'youtube.com/@mkbhd' },
  { label: '@veritasium', value: 'youtube.com/@veritasium' },
  { label: '@lexfridman', value: 'youtube.com/@lexfridman' },
]

const THEMES = [
  { name: 'Federal Reserve policy', pct: 34, color: '#E5322B' },
  { name: 'Treasury yields & duration', pct: 22, color: '#2A2A2E' },
  { name: 'Consumer credit cycle', pct: 17, color: '#6B5B95' },
  { name: 'Commodities & inflation', pct: 14, color: '#88B04B' },
]

const HOW_STEPS = [
  { n: '01', title: 'Paste a channel', body: 'URL or @handle from YouTube.' },
  { n: '02', title: 'Build the profile', body: 'Themes, claims, tone, evidence.' },
  { n: '03', title: 'Search with citations', body: 'Every answer links back to the source.' },
]

function YouTubeGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M23 7.3c-.3-1.2-1.2-2.1-2.4-2.4C18.5 4.5 12 4.5 12 4.5s-6.5 0-8.6.4C2.2 5.2 1.3 6.1 1 7.3.6 9.4.6 12 .6 12s0 2.6.4 4.7c.3 1.2 1.2 2.1 2.4 2.4 2.1.4 8.6.4 8.6.4s6.5 0 8.6-.4c1.2-.3 2.1-1.2 2.4-2.4.4-2.1.4-4.7.4-4.7s0-2.6-.4-4.7zM9.7 15.6V8.4l6 3.6-6 3.6z" />
    </svg>
  )
}

function ArrowIcon() {
  return (
    <svg className="landing-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
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

function LockIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="4" y="11" width="16" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  )
}

function BrandMark() {
  return (
    <span className="landing-brand" aria-label="Trace home">
      <span className="landing-brand-mark" aria-hidden>T</span>
      <span>Trace</span>
    </span>
  )
}

function ProfileCard() {
  return (
    <div className="landing-card landing-layer landing-layer-profile">
      <div className="landing-card-head">
        <span className="landing-kicker">Channel profile</span>
        <span className="landing-tag">
          <span className="landing-dot-green" />
          Indexed
        </span>
      </div>
      <div className="landing-profile">
        <div className="landing-profile-avatar">LR</div>
        <div className="landing-profile-body">
          <div className="landing-profile-name">
            Lyn Robinson Macro
            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
              <path d="M12 2 9.5 6 5 7l3.5 3.5L8 15l4-2 4 2-.5-4.5L19 7l-4.5-1z" />
            </svg>
          </div>
          <div className="landing-profile-handle">@lynmacro - 412K subs</div>
          <div className="landing-profile-stats">
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
    <div className="landing-card landing-layer landing-layer-themes">
      <div className="landing-card-head">
        <div className="landing-card-title">
          <span className="landing-card-dot" />
          <span className="landing-kicker">Recurring themes - last 90d</span>
        </div>
        <div className="landing-card-actions">
          <span />
          <span />
        </div>
      </div>
      <div className="landing-themes">
        {THEMES.map((theme) => (
          <div className="landing-theme" key={theme.name}>
            <div className="landing-theme-label">
              <span className="landing-theme-dot" style={{ background: theme.color }} />
              <span className="landing-theme-name">{theme.name}</span>
            </div>
            <div className="landing-theme-meta">
              <span className="landing-theme-bar">
                <span style={{ width: `${(theme.pct / 34) * 100}%`, background: theme.color }} />
              </span>
              <span className="landing-theme-pct">{theme.pct}%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ClaimCard() {
  return (
    <div className="landing-card landing-layer landing-layer-claim">
      <div className="landing-card-head">
        <span className="landing-kicker">Claim - extracted</span>
        <span className="landing-tag">
          <span className="landing-dot-red" />
          Cited 3x
        </span>
      </div>
      <div className="landing-claim">
        <div className="landing-claim-quote">
          The Fed will cut <span>at least two times before September</span>, even if core inflation prints above 3.
        </div>
        <div className="landing-claim-meta">
          <span className="landing-tag landing-tag-confidence">
            <span className="landing-dot-green" />
            High confidence
          </span>
          <span className="landing-tag">topic - Fed policy</span>
        </div>
      </div>
    </div>
  )
}

function EvidenceCard() {
  return (
    <div className="landing-card landing-layer landing-layer-evidence">
      <div className="landing-card-head">
        <span className="landing-kicker">Evidence - jump to source</span>
      </div>
      <div className="landing-evidence">
        <div className="landing-thumb">
          <div className="landing-thumb-image" />
          <svg className="landing-thumb-play" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
            <path d="M8 5v14l11-7z" />
          </svg>
          <span className="landing-thumb-time">12:43</span>
        </div>
        <div className="landing-evidence-body">
          <div className="landing-evidence-title">Why I am still long duration - March macro update</div>
          <div className="landing-evidence-meta">
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
    <aside className="landing-preview landing-fade-up d5" aria-label="Product preview">
      <div className="landing-preview-label">
        <span>What you get</span>
        <span className="landing-preview-line" aria-hidden />
      </div>
      <ProfileCard />
      <ThemesCard />
      <ClaimCard />
      <EvidenceCard />
    </aside>
  )
}

function HowItWorks() {
  return (
    <section className="landing-how landing-fade-up d6" aria-label="How it works">
      {HOW_STEPS.map((step) => (
        <div className="landing-how-item" key={step.n}>
          <span className="landing-how-num">{step.n}</span>
          <span className="landing-how-title">{step.title}</span>
          <span className="landing-how-desc">{step.body}</span>
        </div>
      ))}
    </section>
  )
}

export default function LandingPage({ signedIn, onLogin, onOpenChannels, onAnalyze, onJoinWaitlist }: LandingPageProps) {
  const [url, setUrl] = useState('')
  const [state, setState] = useState<AnalyzeState>('idle')
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const appLabel = signedIn ? 'Open app' : 'Sign in'

  const fillChip = (value: string) => {
    setUrl(value)
    if (state === 'error') {
      setState('idle')
      setError('')
    }
    inputRef.current?.focus()
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (state === 'loading') return
    const nextUrl = url.trim()
    if (!nextUrl || !CHANNEL_RE.test(nextUrl)) {
      setError('Paste a YouTube channel URL or @handle.')
      setState('error')
      inputRef.current?.focus()
      return
    }
    setError('')
    setState('loading')
    onAnalyze(nextUrl)
  }

  return (
    <div className="landing-page">
      <nav className="landing-nav">
        <BrandMark />
        <div className="landing-nav-actions">
          <button type="button" className="landing-nav-link landing-nav-waitlist" onClick={onJoinWaitlist}>
            <span className="landing-nav-dot" aria-hidden />
            <span>Join waitlist</span>
          </button>
          <button type="button" className="landing-nav-link landing-nav-app" onClick={signedIn ? onOpenChannels : onLogin}>
            {appLabel}
          </button>
        </div>
      </nav>

      <main className="landing-shell">
        <section className="landing-hero">
          <div className="landing-badge landing-fade-up d1">
            <span className="landing-badge-dot" aria-hidden />
            <span>AI-powered creator analysis</span>
          </div>

          <h1 className="landing-headline landing-fade-up d2">Map any YouTube channel in minutes.</h1>

          <p className="landing-sub landing-fade-up d3">
            Trace profiles creators by themes, claims, tone, and evidence, with citations back to the original videos.
          </p>

          <div className="landing-fade-up d4">
            <form className="landing-form" onSubmit={handleSubmit} noValidate>
              <div className="landing-input-wrap">
                <span className="landing-input-icon" aria-hidden>
                  <YouTubeGlyph />
                </span>
                <input
                  ref={inputRef}
                  className={`landing-input${state === 'error' ? ' is-error' : ''}`}
                  type="url"
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="youtube.com/@channel"
                  value={url}
                  onChange={(event) => {
                    setUrl(event.target.value)
                    if (state === 'error') {
                      setState('idle')
                      setError('')
                    }
                  }}
                  disabled={state === 'loading'}
                  aria-invalid={state === 'error'}
                  aria-describedby={state === 'error' ? 'landing-form-error' : undefined}
                />
              </div>
              <button className="landing-button" type="submit" disabled={state === 'loading'}>
                {state === 'loading' ? (
                  <>
                    <span className="landing-spinner" aria-hidden />
                    <span>Analyzing...</span>
                  </>
                ) : (
                  <>
                    <span>Analyze</span>
                    <ArrowIcon />
                  </>
                )}
              </button>
            </form>

            {state === 'error' ? (
              <div id="landing-form-error" className="landing-error" role="alert">
                <AlertIcon />
                {error}
              </div>
            ) : (
              <div className="landing-helper">
                <span className="landing-lock">
                  <LockIcon />
                </span>
                <span>You&apos;ll sign in before analysis starts.</span>
              </div>
            )}

            <div className="landing-chips" role="group" aria-label="Example channels">
              <span className="landing-chips-label">Try</span>
              {EXAMPLE_CHIPS.map((chip) => (
                <button key={chip.label} type="button" className="landing-chip" onClick={() => fillChip(chip.value)}>
                  <span className="landing-chip-dot" aria-hidden />
                  {chip.label}
                </button>
              ))}
            </div>
          </div>
        </section>

        <ProductPreview />
        <HowItWorks />
      </main>
    </div>
  )
}
