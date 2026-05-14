import { useEffect, useRef, useState } from 'react'
import { api, apiStreamFetch } from '../api'
import type { PipelineState } from '../types'

interface UseSSEReturn {
  state: PipelineState | null
  connected: boolean
}

export function useSSE(channelId: string | null): UseSSEReturn {
  const [state, setState] = useState<PipelineState | null>(null)
  const [connected, setConnected] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const streamSeededRef = useRef(false)

  useEffect(() => {
    setState(null)
    setConnected(false)
    streamSeededRef.current = false
    if (!channelId) return

    const activeChannelId = channelId
    const abort = new AbortController()
    abortRef.current = abort

    async function loadInitialState() {
      try {
        const res = await api.pipelineState(activeChannelId)
        if (abort.signal.aborted || streamSeededRef.current) return
        if (res.ok && res.data) setState(res.data)
      } catch {
        // The stream still has its own initial_state event; this fetch is a fast refresh fallback.
      }
    }

    function applyEvent(event: string, rawData: string) {
      if (!rawData) return
      if (event === 'initial_state') {
        streamSeededRef.current = true
        setState(JSON.parse(rawData))
        setConnected(true)
        return
      }
      if (
        event === 'stage_update' ||
        event === 'pipeline_complete' ||
        event === 'pipeline_error' ||
        event === 'pipeline_cancelled'
      ) {
        setState(JSON.parse(rawData))
      }
    }

    async function readStream(response: Response) {
      if (!response.body) throw new Error('SSE response has no body')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      try {
        while (!abort.signal.aborted) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          let idx = buffer.indexOf('\n\n')
          while (idx !== -1) {
            const block = buffer.slice(0, idx)
            buffer = buffer.slice(idx + 2)
            let event = 'message'
            const dataLines: string[] = []
            for (const line of block.split('\n')) {
              if (line.startsWith('event:')) event = line.slice(6).trim()
              if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
            }
            applyEvent(event, dataLines.join('\n'))
            idx = buffer.indexOf('\n\n')
          }
        }
      } finally {
        reader.releaseLock()
      }
    }

    async function connect() {
      try {
        const response = await apiStreamFetch(
          `/api/pipeline/stream?channel_id=${encodeURIComponent(activeChannelId)}`,
          { signal: abort.signal },
        )
        if (!response.ok) throw new Error(`SSE HTTP ${response.status}`)
        await readStream(response)
      } catch {
        if (!abort.signal.aborted) setConnected(false)
      }
    }

    loadInitialState()
    connect()

    return () => {
      abort.abort()
      abortRef.current = null
      setConnected(false)
    }
  }, [channelId])

  return { state, connected }
}
