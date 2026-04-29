import { useEffect, useRef, useState } from 'react'

interface PipelineState {
  status: string
  current_stage?: string
  stages?: Record<
    string,
    {
      status: string
      total: number
      completed: number
      videos: Record<string, { status: string; title: string }>
    }
  >
  error?: string
  started_at?: string
}

interface UseSSEReturn {
  state: PipelineState | null
  connected: boolean
}

export function useSSE(channelId: string | null): UseSSEReturn {
  const [state, setState] = useState<PipelineState | null>(null)
  const [connected, setConnected] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!channelId) return

    const es = new EventSource(`/api/pipeline/stream?channel_id=${channelId}`)
    esRef.current = es

    es.addEventListener('initial_state', (e) => {
      setState(JSON.parse(e.data))
      setConnected(true)
    })

    es.addEventListener('video_update', (e) => {
      const data = JSON.parse(e.data)
      setState((prev) => {
        if (!prev) return prev
        const stageId = data.stage_id || 'transcripts'
        const stage = prev.stages?.[stageId]
        if (!stage) return prev
        const updated = {
          ...prev,
          stages: {
            ...prev.stages,
            [stageId]: { ...stage, ...data.stage },
          },
        }
        return updated
      })
    })

    es.addEventListener('stage_update', (e) => {
      setState(JSON.parse(e.data))
    })

    es.addEventListener('pipeline_complete', (e) => {
      setState(JSON.parse(e.data))
    })

    es.addEventListener('pipeline_error', (e) => {
      setState(JSON.parse(e.data))
    })

    es.onerror = () => {
      setConnected(false)
    }

    return () => {
      es.close()
      esRef.current = null
    }
  }, [channelId])

  return { state, connected }
}
