import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, apiStreamFetch } from '../api'
import type { ApiResponse, ChannelMeta, ChatMessage, ChatSessionSummary, ChatSource, PersistedChatMessage, Profile, ProfileVideo } from '../types'
import EvidenceSheet from '../components/EvidenceSheet'
import ChartArtifact from '../components/ChartArtifact'
import ScopeChips from '../components/ScopeChips'
import { formatShortDate, formatTimestamp } from '../utils/date'

type CitationClickHandler = (
  videoId: string,
  startSeconds: number,
  sourceId?: string,
  messageIdx?: number,
) => void

const _citationClickHandler: { current: CitationClickHandler } = {
  current: (_videoId: string, _startSeconds: number) => {},
}
export function setCitationClickHandler(fn: CitationClickHandler) {
  _citationClickHandler.current = fn
}

interface Scope {
  themes: string[]
  tones: string[]
  dateFrom?: string
  dateTo?: string
}

interface CitedRef {
  sourceId?: string
  videoId: string
  startSeconds: number
  messageIdx: number
  profileVideo?: ProfileVideo
  evidenceQuote?: string
  title?: string
  uploadDate?: string
  source?: ChatSource
}

const isYouTubeCitationHref = (href: unknown): href is string =>
  typeof href === 'string' && parseCitationHref(href) !== null

const isUnknownSourceHref = (href: unknown): href is string =>
  typeof href === 'string' && href.startsWith('#unknown-source-')

function parseTimestampParam(value: string | null): number | null {
  if (!value) return null
  const trimmed = value.trim().toLowerCase()
  const secondsOnly = trimmed.match(/^(\d+)s?$/)
  if (secondsOnly) return Number(secondsOnly[1])
  const parts = trimmed.match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$/)
  if (!parts || !parts[0]) return null
  const hours = Number(parts[1] ?? 0)
  const minutes = Number(parts[2] ?? 0)
  const seconds = Number(parts[3] ?? 0)
  return hours * 3600 + minutes * 60 + seconds
}

interface ParsedCitation {
  videoId: string
  startSeconds: number
  sourceId?: string
  messageIdx?: number
}

