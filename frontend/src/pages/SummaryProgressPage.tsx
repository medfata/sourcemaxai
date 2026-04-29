import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { ChannelMeta } from '../types'
import { useSSE } from '../hooks/useSSE'

interface SummaryProgressPageProps {
  channel: ChannelMeta
  onComplete: () => void
  onBack: () => void
}

type VideoStatus = 'queued' | 'fetching' | 'done' | 'failed' | 'skipped'

interface VideoRow {
  id: string
  title: string
  thumbnail: string
  status: VideoStatus
}

interface CostEstimate {
  estimated_cost_usd: number
  video_count: number
  total_input_tokens: number
}

function StatusPill({ status }: { status: VideoStatus }) {
  const config: Record<VideoStatus, { bg: string; text: string; label: string; dot?: boolean }> = {
    queued: { bg: 'bg-gray-200 dark:bg-gray-700', text: 'text-gray-600 dark:text-gray-300', label: 'Queued' },
    fetching: { bg: 'bg-ios-blue/20', text: 'text-ios-blue', label: 'Summarizing…', dot: true },
    done: { bg: 'bg-ios-green/20', text: 'text-ios-green', label: 'Done' },
    failed: { bg: 'bg-ios-red/20', text: 'text-ios-red', label: 'Failed' },
    skipped: { bg: 'bg-gray-200 dark:bg-gray-700', text: 'text-gray-500 dark:text-gray-400', label: 'Skipped' },
  }
  const c = config[status]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium ${c.bg} ${c.text}`}>
      {c.dot && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
      {status === 'done' && (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      )}
      {status === 'failed' && (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <line x1="15" y1="9" x2="9" y2="15" />
          <line x1="9" y1="9" x2="15" y2="15" />
        </svg>
      )}
      {c.label}
    </span>
  )
}

const terminalStatuses = new Set(['done', 'skipped', 'failed'])

export default function SummaryProgressPage({ channel, onComplete, onBack }: SummaryProgressPageProps) {
  const { state } = useSSE(channel.channel_id)
  const [baseVideos, setBaseVideos] = useState<VideoRow[]>([])
  const [initialized, setInitialized] = useState(false)
  const [cost, setCost] = useState<CostEstimate | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      const [videosRes, selRes, costRes] = await Promise.all([
        api.videos(channel.channel_id),
        api.selection(channel.channel_id),
        api.pipelineCost(channel.channel_id),
      ])
      if (cancelled) return
      const vids = videosRes.data?.videos ?? []
      const selected = new Set(selRes.data?.video_ids ?? vids.map((v) => v.id))
      const rows: VideoRow[] = vids
        .filter((v) => selected.has(v.id))
        .map((v) => ({
          id: v.id,
          title: v.title,
          thumbnail: v.thumbnail,
          status: 'queued' as VideoStatus,
        }))
      setBaseVideos(rows)
      if (costRes.ok && costRes.data) {
        setCost(costRes.data)
      }
      setInitialized(true)
    }
    load()
    return () => {
      cancelled = true
    }
  }, [channel.channel_id])

  const videos = useMemo(() => {
    const backendVideos = state?.stages?.summaries?.videos ?? {}

    return baseVideos.map((v) => {
      const backend = backendVideos[v.id]
      if (backend) {
        const statusMap: Record<string, VideoStatus> = {
          fetching: 'fetching',
          done: 'done',
          skipped: 'skipped',
          failed: 'failed',
        }
        return { ...v, status: statusMap[backend.status] ?? v.status }
      }
      return v
    })
  }, [baseVideos, state])

  const total = videos.length
  const completed = videos.filter((v) => terminalStatuses.has(v.status)).length
  const progress = total > 0 ? (completed / total) * 100 : 0

  const handleComplete = useCallback(() => {
    onComplete()
  }, [onComplete])

  const handleCancel = async () => {
    await fetch('/api/pipeline/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel_id: channel.channel_id }),
    })
    onBack()
  }

  const handleStartSummaries = async () => {
    await fetch('/api/pipeline/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel_id: channel.channel_id }),
    })
  }

  useEffect(() => {
    if (!initialized) return
    const summaryStage = state?.stages?.summaries
    if (summaryStage?.status === 'done' || state?.status === 'completed' || state?.status === 'failed') {
      handleComplete()
    }
  }, [state?.stages?.summaries?.status, state?.status, initialized, handleComplete])

  if (!initialized) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100svh-64px)]">
        <div className="text-ios-text-secondary text-[17px]">Loading…</div>
      </div>
    )
  }

  return (
    <div className="pb-24">
      <div className="max-w-3xl mx-auto px-4 py-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            {channel.avatar_url && (
              <img src={channel.avatar_url} alt="" className="w-10 h-10 rounded-full object-cover" />
            )}
            <div>
              <h2 className="text-[17px] font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
                Summarizing videos
              </h2>
              <p className="text-[13px] text-ios-text-secondary">
                {completed} of {total} complete
              </p>
            </div>
          </div>
          <button
            onClick={handleCancel}
            className="px-4 h-[32px] rounded-full bg-black/[0.05] dark:bg-white/[0.08] text-[13px] text-ios-red font-medium active:opacity-70 transition"
          >
            Cancel
          </button>
        </div>

        {/* Cost estimate + confirmation */}
        {cost && state?.status === 'awaiting_confirm_summaries' && (
          <div className="mb-4 px-4 py-3 bg-white dark:bg-ios-card-dark rounded-xl border border-black/[0.04] dark:border-white/[0.06]">
            <p className="text-[13px] text-ios-text-secondary mb-3">
              Estimated cost:{' '}
              <span className="font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
                ~${cost.estimated_cost_usd.toFixed(2)}
              </span>{' '}
              for {cost.video_count} videos ({cost.total_input_tokens.toLocaleString()} input tokens)
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={handleStartSummaries}
                className="px-5 h-[36px] rounded-xl bg-ios-blue text-white font-semibold text-[14px] active:scale-[0.98] active:opacity-90 transition"
              >
                Start summaries (~${cost.estimated_cost_usd.toFixed(2)})
              </button>
              <button
                onClick={handleCancel}
                className="px-5 h-[36px] rounded-xl bg-black/[0.05] dark:bg-white/[0.08] text-ios-text-primary dark:text-ios-text-primary-dark font-medium text-[14px] active:opacity-70 transition"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Cost estimate (running) */}
        {cost && state?.status !== 'awaiting_confirm_summaries' && (
          <div className="mb-4 px-4 py-3 bg-white dark:bg-ios-card-dark rounded-xl border border-black/[0.04] dark:border-white/[0.06]">
            <p className="text-[13px] text-ios-text-secondary">
              Estimated cost:{' '}
              <span className="font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
                ~${cost.estimated_cost_usd.toFixed(2)}
              </span>{' '}
              for {cost.video_count} videos ({cost.total_input_tokens.toLocaleString()} input tokens)
            </p>
          </div>
        )}

        {/* Progress bar */}
        <div className="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden mb-6">
          <div
            className="h-full bg-ios-blue transition-all duration-500 rounded-full"
            style={{ width: `${progress}%` }}
          />
        </div>

        {/* Video rows */}
        <div className="bg-white dark:bg-ios-card-dark rounded-xl overflow-hidden">
          {videos.map((video, index) => (
            <div
              key={video.id}
              className={`flex items-center gap-3 p-3 ${
                index < videos.length - 1
                  ? 'border-b border-black/[0.04] dark:border-white/[0.06]'
                  : ''
              }`}
            >
              <img
                src={video.thumbnail}
                alt=""
                className="w-20 h-[45px] object-cover flex-shrink-0"
              />
              <div className="flex-1 min-w-0">
                <p className="text-[15px] font-medium text-ios-text-primary dark:text-ios-text-primary-dark truncate">
                  {video.title}
                </p>
                <p className="text-[11px] text-ios-text-secondary font-mono mt-0.5">{video.id}</p>
              </div>
              <StatusPill status={video.status} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
