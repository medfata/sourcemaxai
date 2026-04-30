import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChannelMeta, ChatMessage, Profile } from '../types'
import EvidencePane from '../components/EvidencePane'
import EvidenceSheet from '../components/EvidenceSheet'
import ChartArtifact from '../components/ChartArtifact'
import ScopeChips from '../components/ScopeChips'

const _citationClickHandler = { current: (_videoId: string, _startSeconds: number) => {} }
export function setCitationClickHandler(fn: (videoId: string, startSeconds: number) => void) {
  _citationClickHandler.current = fn
}

const isYouTubeCitationHref = (href: unknown): href is string =>
  typeof href === 'string' &&
  /(?:youtu\.be|youtube\.com)/.test(href) &&
  /[?&]t=/.test(href)

function parseCitationHref(href: string): { videoId: string; startSeconds: number } | null {
  const m = href.match(/(?:youtu\.be\/|v=)([\w-]{11}).*[?&]t=(\d+)s?/)
  if (!m) return null
  return { videoId: m[1], startSeconds: Number(m[2]) }
}

function extractCitations(messages: ChatMessage[], profile: Profile | null): any[] {
  interface CitedRef {
    videoId: string
    startSeconds: number
    messageIdx: number
    profileVideo?: any
    evidenceQuote?: string
  }
  if (!profile || !profile.videos) return []
  const citedRefs: CitedRef[] = []
  const videoMap = new Map(profile.videos.map((v: any) => [v.video_id, v]))
  const findEvidenceQuote = (videoId: string, startSeconds: number): string | null => {
    const profileAny = profile as any
    for (const claim of profileAny.key_claims || []) {
      for (const evidence of claim.evidence || []) {
        if (evidence.video_id === videoId && evidence.start_seconds === startSeconds) return evidence.quote
      }
    }
    for (const opinion of profileAny.notable_opinions || []) {
      for (const evidence of opinion.evidence || []) {
        if (evidence.video_id === videoId && evidence.start_seconds === startSeconds) return evidence.quote
      }
    }
    return null
  }
  const citationRegex = new RegExp(
    String.raw`\[↗\s*[^\]]*\]\((?:https?:\/\/(?:youtu\.be\/|youtube\.com\/watch\?v=)[\w-]{11}(?:[^\s\)]*?[?&]t=(\d+)s?)\)`,
    'g'
  )
  messages.forEach((message, msgIdx) => {
    if (message.role !== 'assistant' || !message.content) return
    let match
    while ((match = citationRegex.exec(message.content)) !== null) {
      const citationData = parseCitationHref(match[1])
      if (citationData) {
        const profileVideo = videoMap.get(citationData.videoId)
        const evidenceQuote = profileVideo ? findEvidenceQuote(citationData.videoId, citationData.startSeconds) : null
        citedRefs.push({
          videoId: citationData.videoId,
          startSeconds: citationData.startSeconds,
          messageIdx: msgIdx,
          profileVideo: profileVideo ?? undefined,
          evidenceQuote: evidenceQuote ?? undefined,
        })
      }
    }
  })
  return citedRefs
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
}

const SUGGESTED_PROMPTS = [
  "What are this channel's main themes?",
  "How has the creator's stance on AI evolved?",
  'What does this person seem to believe most strongly?',
  'What topics keep coming up?',
  'Who or what does this channel reference most?',
]

function PaperPlaneIcon({ className }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
    </svg>
  )
}