function parseCitationHref(href: string): ParsedCitation | null {
  try {
    const url = new URL(href)
    const host = url.hostname.replace(/^www\./, '')
    const videoId =
      host === 'youtu.be'
        ? url.pathname.split('/').filter(Boolean)[0]
        : host.endsWith('youtube.com')
          ? url.searchParams.get('v')
          : null
    const startSeconds = parseTimestampParam(url.searchParams.get('t') ?? url.searchParams.get('start'))
    if (!videoId || !/^[\w-]{11}$/.test(videoId) || startSeconds === null) return null
    const hashParams = new URLSearchParams(url.hash.replace(/^#/, ''))
    const sourceId = hashParams.get('source') ?? undefined
    const rawMessageIdx = hashParams.get('message')
    const messageIdx = rawMessageIdx !== null ? Number(rawMessageIdx) : undefined
    return {
      videoId,
      startSeconds,
      sourceId,
      messageIdx: Number.isInteger(messageIdx) ? messageIdx : undefined,
    }
  } catch {
    return null
  }
}

function findEvidenceQuote(profileVideo: ProfileVideo | undefined, startSeconds: number): string | null {
  if (!profileVideo) return null
  const evidenceGroups: unknown[] = [
    ...(profileVideo.key_claims ?? []),
    ...(profileVideo.notable_opinions ?? []),
  ]
  for (const group of evidenceGroups) {
    if (!group || typeof group !== 'object') continue
    const evidence = (group as { evidence?: unknown }).evidence
    if (!Array.isArray(evidence)) continue
    for (const entry of evidence) {
      if (!entry || typeof entry !== 'object') continue
      const start = Number((entry as { start_seconds?: unknown }).start_seconds)
      const quote = (entry as { quote?: unknown }).quote
      if (Number.isFinite(start) && start === startSeconds && typeof quote === 'string') {
        return quote
      }
    }
  }
  return null
}

function normalizeSources(value: unknown): ChatSource[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((source): ChatSource[] => {
    if (!source || typeof source !== 'object') return []
    const raw = source as Record<string, unknown>
    const sourceId = typeof raw.source_id === 'string' ? raw.source_id : ''
    const videoId = typeof raw.video_id === 'string' ? raw.video_id : ''
    const startSeconds = Number(raw.start_seconds)
    if (!sourceId || !videoId || !Number.isFinite(startSeconds)) return []

    const normalized: ChatSource = {
      source_id: sourceId,
      video_id: videoId,
      start_seconds: Math.max(0, Math.floor(startSeconds)),
    }
    if (typeof raw.kind === 'string') normalized.kind = raw.kind
    if (typeof raw.chunk_id === 'string') normalized.chunk_id = raw.chunk_id
    if (typeof raw.title === 'string') normalized.title = raw.title
    if (typeof raw.upload_date === 'string') normalized.upload_date = raw.upload_date
    if (typeof raw.quote === 'string') normalized.quote = raw.quote
    const endSeconds = Number(raw.end_seconds)
    if (Number.isFinite(endSeconds)) normalized.end_seconds = Math.max(0, Math.floor(endSeconds))
    return [normalized]
  })
}

function sourceToRef(source: ChatSource, messageIdx: number, profile: Profile | null): CitedRef | null {
  if (!/^[\w-]{11}$/.test(source.video_id) || !Number.isFinite(source.start_seconds)) return null
  const profileVideo = profile?.videos?.find((video) => video.video_id === source.video_id)
  return {
    sourceId: source.source_id,
    videoId: source.video_id,
    startSeconds: source.start_seconds,
    messageIdx,
    profileVideo,
    evidenceQuote: source.quote || findEvidenceQuote(profileVideo, source.start_seconds) || undefined,
    title: source.title || profileVideo?.title,
    uploadDate: source.upload_date || profileVideo?.upload_date,
    source,
  }
}

function youtubeUrlForSource(source: ChatSource, messageIdx: number): string | null {
  if (!/^[\w-]{11}$/.test(source.video_id) || !Number.isFinite(source.start_seconds)) return null
  const params = new URLSearchParams({ source: source.source_id, message: String(messageIdx) })
  return `https://youtu.be/${source.video_id}?t=${Math.max(0, Math.floor(source.start_seconds))}s#${params.toString()}`
}

function replaceSourceMarkers(segment: string, sources: ChatSource[] | undefined, messageIdx: number): string {
  const sourceMap = new Map((sources ?? []).map((source) => [source.source_id, source]))
  return segment.replace(/\[(S\d+)\](?!\()/g, (_marker, sourceId: string) => {
    const source = sourceMap.get(sourceId)
    if (!source) return `[${sourceId}](#unknown-source-${sourceId})`
    const href = youtubeUrlForSource(source, messageIdx)
    return href ? `[${sourceId}](${href})` : `[${sourceId}](#unknown-source-${sourceId})`
  })
}

function renderCitationMarkdown(content: string, sources: ChatSource[] | undefined, messageIdx: number): string {
  let rendered = ''
  let lastIndex = 0
  const fenceRegex = /```[\s\S]*?```/g
  let match: RegExpExecArray | null
  while ((match = fenceRegex.exec(content)) !== null) {
    rendered += replaceSourceMarkers(content.slice(lastIndex, match.index), sources, messageIdx)
    rendered += match[0]
    lastIndex = match.index + match[0].length
  }
  rendered += replaceSourceMarkers(content.slice(lastIndex), sources, messageIdx)
  return rendered
}

function contentWithoutFencedCode(content: string): string {
  return content.replace(/```[\s\S]*?```/g, '')
}

function extractCitations(messages: ChatMessage[], profile: Profile | null): CitedRef[] {
  const citedRefs: CitedRef[] = []
  const videoMap = new Map((profile?.videos ?? []).map((v) => [v.video_id, v]))
  messages.forEach((message, msgIdx) => {
    if (message.role !== 'assistant' || !message.content) return
    const citationContent = contentWithoutFencedCode(message.content)
    const sourceMap = new Map((message.sources ?? []).map((source) => [source.source_id, source]))
    const sourceCitationRegex = /\[(S\d+)\]/g
    let sourceMatch
    while ((sourceMatch = sourceCitationRegex.exec(citationContent)) !== null) {
      const source = sourceMap.get(sourceMatch[1])
      if (!source) continue
      const ref = sourceToRef(source, msgIdx, profile)
      if (ref) citedRefs.push(ref)
    }

    const citationRegex = /\[↗\s*[^\]]*\]\((https?:\/\/[^\s)]+)\)/g
    let match
    while ((match = citationRegex.exec(citationContent)) !== null) {
      const citationData = parseCitationHref(match[1])
      if (citationData) {
        const profileVideo = videoMap.get(citationData.videoId)
        const evidenceQuote = findEvidenceQuote(profileVideo, citationData.startSeconds)
        citedRefs.push({
          videoId: citationData.videoId,
          startSeconds: citationData.startSeconds,
          messageIdx: msgIdx,
          profileVideo: profileVideo ?? undefined,
          evidenceQuote: evidenceQuote ?? undefined,
          title: profileVideo?.title,
          uploadDate: profileVideo?.upload_date,
        })
      }
    }
  })
  return citedRefs
}

function buildScopePayload(scope: Scope) {
  const hasActiveScope =
    scope.themes.length > 0 || scope.tones.length > 0 || Boolean(scope.dateFrom) || Boolean(scope.dateTo)
  if (!hasActiveScope) return undefined
  return {
    themes: scope.themes,
    tones: scope.tones,
    date_from: scope.dateFrom,
    date_to: scope.dateTo,
  }
}

function messageFromPersisted(message: PersistedChatMessage): ChatMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    sources: normalizeSources(message.sources),
    unknownSourceIds: message.unknown_source_ids,
    created_at: message.created_at,
    sequence: message.sequence,
  }
}

