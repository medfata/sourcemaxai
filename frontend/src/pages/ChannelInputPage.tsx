import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { api } from '../api'
import type { ChannelMeta } from '../types'

interface ChannelInputPageProps {
  onResolved: (meta: ChannelMeta) => void
  initialUrl?: string
  autoSubmitInitialUrl?: boolean
  onInitialUrlConsumed?: () => void
}

const EXAMPLES = [
  { label: '@mkbhd', url: '@mkbhd' },
  { label: '@veritasium', url: '@veritasium' },
  { label: '@lexfridman', url: '@lexfridman' },
]

const HANDLE_RE = /^@[A-Za-z0-9._-]+$/

function normalizeChannelInput(raw: string): string {
  const trimmed = raw.trim()
  if (!trimmed) return ''
  if (HANDLE_RE.test(trimmed)) return `https://www.youtube.com/${trimmed}`
  return trimmed
}

const STEPS = [
  { n: '01', title: 'Pick a channel', body: 'Paste any YouTube URL or handle. We pull the catalogue automatically.' },
  { n: '02', title: 'Watch the AI work', body: 'Transcripts, summaries, and a structured profile build live in front of you.' },
  { n: '03', title: 'Ask anything', body: 'Chat with the channel. Every answer cites the exact moment in a video.' },
]