export default function ChatPage({ channel, onBack, onComplete, initialInput }: ChatPageProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [profile, setProfile] = useState<any>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [focusedRef, setFocusedRef] = useState<any>(null)
  const [conversationRefs, setConversationRefs] = useState<any[]>([])
  const [scope, setScope] = useState<{ themes: string[]; tones: string[]; dateFrom?: string; dateTo?: string }>({
    themes: [],
    tones: [],
  })
  const completedRef = useRef(false)
  const seedAppliedRef = useRef(false)
  const autoFocusRef = useRef(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const userScrolledUp = useRef(false)
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
    async function fetchProfile() {
      try {
        const res = await fetch(`/api/profile?channel_id=${channel.channel_id}`)
        if (res.ok) setProfile(await res.json())
      } catch (err) { console.error('Failed to fetch profile:', err) }
    }
    if (channel.channel_id) fetchProfile()
  }, [channel.channel_id])

  useEffect(() => {
    setConversationRefs(extractCitations(messages, profile))
  }, [messages, profile])

  useEffect(() => { scrollToBottom() }, [messages, scrollToBottom])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    userScrolledUp.current = el.scrollHeight - el.scrollTop - el.clientHeight >= 40
  }

  const handleCitationClick = useCallback((videoId: string, startSeconds: number) => {
    const ref = conversationRefs.find(
      (r: any) => r.videoId === videoId && r.startSeconds === startSeconds
    )
    if (ref) {
      setFocusedRef(ref)
      setSheetOpen(true)
    }
  }, [conversationRefs])

  useEffect(() => { setCitationClickHandler(handleCitationClick) }, [handleCitationClick])

  const markdownComponents: Components = {
    a: ({ href, children }) => {
      if (isYouTubeCitationHref(href)) {
        const citationData = parseCitationHref(href)
        if (citationData) {
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => {
                // Left click only (button === 0) and no modifier keys → in-app
                if (e.button === 0 && !e.ctrlKey && !e.metaKey) {
                  e.preventDefault()
                  _citationClickHandler.current(citationData.videoId, citationData.startSeconds)
                }
                // Middle-click, Cmd-click, Ctrl-click → let browser open in new tab (default)
              }}
              className="text-[12px] font-medium text-ios-blue bg-ios-blue/10 hover:bg-ios-blue/20 rounded-md px-1.5 py-0.5 mx-0.5 no-underline transition-colors box-decoration-clone break-words cursor-pointer"
            >
              {children}
            </a>
          )
        }
      }
      return <a href={href} target="_blank" rel="noopener noreferrer" className="text-ios-blue underline underline-offset-2">{children}</a>
    },
    h1: ({ children }) => <h1 className="text-[22px] font-bold tracking-tight mt-4 mb-2 first:mt-0">{children}</h1>,
    h2: ({ children }) => <h2 className="text-[19px] font-semibold tracking-tight mt-4 mb-2 first:mt-0">{children}</h2>,
    h3: ({ children }) => <h3 className="text-[17px] font-semibold tracking-tight mt-3 mb-1.5 first:mt-0">{children}</h3>,
    p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0 leading-[1.55]">{children}</p>,
    ul: ({ children }) => <ul className="list-disc pl-5 my-2 first:mt-0 last:mb-0 space-y-1">{children}</ul>,
    ol: ({ children }) => <ol className="list-decimal pl-5 my-2 first:mt-0 last:mb-0 space-y-1">{children}</ol>,
    li: ({ children }) => <li className="leading-[1.5]">{children}</li>,
    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
    em: ({ children }) => <em className="italic">{children}</em>,
    blockquote: ({ children }) => (
      <blockquote className="border-l-2 border-ios-blue/40 pl-3 my-2 text-ios-text-secondary italic">{children}</blockquote>
    ),
    hr: () => <hr className="my-3 border-t border-ios-separator/60" />,
    code: ({ className, children }) => {
      const isBlock = typeof className === 'string' && className.startsWith('language-')
      if (isBlock && className === 'language-chart') {
        const raw = String(children).trim()
        try {
          const spec = JSON.parse(raw)
          return <ChartArtifact spec={spec} profile={profile} onCitationClick={(videoId, startSeconds) => _citationClickHandler.current(videoId, startSeconds)} />
        } catch {
          return <div className="text-[13px] text-ios-text-secondary italic my-2">Generating chart...</div>
        }
      }
      if (isBlock) {
        return <code className="block bg-black/5 dark:bg-white/10 rounded-xl p-3 my-2 text-[13px] font-mono overflow-x-auto">{children}</code>
      }
      return <code className="bg-black/[0.06] dark:bg-white/[0.10] rounded px-1 py-0.5 text-[13px] font-mono">{children}</code>
    },
    pre: ({ children }) => <pre className="my-2">{children}</pre>,
    table: ({ children }) => <div className="my-2 overflow-x-auto"><table className="w-full text-[13px] border-collapse">{children}</table></div>,
    th: ({ children }) => <th className="text-left font-semibold border-b border-ios-separator px-2 py-1.5">{children}</th>,
    td: ({ children }) => <td className="border-b border-ios-separator/40 px-2 py-1.5 align-top">{children}</td>,
  }

  const sendMessage = async (text: string) => {
    if (!text.trim() || streaming) return
    const userMsg: ChatMessage = { role: 'user', content: text.trim() }
    const assistantMsg: ChatMessage = { role: 'assistant', content: '' }
    const nextMessages = [...messages, userMsg]
    setMessages([...nextMessages, assistantMsg])
    setInput('')
    setStreaming(true)
    setError(null)
    let streamError = false
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel_id: channel.channel_id,
          messages: nextMessages.map((m) => ({ role: m.role, content: m.content })),
          scope: scope.themes.length || scope.tones.length || scope.dateFrom ? scope : undefined,
        }),
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
      for await (const data of sseStream(res)) {
        if (!data) continue
        try {
          const frame = JSON.parse(data)
          if (frame.type === 'delta' && typeof frame.text === 'string') {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (!last || last.role !== 'assistant') return prev
              return [...prev.slice(0, -1), { ...last, content: last.content + frame.text }]
            })
            userScrolledUp.current = false
            scrollToBottom()
          } else if (frame.type === 'error') {
            streamError = true
            const errMsg = frame.message || 'Unknown error'
            if (errMsg === 'scope_empty') {
              setError('No videos match the current filter.')
            } else {
              setError(errMsg)
            }
            break
          } else if (frame.type === 'done') {
            break
          }
        } catch { /* ignore */ }
      }
      if (!streamError && autoFocusRef.current && !focusedRef) {
        let latestIdx = -1
        for (let i = nextMessages.length; i < messages.length; i++) {
          if (messages[i].role === 'assistant') latestIdx = i
        }
        if (latestIdx !== -1) {
          const latestMsg = messages[latestIdx]
          if (latestMsg && /youtu\.be|youtube\.com/.test(latestMsg.content)) {
            const first = extractCitations([latestMsg], profile)[0]
            if (first) setFocusedRef(first)
          }
        }
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

  const retryLast = () => {
    if (messages.length === 0) return
    const lastUserIndex = messages.map((m) => m.role).lastIndexOf('user')
    if (lastUserIndex === -1) return
    const trimmed = messages.slice(0, lastUserIndex + 1)
    setMessages([...trimmed, { role: 'assistant', content: '' }])
    setStreaming(true)
    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        channel_id: channel.channel_id,
        messages: trimmed.map((m) => ({ role: m.role, content: m.content })),
        scope: scope.themes.length || scope.tones.length || scope.dateFrom ? scope : undefined,
      }),
    })
      .then(async (res) => {
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
        for await (const data of sseStream(res)) {
          if (!data) continue
          try {
            const frame = JSON.parse(data)
            if (frame.type === 'delta' && typeof frame.text === 'string') {
              setMessages((prev) => {
                const last = prev[prev.length - 1]
                if (!last || last.role !== 'assistant') return prev
                return [...prev.slice(0, -1), { ...last, content: last.content + frame.text }]
              })
              scrollToBottom()
            } else if (frame.type === 'error') { setError(frame.message); break }
            else if (frame.type === 'done') { break }
          } catch { /* ignore */ }
        }
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setStreaming(false))
  }

  return (
    <div className="flex flex-col h-[calc(100svh-64px)]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-ios-separator dark:border-white/[0.06]">
        <button onClick={onBack} className="flex items-center gap-2 group">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5 text-ios-text-secondary group-hover:text-ios-blue transition-colors">
            <path fillRule="evenodd" d="M12.79 5.23a.75.75 0 01-.02 1.06L8.832 10l3.938 3.71a.75.75 0 11-1.04 1.08l-4.5-4.25a.75.75 0 010-1.08l4.5-4.25a.75.75 0 011.06.02z" clipRule="evenodd" />
          </svg>
          <span className="text-[15px] text-ios-text-secondary group-hover:text-ios-blue transition-colors">Profile</span>
        </button>
        <button onClick={onBack} className="flex items-center gap-2 hover:opacity-80 transition-opacity">
          <span className="text-[15px] font-medium text-ios-text-primary dark:text-ios-text-primary-dark truncate max-w-[180px]">{channel.channel_name}</span>
          {channel.avatar_url
            ? <img src={channel.avatar_url} alt="" className="w-8 h-8 rounded-full object-cover flex-shrink-0" />
            : <div className="w-8 h-8 rounded-full bg-ios-bg dark:bg-gray-800 flex items-center justify-center text-[13px] font-bold text-ios-text-secondary flex-shrink-0">{channel.channel_name.charAt(0).toUpperCase()}</div>
          }
        </button>
      </div>

      <div className="flex flex-1 min-h-0">
        <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
          {messages.map((msg, idx) => (
            <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={msg.role === 'user'
                ? 'max-w-[88%] sm:max-w-[680px] px-4 py-3 text-[15px] leading-[1.55] bg-ios-blue text-white rounded-3xl rounded-br-md whitespace-pre-wrap break-words'
                : 'max-w-[92%] sm:max-w-[720px] lg:max-w-[860px] xl:max-w-[960px] px-4 py-3 text-[15px] leading-[1.55] bg-ios-bubble dark:bg-gray-800 text-ios-text-primary dark:text-ios-text-primary-dark rounded-3xl rounded-bl-md break-words'}>
                {msg.role === 'assistant' ? (
                  msg.content ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                      {msg.content}
                    </ReactMarkdown>
                  ) : streaming && idx === messages.length - 1 ? (
                    <span className="inline-flex gap-1">
                      <span className="w-1.5 h-1.5 bg-ios-text-secondary rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="w-1.5 h-1.5 bg-ios-text-secondary rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="w-1.5 h-1.5 bg-ios-text-secondary rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </span>
                  ) : null
                ) : msg.content}
              </div>
            </div>
          ))}
          {error && (
            <div className="flex justify-start">
              <div className="max-w-[80%]">
                <p className="text-[13px] text-ios-red mb-1">{error}</p>
                <button onClick={retryLast} className="text-[13px] text-ios-blue font-medium hover:underline">Retry</button>
              </div>
            </div>
          )}
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center space-y-4">
              <div className="text-ios-text-secondary text-[15px]">Ask anything about this channel</div>
            </div>
          )}
        </div>
        <div className="hidden lg:block lg:w-[440px] border-l border-ios-separator/60">
          <EvidencePane focusedRef={focusedRef} conversationRefs={conversationRefs} onSelectRef={setFocusedRef} channelName={channel.channel_name} />
        </div>
      </div>

      <EvidenceSheet focusedRef={focusedRef} conversationRefs={conversationRefs} onSelectRef={setFocusedRef} channelName={channel.channel_name} isOpen={sheetOpen} onClose={() => setSheetOpen(false)} />

      {conversationRefs.length > 0 && (
        <button
          onClick={() => setSheetOpen(true)}
          className="lg:hidden fixed bottom-20 right-4 z-40 bg-ios-blue text-white text-[12px] font-medium px-3 py-1.5 rounded-full shadow-lg hover:bg-ios-blue/90 transition-colors"
        >
          View sources ({conversationRefs.length})
        </button>
      )}

      <ScopeChips profile={profile} scope={scope} onScopeChange={setScope} />

      {messages.length === 0 && (
        <div className="px-4 pb-3">
          <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
            {SUGGESTED_PROMPTS.map((prompt) => (
              <button key={prompt} onClick={() => handleSuggested(prompt)}
                className="flex-shrink-0 text-[13px] px-3 py-1.5 rounded-full bg-white dark:bg-ios-card-dark border border-ios-separator dark:border-white/[0.08] text-ios-text-primary dark:text-ios-text-primary-dark hover:bg-ios-blue/5 hover:border-ios-blue/30 transition-colors whitespace-nowrap">
                {prompt}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="sticky bottom-0 bg-ios-bg/80 dark:bg-black/80 backdrop-blur-md border-t border-ios-separator dark:border-white/[0.06] px-4 py-3">
        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask a question..." disabled={streaming}
            className="flex-1 bg-white dark:bg-ios-card-dark rounded-2xl px-4 py-3 text-[15px] text-ios-text-primary dark:text-ios-text-primary-dark placeholder:text-ios-text-secondary outline-none focus:ring-2 focus:ring-ios-blue/30 transition-shadow disabled:opacity-60" />
          <button type="submit" disabled={streaming || !input.trim()}
            className="mb-0.5 p-2.5 bg-ios-blue text-white rounded-full hover:bg-ios-blue/90 active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed">
            <PaperPlaneIcon className="w-5 h-5" />
          </button>
        </form>
      </div>
    </div>
  )
}