async function* sseStream(response: Response): AsyncGenerator<string, void, unknown> {
  if (!response.body) return
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const idx = buffer.indexOf('\n\n')
      if (idx !== -1) {
        const chunk = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        for (const line of chunk.split('\n')) {
          if (line.startsWith('data: ')) yield line.slice(6)
        }
      }
    }
    if (buffer.length) {
      for (const line of buffer.split('\n')) {
        if (line.startsWith('data: ')) yield line.slice(6)
      }
    }
  } finally {
    reader.releaseLock()
  }
}

interface ChatPageProps {
  channel: ChannelMeta
  onBack: () => void
  onComplete?: () => void
  initialInput?: string
  embedded?: boolean
  chatSessionId?: string
  onSessionCreated?: (session: ChatSessionSummary) => void
  onSessionUpdated?: (session: ChatSessionSummary) => void
}

const SUGGESTED_PROMPTS = [
  "What are this channel's main themes?",
  "How has the creator's stance evolved over time?",
  'What does this person believe most strongly?',
  'What topics keep coming up?',
  'Who or what does this channel reference most?',
]

function SendIcon({ className }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  )
}

function PaperclipIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="m21 11-9 9a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8" />
    </svg>
  )
}

function FilterIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 5h18l-7 9v6l-4-2v-4z" />
    </svg>
  )
}

function SparkIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" />
    </svg>
  )
}

function PlayIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  )
}

function ExternalIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 4h6v6M10 14 20 4M19 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h6" />
    </svg>
  )
}

function sourceTitle(ref: CitedRef): string {
  return ref.title ?? ref.profileVideo?.title ?? ref.source?.title ?? 'Unknown video'
}

function sourceDate(ref: CitedRef): string {
  const raw = ref.uploadDate ?? ref.profileVideo?.upload_date ?? ref.source?.upload_date ?? ''
  return raw && raw.length === 8 ? formatShortDate(raw) : raw
}

function sourceLabel(ref: CitedRef): string {
  return ref.sourceId ? `[${ref.sourceId}]` : '[source]'
}

