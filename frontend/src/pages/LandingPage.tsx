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

interface ThemeCite {
  n: number
  ts: string
}

interface ThemeRow {
  num: string
  name: string
  pct: number
  count: number
  cites: ThemeCite[]
}

const THEMES: ThemeRow[] = [
  { num: '01', name: 'Polished but unfinished',   pct: 28, count: 14, cites: [{ n: 1, ts: '12:08' }, { n: 2, ts: '04:42' }] },
  { num: '02', name: 'The boring innovation era', pct: 19, count: 9,  cites: [{ n: 3, ts: '01:33' }] },
  { num: '03', name: 'Foldables as the test bed', pct: 14, count: 8,  cites: [{ n: 4, ts: '18:27' }] },
  { num: '04', name: 'The review threshold',      pct: 9,  count: 6,  cites: [] },
]

const HOW_STEPS = [
  { n: '01', title: 'Paste a channel', body: 'URL or @handle. Sourcemax fetches every video.' },
  { n: '02', title: 'We transcribe & synthesize', body: 'Captions, ASR fallback, then themes, claims & tone.' },
  { n: '03', title: 'Ask anything, cited', body: 'Every answer links back to the exact timestamp.' },
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
    <span className="landing-brand" aria-label="Sourcemax home">
      <img className="landing-brand-mark" src="/sourcemax_icon.png" alt="" aria-hidden />
      <span>Sourcemax</span>
    </span>
  )
}

function ProfileCard() {
  return (
    <div className="landing-card landing-layer landing-layer-profile">
      <div className="landing-card-head">
        <span className="landing-kicker">Channel · profile</span>
        <span className="landing-tag landing-tag-confidence">
          <span className="landing-dot-green" />
          87% confidence
        </span>
      </div>
      <div className="landing-profile">
        <div className="landing-profile-avatar">
          <img src="/mkbhd.jpg" alt="Marques Brownlee" />
        </div>
        <div className="landing-profile-body">
          <div className="landing-profile-name">Marques Brownlee</div>
          <div className="landing-profile-handle">@mkbhd · 19.4M subs</div>
          <div className="landing-profile-stats">
            <span><b>47</b>/412 videos</span>
            <span><b>4h 22m</b> analyzed</span>
            <span>refreshed <b>12m ago</b></span>
          </div>
        </div>
      </div>
      <p className="landing-profile-fingerprint">
        <span className="landing-profile-fingerprint-mark" aria-hidden>“</span>
        Polished, comparative, and quietly skeptical of flagship innovation.
      </p>
    </div>
  )
}

function ThemesCard() {
  return (
    <div className="landing-card landing-layer landing-layer-themes">
      <div className="landing-card-head">
        <div className="landing-card-title">
          <span className="landing-card-dot" />
          <span className="landing-kicker">Dominant themes · last 12mo</span>
        </div>
        <span className="landing-kicker landing-kicker-small">4 clusters</span>
      </div>
      <ul className="landing-themes-list">
        {THEMES.map((theme) => (
          <li className="landing-theme-row" key={theme.num}>
            <span className="landing-theme-num">{theme.num}</span>
            <div className="landing-theme-body">
              <span className="landing-theme-name">{theme.name}</span>
              <div className="landing-theme-cites">
                {theme.cites.map((c) => (
                  <span className="landing-theme-cite" key={c.n}>
                    <span className="landing-theme-cite-num">[{c.n}]</span>
                    <span className="landing-theme-cite-ts">{c.ts}</span>
                  </span>
                ))}
              </div>
            </div>
            <div className="landing-theme-stat">
              <span className="landing-theme-pct">{theme.pct}<i>%</i></span>
              <span className="landing-theme-count">{theme.count} vids</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ClaimCard() {
  return (
    <div className="landing-card landing-layer landing-layer-claim">
      <div className="landing-card-head">
        <span className="landing-kicker">Claim · extracted</span>
        <span className="landing-tag landing-tag-cite">
          <span className="landing-tag-cite-dot" />
          [1] · 12:08
        </span>
      </div>
      <div className="landing-claim">
        <div className="landing-claim-quote">
          “…the hardware is so polished it almost forgives the software —{' '}
          <span>a beautifully finished prototype, not a finished product</span>.”
        </div>
        <div className="landing-claim-meta">
          <span className="landing-tag landing-tag-confidence">
            <span className="landing-dot-green" />
            High confidence
          </span>
          <span className="landing-tag landing-tag-mono">Vision Pro review</span>
        </div>
      </div>
    </div>
  )
}

function EvidenceCard() {
  return (
    <div className="landing-card landing-layer landing-layer-evidence">
      <div className="landing-card-head">
        <span className="landing-kicker">Source · jump to transcript</span>
        <span className="landing-evidence-cite-num">[1]</span>
      </div>
      <div className="landing-evidence">
        <div className="landing-thumb">
          <div className="landing-thumb-image" />
          <svg className="landing-thumb-play" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
            <path d="M8 5v14l11-7z" />
          </svg>
          <span className="landing-thumb-time">24:09</span>
        </div>
        <div className="landing-evidence-body">
          <div className="landing-evidence-title">Apple Vision Pro Review: Magic, Until It&apos;s Not.</div>
          <div className="landing-evidence-meta">
            <span>@mkbhd</span>
            <span>·</span>
            <span>1mo ago</span>
            <span>·</span>
            <span className="landing-evidence-ts">▸ 12:08</span>
          </div>
        </div>
      </div>
      <div className="landing-evidence-transcript">
        <span className="landing-evidence-transcript-pre">…forgives the software —</span>{' '}
        <span className="landing-evidence-transcript-hl">a beautifully finished prototype, not a finished product</span>
        <span className="landing-evidence-transcript-post">, and that gap is what most reviews…</span>
      </div>
    </div>
  )
}

function ProductPreview() {
  return (
    <aside className="landing-preview landing-fade-up d5" aria-label="Product preview">
      <div className="landing-preview-label">
        <span>A real channel, traced</span>
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
          <img
            className="landing-hero-mark landing-fade-up d1"
            src="/sourcemax_icon.png"
            alt=""
            aria-hidden
          />
          <div className="landing-badge landing-fade-up d1">
            <span className="landing-badge-dot" aria-hidden />
            <span>Private beta · cited creator profiles</span>
          </div>

          <h1 className="landing-headline landing-fade-up d2">
            Map any <span className="landing-yt-glow">YouTube</span>
            <br />
            channel in minutes.
          </h1>

          <p className="landing-sub landing-fade-up d3">
            Sourcemax turns a creator&apos;s last year of video into a profile of themes, claims, and tone — every line cited back to the exact timestamp.
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
              <button className={`landing-button${state === 'loading' ? ' is-analyzing' : ''}`} type="submit" disabled={state === 'loading'}>
                {state === 'loading' ? (
                  <>
                    <span className="landing-spinner" aria-hidden />
                    <span>Analyzing…</span>
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
                <span>You&apos;ll sign in before the pipeline starts.</span>
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