export default function ChannelInputPage({
  onResolved,
  initialUrl = '',
  autoSubmitInitialUrl = false,
  onInitialUrlConsumed,
}: ChannelInputPageProps) {
  const [url, setUrl] = useState(initialUrl)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const autoSubmittedUrlRef = useRef<string | null>(null)

  useEffect(() => {
    if (initialUrl) {
      setUrl(initialUrl)
    }
  }, [initialUrl])

  const resolveChannel = useCallback(async (nextUrl: string) => {
    setError('')
    const normalized = normalizeChannelInput(nextUrl)
    if (!normalized) {
      setError('Enter a URL, @handle, or playlist link to continue')
      return
    }
    setLoading(true)
    const res = await api.channel(normalized)
    setLoading(false)
    if (res.ok && res.data) {
      onInitialUrlConsumed?.()
      onResolved(res.data)
    } else {
      setError(res.error || 'Could not resolve channel')
    }
  }, [onInitialUrlConsumed, onResolved])

  useEffect(() => {
    const nextUrl = initialUrl.trim()
    if (!autoSubmitInitialUrl || !nextUrl || autoSubmittedUrlRef.current === nextUrl) return
    autoSubmittedUrlRef.current = nextUrl
    void resolveChannel(nextUrl)
  }, [autoSubmitInitialUrl, initialUrl, resolveChannel])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    await resolveChannel(url)
  }

  return (
    <div className="relative min-h-[100svh] overflow-hidden bg-cream dark:bg-ink-900">
      {/* Mesh gradient backdrop */}
      <div aria-hidden className="absolute inset-0 bg-gradient-mesh pointer-events-none" />
      <div aria-hidden className="absolute -top-40 -left-40 w-[480px] h-[480px] rounded-full bg-accent-red/20 blur-3xl animate-float" />
      <div aria-hidden className="absolute top-40 -right-40 w-[520px] h-[520px] rounded-full bg-accent-coral/15 blur-3xl animate-float" style={{ animationDelay: '2s' }} />
      <div aria-hidden className="absolute inset-0 noise" />

      {/* Top nav */}
      <div className="relative max-w-6xl mx-auto px-6 pt-8 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-7 h-7 rounded-lg bg-gradient-aurora" />
          <span className="text-[15px] font-semibold tracking-tight text-ink-900 dark:text-cream">Trace</span>
        </div>
        <span className="text-[12px] uppercase tracking-[0.18em] text-ink-400">v1 · beta</span>
      </div>

      {/* Hero */}
      <div className="relative max-w-3xl mx-auto px-6 pt-16 sm:pt-24 pb-20 text-center">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-black/5 dark:border-white/10 bg-white/60 dark:bg-white/5 backdrop-blur-md mb-8"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-accent-red animate-pulse-soft" />
          <span className="text-[12px] tracking-wide text-ink-500 dark:text-white/70">AI-powered creator analysis</span>
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.05 }}
          className="text-[44px] sm:text-[68px] lg:text-[84px] leading-[0.95] tracking-tighter text-ink-900 dark:text-cream font-display text-balance"
        >
          Trace any YouTube creator.<br />
          <em className="italic gradient-text not-italic font-display">In minutes, not months.</em>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.15 }}
          className="mt-6 max-w-xl mx-auto text-[17px] sm:text-[19px] leading-[1.5] text-ink-500 dark:text-white/60 text-pretty"
        >
          Turn a channel into a searchable, cited map of themes, claims, tone, and recurring ideas, with evidence from the original videos.
        </motion.p>

        <motion.form
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.25 }}
          onSubmit={handleSubmit}
          className="mt-10 max-w-xl mx-auto"
        >
          <div className="relative group">
            <div className="absolute -inset-0.5 rounded-2xl bg-gradient-aurora opacity-0 group-focus-within:opacity-30 blur transition-opacity duration-500" />
            <div className="relative flex items-center bg-white dark:bg-ink-700 rounded-2xl shadow-soft border border-black/5 dark:border-white/10 p-1.5">
              <input
                type="text"
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value)
                  if (error) setError('')
                }}
                placeholder="@handle, youtube.com/@channel, or playlist link"
                className="flex-1 h-12 px-4 bg-transparent text-[16px] text-ink-900 dark:text-cream placeholder:text-ink-300 dark:placeholder:text-white/30 outline-none"
              />
              <button
                type="submit"
                disabled={loading}
                className="h-12 px-5 sm:px-6 rounded-xl bg-ink-900 dark:bg-cream text-cream dark:text-ink-900 font-medium text-[14px] hover:bg-ink-700 dark:hover:bg-white transition-all active:scale-[0.97] disabled:opacity-50 flex items-center gap-2"
              >
                {loading ? (
                  <>
                    <span className="w-3 h-3 rounded-full border-2 border-current border-r-transparent animate-spin" />
                    Resolving
                  </>
                ) : (
                  <>
                    Analyze
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <line x1="5" y1="12" x2="19" y2="12" />
                      <polyline points="12 5 19 12 12 19" />
                    </svg>
                  </>
                )}
              </button>
            </div>
          </div>
          {error && (
            <motion.p
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-3 text-[13px] text-ios-red"
            >
              {error}
            </motion.p>
          )}

          <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
            <span className="text-[12px] text-ink-400 dark:text-white/40 mr-1">Try:</span>
            {EXAMPLES.map((ex) => (
              <button
                key={ex.url}
                type="button"
                onClick={() => {
                  setUrl(ex.url)
                  setError('')
                }}
                className="text-[12px] px-3 py-1.5 rounded-full border border-black/[0.08] dark:border-white/10 bg-white/60 dark:bg-white/5 text-ink-700 dark:text-white/70 hover:border-ink-900/20 hover:bg-white dark:hover:bg-white/10 transition-all"
              >
                {ex.label}
              </button>
            ))}
          </div>
        </motion.form>
      </div>

      {/* How it works */}
      <div className="relative max-w-6xl mx-auto px-6 pb-24">
        <div className="text-center mb-12">
          <span className="text-[11px] uppercase tracking-[0.22em] text-ink-400">How it works</span>
          <h2 className="mt-3 text-[32px] sm:text-[44px] tracking-tighter font-display text-ink-900 dark:text-cream">
            Three steps. Zero busywork.
          </h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {STEPS.map((step, i) => (
            <motion.div
              key={step.n}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-50px' }}
              transition={{ duration: 0.5, delay: i * 0.08 }}
              className="relative group p-6 rounded-3xl bg-white/60 dark:bg-white/[0.03] backdrop-blur-md border border-black/[0.06] dark:border-white/10 hover:border-ink-900/20 dark:hover:border-white/20 transition-all hover:-translate-y-0.5"
            >
              <span className="font-mono text-[12px] text-ink-300 dark:text-white/30">{step.n}</span>
              <h3 className="mt-4 font-display text-[26px] tracking-tight text-ink-900 dark:text-cream">{step.title}</h3>
              <p className="mt-2 text-[14px] text-ink-500 dark:text-white/60 leading-[1.6]">{step.body}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  )
}