function messageSourceRefs(message: ChatMessage, messageIdx: number, profile: Profile | null): CitedRef[] {
  const refs = (message.sources ?? [])
    .map((source) => sourceToRef(source, messageIdx, profile))
    .filter((ref): ref is CitedRef => Boolean(ref))
  const seen = new Set<string>()
  return refs.filter((ref) => {
    const key = `${ref.sourceId ?? ''}:${ref.videoId}:${ref.startSeconds}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function MessageSources({
  refs,
  channelName,
  onOpen,
}: {
  refs: CitedRef[]
  channelName: string
  onOpen: (ref: CitedRef) => void
}) {
  const [expanded, setExpanded] = useState(false)
  if (refs.length === 0) return null
  const visibleRefs = expanded ? refs : refs.slice(0, 3)
  const overflowCount = Math.max(0, refs.length - visibleRefs.length)

  return (
    <div className={`trace-sources ${expanded ? 'expanded' : ''}`}>
      <div className="trace-sources-head">
        <div className="trace-sources-label">Cited sources</div>
        {refs.length > 3 && (
          <button type="button" className="trace-sources-toggle" onClick={() => setExpanded((value) => !value)}>
            {expanded ? 'See less' : `See ${overflowCount} more`}
          </button>
        )}
      </div>
      <div className="trace-sources-list">
        {visibleRefs.map((ref) => (
          <button
            key={`${ref.sourceId ?? 'source'}-${ref.videoId}-${ref.startSeconds}`}
            type="button"
            className="trace-source-row"
            onClick={() => onOpen(ref)}
          >
            <span className="trace-source-thumb">
              <img src={`https://i.ytimg.com/vi/${ref.videoId}/mqdefault.jpg`} alt="" loading="lazy" />
              <PlayIcon />
              <span>{formatTimestamp(ref.startSeconds)}</span>
            </span>
            <span className="trace-source-body">
              <span className="trace-source-title">{sourceTitle(ref)}</span>
              <span className="trace-source-meta">
                <span className="trace-source-id">{sourceLabel(ref)}</span>
                <span>{formatTimestamp(ref.startSeconds)}</span>
                <span>{channelName}</span>
                {sourceDate(ref) && <span>{sourceDate(ref)}</span>}
              </span>
            </span>
            <ExternalIcon />
          </button>
        ))}
      </div>
    </div>
  )
}

