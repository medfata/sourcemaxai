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

const PROOF_AVATARS = [
  { initials: 'JN', cls: 'wl-avatar-1' },
  { initials: 'RP', cls: 'wl-avatar-2' },
  { initials: 'MK', cls: 'wl-avatar-3' },
  { initials: 'SL', cls: 'wl-avatar-4' },
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

function TraceMark({ onBackHome }: { onBackHome: () => void }) {
  return (
    <button type="button" className="wl-brand" onClick={onBackHome} aria-label="Sourcemax home">
      <img className="wl-brand-mark" src="/sourcemax_icon.png" alt="" aria-hidden />
      <span>Sourcemax</span>
    </button>
  )
}

function Nav({ signedIn, onBackHome, onLogin, onOpenChannels }: WaitlistPageProps) {
  return (
    <nav className="wl-nav">
      <TraceMark onBackHome={onBackHome} />
      <div className="wl-nav-actions">
        <button type="button" className="wl-nav-link" onClick={onBackHome}>
          Back to Sourcemax
        </button>
        <button type="button" className="wl-nav-link wl-nav-link-strong" onClick={signedIn ? onOpenChannels : onLogin}>
          {signedIn ? 'Open app' : 'Sign in'}
        </button>
      </div>
    </nav>
  )
}

function Proof() {
  return (
    <div className="wl-proof fade-up d5">
      <div className="wl-avatars" aria-hidden>
        {PROOF_AVATARS.map((a) => (
          <div className={`wl-avatar ${a.cls}`} key={a.initials}>{a.initials}</div>
        ))}
      </div>
      <span>Built with analysts, journalists and creators tracking dozens of channels at a time.</span>
    </div>
  )
}

function SearchCard() {
  return (
    <div className="wl-card wl-search-card wl-layer wl-layer-search">
      <span className="wl-search-prefix" aria-hidden>
        <img className="wl-search-mark" src="/sourcemax_icon.png" alt="" />
        <span className="wl-search-arrow">›</span>
      </span>
      <div className="wl-query">
        what does MKBHD keep coming back to about Apple
        <span className="wl-cursor" />
      </div>
      <span className="wl-grounded" title="Grounded in MKBHD's profile">
        <span className="wl-grounded-dot" />
        grounded
      </span>
      <span className="wl-kbd">↵</span>
    </div>
  )
}

function ProfileCard() {
  return (
    <div className="wl-card wl-layer wl-layer-profile">
      <div className="wl-card-head">
        <span className="wl-kicker">Channel · profile</span>
        <span className="wl-tag wl-tag-confidence">
          <span className="wl-dot-green" />
          87% confidence
        </span>
      </div>
      <div className="wl-profile">
        <div className="wl-profile-avatar">
          <img src="/mkbhd.jpg" alt="Marques Brownlee" />
        </div>
        <div className="wl-profile-body">
          <div className="wl-profile-name">Marques Brownlee</div>
          <div className="wl-profile-handle">@mkbhd · 19.4M subs</div>
          <div className="wl-profile-stats">
            <span><b>47</b>/412 videos</span>
            <span><b>4h 22m</b> analyzed</span>
            <span>refreshed <b>12m ago</b></span>
          </div>
        </div>
      </div>
      <p className="wl-profile-fingerprint">
        <span className="wl-profile-fingerprint-mark" aria-hidden>“</span>
        Polished, comparative, and quietly skeptical of flagship innovation.
      </p>
    </div>
  )
}

function ThemesCard() {
  return (
    <div className="wl-card wl-layer wl-layer-themes">
      <div className="wl-card-head">
        <div className="wl-card-title">
          <span className="wl-card-dot" />
          <span className="wl-kicker">Dominant themes · last 12mo</span>
        </div>
        <span className="wl-kicker wl-kicker-small">4 clusters</span>
      </div>
      <ul className="wl-themes-list">
        {THEMES.map((theme) => (
          <li className="wl-theme-row" key={theme.num}>
            <span className="wl-theme-num">{theme.num}</span>
            <div className="wl-theme-body">
              <span className="wl-theme-name">{theme.name}</span>
              <div className="wl-theme-cites">
                {theme.cites.map((c) => (
                  <span className="wl-theme-cite" key={c.n}>
                    <span className="wl-theme-cite-num">[{c.n}]</span>
                    <span className="wl-theme-cite-ts">{c.ts}</span>
                  </span>
                ))}
              </div>
            </div>
            <div className="wl-theme-stat">
              <span className="wl-theme-pct">{theme.pct}<i>%</i></span>
              <span className="wl-theme-count">{theme.count} vids</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ClaimCard() {
  return (
    <div className="wl-card wl-layer wl-layer-claim">
      <div className="wl-card-head">
        <span className="wl-kicker">Claim · extracted</span>
        <span className="wl-tag wl-tag-cite">
          <span className="wl-tag-cite-dot" />
          [1] · 12:08
        </span>
      </div>
      <div className="wl-claim">
        <div className="wl-claim-quote">
          “…the hardware is so polished it almost forgives the software —{' '}
          <span>a beautifully finished prototype, not a finished product</span>.”
        </div>
        <div className="wl-claim-meta">
          <span className="wl-tag wl-tag-confidence">
            <span className="wl-dot-green" />
            High confidence
          </span>
          <span className="wl-tag wl-tag-mono">Vision Pro review</span>
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
      <span className="wl-thumb-time">24:09</span>
    </div>
  )
}

function EvidenceCard() {
  return (
    <div className="wl-card wl-layer wl-layer-evidence">
      <div className="wl-card-head">
        <span className="wl-kicker">Source · jump to transcript</span>
        <span className="wl-evidence-cite-num">[1]</span>
      </div>
      <div className="wl-evidence">
        <Thumb />
        <div className="wl-evidence-body">
          <div className="wl-evidence-title">Apple Vision Pro Review: Magic, Until It&apos;s Not.</div>
          <div className="wl-evidence-meta">
            <span>@mkbhd</span>
            <span>·</span>
            <span>1mo ago</span>
            <span>·</span>
            <span className="wl-evidence-ts">▸ 12:08</span>
          </div>
        </div>
      </div>
      <div className="wl-evidence-transcript">
        <span className="wl-evidence-transcript-pre">…forgives the software —</span>{' '}
        <span className="wl-evidence-transcript-hl">a beautifully finished prototype, not a finished product</span>
        <span className="wl-evidence-transcript-post">, and that gap is what most reviews…</span>
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
      setMessage('Could not reach Sourcemax. Please try again.')
    }
  }

  return (
    <div className="waitlist-page">
      <Nav {...props} />

      <main className="wl-page">
        <section className="wl-hero">
          <img
            className="wl-hero-mark fade-up d1"
            src="/sourcemax_icon.png"
            alt=""
            aria-hidden
          />
          <div className="wl-badge fade-up d1">
            <span className="wl-badge-dot" aria-hidden />
            <span>1,000 free transcript minutes at launch</span>
          </div>

          <h1 className="wl-headline fade-up d2">Join the Sourcemax waitlist.</h1>

          <p className="wl-sub fade-up d3">
            Profile any YouTube channel — themes, claims, tone, evidence — with every line cited back to the exact timestamp.
          </p>

          <p className="wl-supporting fade-up d3">
            Early access gets 1,000 transcript minutes free — roughly{' '}
            <b>60 long-form videos</b> fully profiled, with no card on file.
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
                    Your 1,000 minutes will be ready at launch. We&apos;ll email <b>{email || 'you'}</b> the moment your workspace opens — no other emails.
                  </div>
                  <span className="wl-success-tag">
                    <MailIcon size={11} />
                    confirmation sent
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
                        <span>Joining…</span>
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
                    <span>One email when your workspace opens.</span>
                    <span className="wl-meta-dot" aria-hidden />
                    <span>Unsubscribe in one click.</span>
                  </div>
                )}
              </>
            )}
          </div>

          {!isSuccess && <Proof />}
        </section>

        <ProductPreview />
      </main>
    </div>
  )
}
