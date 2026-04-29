import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChannelMeta, ChatMessage } from '../types'

interface ChatPageProps {
  channel: ChannelMeta
  onBack: () => void
  onComplete?: () => void
}

const SUGGESTED_PROMPTS = [
  "What are this channel's main themes?",
  "How has the creator's thinking evolved over time?",
  "What does this person seem to believe most strongly?",
  "What topics keep coming up?",
  "Who or what does this channel reference most?",
]

function PaperPlaneIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
    >
      <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
    </svg>
  )
}

async function* sseStream(response: Response): AsyncGenerator<string, void, unknown> {
  if (!response.body) return
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      while (true) {
        const idx = buffer.indexOf("\n\n")
        if (idx === -1) break
        const chunk = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data: ")) {
            yield line.slice(6)
          }
        }
      }
    }
    // Flush remaining
    if (buffer.length) {
      for (const line of buffer.split("\n")) {
        if (line.startsWith("data: ")) {
          yield line.slice(6)
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export default function ChatPage({ channel, onBack, onComplete }: ChatPageProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [input, setInput] = useState("")
  const [error, setError] = useState<string | null>(null)
  const completedRef = useRef(false)

  const scrollRef = useRef<HTMLDivElement>(null)
  const userScrolledUp = useRef(false)

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    if (!userScrolledUp.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    userScrolledUp.current = !nearBottom
  }

  const sendMessage = async (text: string) => {
    if (!text.trim() || streaming) return
    const userMsg: ChatMessage = { role: "user", content: text.trim() }
    const assistantMsg: ChatMessage = { role: "assistant", content: "" }
    const nextMessages = [...messages, userMsg]
    setMessages([...nextMessages, assistantMsg])
    setInput("")
    setStreaming(true)
    setError(null)

    let streamError = false
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          channel_id: channel.channel_id,
          messages: nextMessages.map((m) => ({
            role: m.role,
            content: m.content,
          })),
        }),
      })

      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`)
      }

      let firstTokenReceived = false
      for await (const data of sseStream(res)) {
        if (!data) continue
        try {
          const frame = JSON.parse(data)
          if (frame.type === "delta" && typeof frame.text === "string") {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (!last || last.role !== "assistant") return prev
              return [
                ...prev.slice(0, -1),
                { ...last, content: last.content + frame.text },
              ]
            })
            if (!firstTokenReceived) {
              firstTokenReceived = true
              // Reset auto-scroll on first token
              userScrolledUp.current = false
            }
            scrollToBottom()
          } else if (frame.type === "error") {
            streamError = true
            setError(frame.message || "Unknown error")
            break
          } else if (frame.type === "done") {
            break
          }
        } catch {
          // ignore malformed JSON
        }
      }
    } catch (exc) {
      streamError = true
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setStreaming(false)
      if (!completedRef.current && !streamError) {
        completedRef.current = true
        onComplete?.()
      }
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    sendMessage(input)
  }

  const handleSuggested = (prompt: string) => {
    setInput(prompt)
    sendMessage(prompt)
  }

  const retryLast = () => {
    if (messages.length === 0) return
    // Remove the empty assistant message and resend the last user message
    const lastUserIndex = messages.map((m) => m.role).lastIndexOf("user")
    if (lastUserIndex === -1) return
    const trimmed = messages.slice(0, lastUserIndex + 1)
    setMessages(trimmed)
    setError(null)
    // Re-send by creating a new assistant slot and streaming
    const assistantMsg: ChatMessage = { role: "assistant", content: "" }
    setMessages([...trimmed, assistantMsg])
    setStreaming(true)

    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        channel_id: channel.channel_id,
        messages: trimmed.map((m) => ({
          role: m.role,
          content: m.content,
        })),
      }),
    })
      .then(async (res) => {
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
        for await (const data of sseStream(res)) {
          if (!data) continue
          try {
            const frame = JSON.parse(data)
            if (frame.type === "delta" && typeof frame.text === "string") {
              setMessages((prev) => {
                const last = prev[prev.length - 1]
                if (!last || last.role !== "assistant") return prev
                return [
                  ...prev.slice(0, -1),
                  { ...last, content: last.content + frame.text },
                ]
              })
              scrollToBottom()
            } else if (frame.type === "error") {
              setError(frame.message || "Unknown error")
              break
            } else if (frame.type === "done") {
              break
            }
          } catch {
            // ignore
          }
        }
      })
      .catch((exc) => {
        setError(exc instanceof Error ? exc.message : String(exc))
      })
      .finally(() => {
        setStreaming(false)
      })
  }

  return (
    <div className="flex flex-col h-[calc(100svh-64px)]">
      {/* Top header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-ios-separator dark:border-white/[0.06]">
        <button
          onClick={onBack}
          className="flex items-center gap-2 group"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className="w-5 h-5 text-ios-text-secondary group-hover:text-ios-blue transition-colors"
          >
            <path
              fillRule="evenodd"
              d="M12.79 5.23a.75.75 0 01-.02 1.06L8.832 10l3.938 3.71a.75.75 0 11-1.04 1.08l-4.5-4.25a.75.75 0 010-1.08l4.5-4.25a.75.75 0 011.06.02z"
              clipRule="evenodd"
            />
          </svg>
          <span className="text-[15px] text-ios-text-secondary group-hover:text-ios-blue transition-colors">
            Profile
          </span>
        </button>

        <button
          onClick={onBack}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity"
        >
          <span className="text-[15px] font-medium text-ios-text-primary dark:text-ios-text-primary-dark truncate max-w-[180px]">
            {channel.channel_name}
          </span>
          {channel.avatar_url ? (
            <img
              src={channel.avatar_url}
              alt=""
              className="w-8 h-8 rounded-full object-cover flex-shrink-0"
            />
          ) : (
            <div className="w-8 h-8 rounded-full bg-ios-bg dark:bg-gray-800 flex items-center justify-center text-[13px] font-bold text-ios-text-secondary flex-shrink-0">
              {channel.channel_name.charAt(0).toUpperCase()}
            </div>
          )}
        </button>
      </div>

      {/* Messages area */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-4 space-y-3"
      >
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex ${
              msg.role === "user" ? "justify-end" : "justify-start"
            }`}
          >
            <div
              className={`max-w-[80%] px-4 py-2.5 text-[15px] leading-relaxed ${
                  msg.role === "user"
                    ? "bg-ios-blue text-white rounded-3xl rounded-br-md whitespace-pre-wrap"
                    : "bg-ios-bubble dark:bg-gray-800 text-ios-text-primary dark:text-ios-text-primary-dark rounded-3xl rounded-bl-md"
              }`}
            >
              {msg.role === "assistant" ? (
                msg.content ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ node, ...props }) => (
                        <a {...props} target="_blank" rel="noopener noreferrer" className="text-ios-blue underline" />
                      ),
                    }}
                  >
                    {msg.content}
                  </ReactMarkdown>
                ) : streaming && idx === messages.length - 1 ? (
                  <span className="inline-flex gap-1">
                    <span className="w-1.5 h-1.5 bg-ios-text-secondary rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-1.5 h-1.5 bg-ios-text-secondary rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-1.5 h-1.5 bg-ios-text-secondary rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                  </span>
                ) : null
              ) : (
                msg.content
              )}
            </div>
          </div>
        ))}

        {error && messages.length > 0 && messages[messages.length - 1].role === "assistant" && (
          <div className="flex justify-start">
            <div className="max-w-[80%]">
              <p className="text-[13px] text-ios-red mb-1">{error}</p>
              <button
                onClick={retryLast}
                className="text-[13px] text-ios-blue font-medium hover:underline"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-4">
            <div className="text-ios-text-secondary text-[15px]">
              Ask anything about this channel
            </div>
          </div>
        )}
      </div>

      {/* Suggested prompts */}
      {messages.length === 0 && (
        <div className="px-4 pb-3">
          <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
            {SUGGESTED_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                onClick={() => handleSuggested(prompt)}
                className="flex-shrink-0 text-[13px] px-3 py-1.5 rounded-full bg-white dark:bg-ios-card-dark border border-ios-separator dark:border-white/[0.08] text-ios-text-primary dark:text-ios-text-primary-dark hover:bg-ios-blue/5 hover:border-ios-blue/30 transition-colors whitespace-nowrap"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input bar */}
      <div className="sticky bottom-0 bg-ios-bg/80 dark:bg-black/80 backdrop-blur-md border-t border-ios-separator dark:border-white/[0.06] px-4 py-3">
        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question…"
            disabled={streaming}
            className="flex-1 bg-white dark:bg-ios-card-dark rounded-2xl px-4 py-3 text-[15px] text-ios-text-primary dark:text-ios-text-primary-dark placeholder:text-ios-text-secondary outline-none focus:ring-2 focus:ring-ios-blue/30 transition-shadow disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={streaming || !input.trim()}
            className="mb-0.5 p-2.5 bg-ios-blue text-white rounded-full hover:bg-ios-blue/90 active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <PaperPlaneIcon className="w-5 h-5" />
          </button>
        </form>
      </div>
    </div>
  )
}