export default function ChatPage({
  channel,
  onBack,
  onComplete,
  initialInput,
  embedded = false,
  chatSessionId,
  onSessionCreated,
  onSessionUpdated,
}: ChatPageProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [focusedRef, setFocusedRef] = useState<CitedRef | null>(null)
  const [conversationRefs, setConversationRefs] = useState<CitedRef[]>([])
  const [scope, setScope] = useState<Scope>({ themes: [], tones: [] })
  const [filtersOpen, setFiltersOpen] = useState(false)
  const completedRef = useRef(false)
  const seedAppliedRef = useRef(false)
  const autoFocusRef = useRef(true)
  const activeSessionIdRef = useRef<string | undefined>(chatSessionId)
  const scrollRef = useRef<HTMLDivElement>(null)
  const userScrolledUp = useRef(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    if (!userScrolledUp.current) el.scrollTop = el.scrollHeight
  }, [])

  useEffect(() => {
    if (initialInput && !seedAppliedRef.current) {
      setInput(initialInput)
      seedAppliedRef.current = true
    }
  }, [initialInput])

  useEffect(() => {
    activeSessionIdRef.current = chatSessionId
    seedAppliedRef.current = false
    autoFocusRef.current = true
    setError(null)
    setFocusedRef(null)
    setSheetOpen(false)

    if (streaming) return
    if (!chatSessionId) {
      setMessages([])
      setHistoryLoading(false)
      return
    }

    let cancelled = false
    setHistoryLoading(true)
    api.chatSession(channel.channel_id, chatSessionId)
      .then((body) => {
        if (cancelled) return
        if (!body.ok || !body.data) {
          setError(body.error || 'Failed to load chat history')
          setMessages([])
          return
        }
        setMessages(body.data.messages.map(messageFromPersisted))
        onSessionUpdated?.(body.data.session)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load chat history')
          setMessages([])
        }
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [channel.channel_id, chatSessionId, streaming, onSessionUpdated])

  useEffect(() => {
    async function fetchProfile() {
      try {
        const body = await api.profile(channel.channel_id) as ApiResponse<Profile>
        setProfile(body.ok && body.data ? body.data : null)
      } catch (err) { console.error('Failed to fetch profile:', err) }
    }
    if (channel.channel_id) fetchProfile()
  }, [channel.channel_id])

  useEffect(() => { setConversationRefs(extractCitations(messages, profile)) }, [messages, profile])
  useEffect(() => { scrollToBottom() }, [messages, scrollToBottom])

  // Auto-grow textarea
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }, [input])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    userScrolledUp.current = el.scrollHeight - el.scrollTop - el.clientHeight >= 40
  }

  const handleCitationClick = useCallback((
    videoId: string,
    startSeconds: number,
    sourceId?: string,
    messageIdx?: number,
  ) => {
    const ref = conversationRefs.find((r) => {
      if (messageIdx !== undefined && r.messageIdx !== messageIdx) return false
      if (sourceId) return r.sourceId === sourceId
      return r.videoId === videoId && r.startSeconds === startSeconds
    })
    if (ref) {
      setFocusedRef(ref)
      setSheetOpen(true)
    }
  }, [conversationRefs])

  useEffect(() => { setCitationClickHandler(handleCitationClick) }, [handleCitationClick])

  const markdownComponents: Components = {
    a: ({ href, children }) => {
      if (isUnknownSourceHref(href)) {
        const sourceId = href.replace('#unknown-source-', '')
        return (
          <span
            title={`${sourceId} was not included in the source registry`}
            className="text-[12px] font-medium text-ink-400 bg-ink-100 dark:bg-white/[0.08] rounded-md px-1.5 py-0.5 mx-0.5 no-underline box-decoration-clone break-words cursor-not-allowed"
          >
            {children}
          </span>
        )
      }
      if (isYouTubeCitationHref(href)) {
        const citationData = parseCitationHref(href)
        if (citationData) {
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => {
                if (e.button === 0 && !e.ctrlKey && !e.metaKey) {
                  e.preventDefault()
                  _citationClickHandler.current(
                    citationData.videoId,
                    citationData.startSeconds,
                    citationData.sourceId,
                    citationData.messageIdx,
                  )
                }
              }}
              className="text-[12px] font-medium text-accent-red bg-accent-red/10 hover:bg-accent-red/20 rounded-md px-1.5 py-0.5 mx-0.5 no-underline transition-colors box-decoration-clone break-words cursor-pointer"
            >
              {children}
            </a>
          )
        }
      }
      return <a href={href} target="_blank" rel="noopener noreferrer" className="text-accent-red underline underline-offset-2">{children}</a>
    },
    h1: ({ children }) => <h1 className="font-display text-[28px] tracking-tight mt-5 mb-3 first:mt-0 text-ink-900 dark:text-cream">{children}</h1>,
    h2: ({ children }) => <h2 className="font-display text-[22px] tracking-tight mt-4 mb-2 first:mt-0 text-ink-900 dark:text-cream">{children}</h2>,
    h3: ({ children }) => <h3 className="text-[16px] font-semibold tracking-tight mt-3 mb-1.5 first:mt-0 text-ink-900 dark:text-cream">{children}</h3>,
    p: ({ children }) => <p className="my-2.5 first:mt-0 last:mb-0 leading-[1.65]">{children}</p>,
    ul: ({ children }) => <ul className="list-disc pl-5 my-2.5 first:mt-0 last:mb-0 space-y-1.5">{children}</ul>,
    ol: ({ children }) => <ol className="list-decimal pl-5 my-2.5 first:mt-0 last:mb-0 space-y-1.5">{children}</ol>,
    li: ({ children }) => <li className="leading-[1.6]">{children}</li>,
    strong: ({ children }) => <strong className="font-semibold text-ink-900 dark:text-cream">{children}</strong>,
    em: ({ children }) => <em className="italic">{children}</em>,
    blockquote: ({ children }) => (
      <blockquote className="border-l-2 border-accent-red/40 pl-4 my-3 text-ink-500 dark:text-white/60 italic">{children}</blockquote>
    ),
    hr: () => <hr className="my-4 border-t border-black/[0.06] dark:border-white/10" />,
    code: ({ className, children }) => {
      const isBlock = typeof className === 'string' && className.startsWith('language-')
      if (isBlock && className === 'language-chart') {
        const raw = String(children).trim()
        try {
          const spec = JSON.parse(raw)
          return <ChartArtifact spec={spec} profile={profile} onCitationClick={(videoId, startSeconds) => _citationClickHandler.current(videoId, startSeconds)} />
        } catch {
          return <div className="text-[13px] text-ink-400 italic my-2">Generating chart...</div>
        }
      }
      if (isBlock) {
        return <code className="block bg-ink-50 dark:bg-ink-700 rounded-2xl p-4 my-3 text-[13px] font-mono overflow-x-auto border border-black/[0.04] dark:border-white/10">{children}</code>
      }
      return <code className="bg-ink-100 dark:bg-white/[0.08] rounded px-1.5 py-0.5 text-[13px] font-mono">{children}</code>
    },
    pre: ({ children }) => <pre className="my-2">{children}</pre>,
    table: ({ children }) => <div className="my-3 overflow-x-auto rounded-xl border border-black/[0.06] dark:border-white/10"><table className="w-full text-[13px] border-collapse">{children}</table></div>,
    th: ({ children }) => <th className="text-left font-semibold border-b border-black/[0.06] dark:border-white/10 px-3 py-2 bg-ink-50 dark:bg-ink-700">{children}</th>,
    td: ({ children }) => <td className="border-b border-black/[0.04] dark:border-white/[0.06] px-3 py-2 align-top">{children}</td>,
  }

  const sendMessage = async (text: string) => {
    if (!text.trim() || streaming || historyLoading) return
    const userMsg: ChatMessage = { role: 'user', content: text.trim() }
    const assistantMsg: ChatMessage = { role: 'assistant', content: '' }
    const nextMessages = [...messages, userMsg]
    setMessages([...nextMessages, assistantMsg])
    setInput('')
    setStreaming(true)
    setError(null)
    let streamError = false
    let assistantContent = ''
    let assistantSources: ChatSource[] = []
    try {
      const res = await apiStreamFetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel_id: channel.channel_id,
          chat_session_id: activeSessionIdRef.current,
          messages: nextMessages.map((m) => ({ role: m.role, content: m.content })),
          scope: buildScopePayload(scope),
        }),
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
      for await (const data of sseStream(res)) {
        if (!data) continue
        try {
          const frame = JSON.parse(data)
          if (frame.type === 'session' && frame.session && typeof frame.session.id === 'string') {
            const session = frame.session as ChatSessionSummary
            const previousSessionId = activeSessionIdRef.current
            activeSessionIdRef.current = session.id
            if (!previousSessionId) onSessionCreated?.(session)
            else onSessionUpdated?.(session)
          } else if (frame.type === 'sources') {
            assistantSources = normalizeSources(frame.sources)
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (!last || last.role !== 'assistant') return prev
              return [...prev.slice(0, -1), { ...last, sources: assistantSources }]
            })
          } else if (frame.type === 'delta' && typeof frame.text === 'string') {
            assistantContent += frame.text
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (!last || last.role !== 'assistant') return prev
              return [...prev.slice(0, -1), { ...last, content: last.content + frame.text }]
            })
            userScrolledUp.current = false
            scrollToBottom()
          } else if (frame.type === 'citation_warning' && Array.isArray(frame.unknown_source_ids)) {
            const unknownSourceIds = frame.unknown_source_ids.filter((value: unknown) => typeof value === 'string')
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (!last || last.role !== 'assistant') return prev
              return [...prev.slice(0, -1), { ...last, unknownSourceIds }]
            })
          } else if (frame.type === 'error') {
            streamError = true
            const errMsg = frame.message || 'Unknown error'
            setError(errMsg === 'scope_empty' ? 'No videos match the current filter.' : errMsg)
            break
          } else if (frame.type === 'done') {
            break
          }
        } catch { /* ignore */ }
      }
      if (!streamError && autoFocusRef.current && !focusedRef) {
        const finalMessages: ChatMessage[] = [
          ...nextMessages,
          { role: 'assistant', content: assistantContent, sources: assistantSources },
        ]
        const assistantIdx = finalMessages.length - 1
        const first = extractCitations(finalMessages, profile).find((ref) => ref.messageIdx === assistantIdx)
        if (first) setFocusedRef(first)
        autoFocusRef.current = false
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setStreaming(false)
      if (!completedRef.current && !streamError) {
        completedRef.current = true
        onComplete?.()
      }
    }
  }

  const handleSubmit = (e: React.FormEvent) => { e.preventDefault(); sendMessage(input) }
  const handleSuggested = (prompt: string) => { setInput(prompt); sendMessage(prompt) }
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  const retryLast = () => {
    if (messages.length === 0) return
    const lastUserIndex = messages.map((m) => m.role).lastIndexOf('user')
    if (lastUserIndex === -1) return
    const trimmed = messages.slice(0, lastUserIndex + 1)
    setMessages([...trimmed, { role: 'assistant', content: '' }])
    setStreaming(true)
    let assistantSources: ChatSource[] = []
    apiStreamFetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        channel_id: channel.channel_id,
        chat_session_id: activeSessionIdRef.current,
        messages: trimmed.map((m) => ({ role: m.role, content: m.content })),
        scope: buildScopePayload(scope),
      }),
    })
      .then(async (res) => {
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
        for await (const data of sseStream(res)) {
          if (!data) continue
          try {
            const frame = JSON.parse(data)
            if (frame.type === 'session' && frame.session && typeof frame.session.id === 'string') {
              const session = frame.session as ChatSessionSummary
              activeSessionIdRef.current = session.id
              onSessionUpdated?.(session)
            } else if (frame.type === 'sources') {
              assistantSources = normalizeSources(frame.sources)
              setMessages((prev) => {
                const last = prev[prev.length - 1]
                if (!last || last.role !== 'assistant') return prev
                return [...prev.slice(0, -1), { ...last, sources: assistantSources }]
              })
            } else if (frame.type === 'delta' && typeof frame.text === 'string') {
              setMessages((prev) => {
                const last = prev[prev.length - 1]
                if (!last || last.role !== 'assistant') return prev
                return [...prev.slice(0, -1), { ...last, content: last.content + frame.text }]
              })
              scrollToBottom()
            } else if (frame.type === 'citation_warning' && Array.isArray(frame.unknown_source_ids)) {
              const unknownSourceIds = frame.unknown_source_ids.filter((value: unknown) => typeof value === 'string')
              setMessages((prev) => {
                const last = prev[prev.length - 1]
                if (!last || last.role !== 'assistant') return prev
                return [...prev.slice(0, -1), { ...last, unknownSourceIds }]
              })
            } else if (frame.type === 'error') { setError(frame.message); break }
            else if (frame.type === 'done') { break }
          } catch { /* ignore */ }
        }
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setStreaming(false))
  }

  const hasMessages = messages.length > 0
  const activeFiltersCount =
    scope.themes.length + scope.tones.length + (scope.dateFrom ? 1 : 0) + (scope.dateTo ? 1 : 0)

  const openSource = (ref: CitedRef) => {
    setFocusedRef(ref)
    setSheetOpen(true)
  }

  return (
    <div className={`trace-chat ${embedded ? 'embedded' : 'standalone'}`}>
      {!embedded && (
        <header className="trace-chat-header">
          <button type="button" onClick={onBack} className="trace-chat-back">Profile</button>
          <button type="button" onClick={onBack} className="trace-chat-channel">
            {channel.avatar_url ? <img src={channel.avatar_url} alt="" /> : <span>{channel.channel_name.charAt(0).toUpperCase()}</span>}
            <b>{channel.channel_name}</b>
          </button>
        </header>
      )}

      <div ref={scrollRef} onScroll={handleScroll} className="trace-chat-scroll">
        <div className="trace-chat-inner">
          {historyLoading && (
            <div className="studio-loading">
              <span className="studio-spinner" />
              <span>Loading chat</span>
            </div>
          )}

          {!historyLoading && !hasMessages && (
            <motion.div
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35 }}
              className="trace-chat-empty"
            >
              <div className="trace-chat-empty-mark"><SparkIcon /></div>
              <div>
                <h2>Ask {channel.channel_name.split(' ')[0]} anything.</h2>
                <p>Every answer is cited back to the original video and timestamp. Start with a prompt or write your own.</p>
              </div>
              <div className="trace-suggestions">
                {SUGGESTED_PROMPTS.slice(0, 4).map((prompt) => (
                  <button key={prompt} type="button" className="trace-suggestion" onClick={() => handleSuggested(prompt)}>
                    <span><SparkIcon /></span>
                    {prompt}
                  </button>
                ))}
              </div>
            </motion.div>
          )}

          {messages.map((msg, idx) => {
            const refs = msg.role === 'assistant' ? messageSourceRefs(msg, idx, profile) : []
            return (
              <motion.div
                key={idx}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.24 }}
                className={`trace-msg ${msg.role === 'user' ? 'user' : 'assist'}`}
              >
                <div className="trace-msg-av">{msg.role === 'user' ? 'Y' : 'S'}</div>
                <div className="trace-msg-body">
                  <div className="trace-msg-meta">
                    <b>{msg.role === 'user' ? 'You' : 'Sourcemax'}</b>
                    <span>·</span>
                    <span>{msg.role === 'user' ? 'now' : `${refs.length} source${refs.length === 1 ? '' : 's'}`}</span>
                  </div>
                  {msg.role === 'user' ? (
                    <div className="trace-msg-text trace-user-bubble">{msg.content}</div>
                  ) : msg.content ? (
                    <>
                      <div className="trace-msg-text trace-markdown">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                          {renderCitationMarkdown(msg.content, msg.sources, idx)}
                        </ReactMarkdown>
                      </div>
                      <MessageSources refs={refs} channelName={channel.channel_name} onOpen={openSource} />
                    </>
                  ) : streaming && idx === messages.length - 1 ? (
                    <div className="trace-thinking" aria-label="Sourcemax is thinking">
                      <span />
                      <span />
                      <span />
                    </div>
                  ) : null}
                </div>
              </motion.div>
            )
          })}

          {error && (
            <div className="trace-msg assist">
              <div className="trace-msg-av">S</div>
              <div className="trace-error">
                <b>{error}</b>
                <button type="button" onClick={retryLast}>Retry</button>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="trace-composer-wrap">
        <AnimatePresence>
          {filtersOpen && (
            <motion.div
              initial={{ opacity: 0, y: 8, height: 0 }}
              animate={{ opacity: 1, y: 0, height: 'auto' }}
              exit={{ opacity: 0, y: 8, height: 0 }}
              transition={{ duration: 0.18 }}
              className="trace-scope-panel"
            >
              <ScopeChips profile={profile} scope={scope} onScopeChange={setScope} />
            </motion.div>
          )}
        </AnimatePresence>

        <form className="trace-composer" onSubmit={handleSubmit}>
          <textarea
            ref={textareaRef}
            className="trace-composer-input"
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={hasMessages ? 'Ask a follow-up...' : `Ask ${channel.channel_name.split(' ')[0]} anything...`}
            disabled={streaming || historyLoading}
          />
          <div className="trace-composer-tools">
            <button type="button" className="trace-tool" onClick={() => setFiltersOpen((value) => !value)}>
              <PaperclipIcon />
              Scope
            </button>
            <button type="button" className={`trace-tool ${filtersOpen || activeFiltersCount > 0 ? 'active' : ''}`} onClick={() => setFiltersOpen((value) => !value)}>
              <FilterIcon />
              Filters
              {activeFiltersCount > 0 && <span>{activeFiltersCount}</span>}
            </button>
            <div className="trace-composer-spacer" />
            <span className="trace-composer-hint"><kbd>Enter</kbd> send · <kbd>Shift</kbd><kbd>Enter</kbd> newline</span>
            <button type="submit" className="trace-send" disabled={streaming || historyLoading || !input.trim()} aria-label="Send message">
              {streaming ? <span className="trace-send-spinner" /> : <SendIcon />}
            </button>
          </div>
        </form>
      </div>

      <EvidenceSheet focusedRef={focusedRef} conversationRefs={conversationRefs} onSelectRef={setFocusedRef} channelName={channel.channel_name} isOpen={sheetOpen} onClose={() => setSheetOpen(false)} />
    </div>
  )
}
