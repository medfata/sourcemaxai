import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { ChannelMeta, PipelineCost } from '../types'
import { useSSE } from '../hooks/useSSE'
import ProgressStats from '../components/ProgressStats'
import LiveActivityPanel from '../components/LiveActivityPanel'
import type { ActivityItem } from '../components/LiveActivityPanel'

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
  const [cost, setCost] = useState<PipelineCost | null>(null)
  const [activityLog, setActivityLog] = useState<ActivityItem[]>([])
  const lastStatusRef = useRef<Record<string, string>>({})
  const [videoListOpen, setVideoListOpen] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [controlError, setControlError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

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
      setVideoListOpen(rows.length <= 30)
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
  const doneCount = videos.filter((v) => v.status === 'done').length
  const failedCount = videos.filter((v) => v.status === 'failed').length
  const progress = total > 0 ? (completed / total) * 100 : 0
  const runId = typeof state?.run_id === 'string' ? state.run_id : null
  const canRetryFailed = state?.status === 'failed' && failedCount > 0 && Boolean(runId) && !notice

  const activeItems: ActivityItem[] = useMemo(() =>
    videos
      .filter((v) => v.status === 'fetching')
      .map((v) => ({ videoId: v.id, title: v.title, status: 'fetching' as const, ts: 0 })),
    [videos]
  )

  useEffect(() => {
    const newEntries: ActivityItem[] = []
    for (const v of videos) {
      const prev = lastStatusRef.current[v.id]
      if (prev !== v.status) {
        lastStatusRef.current[v.id] = v.status
        if (terminalStatuses.has(v.status)) {
          newEntries.push({ videoId: v.id, title: v.title, status: v.status as ActivityItem['status'], ts: Date.now() })
        }
      }
    }
    if (newEntries.length > 0) {
      setActivityLog((prev) => [...newEntries, ...prev].slice(0, 8))
    }
  }, [videos])

  const handleComplete = useCallback(() => {
    onComplete()
  }, [onComplete])

  const handleCancel = async () => {
    await api.pipelineCancel(channel.channel_id)
    onBack()
  }

  const handleRetryFailed = async () => {
    if (!runId) {
      setControlError('No retryable run found')
      return
    }
    setRetrying(true)
    setControlError(null)
    setNotice(null)
    const res = await api.retryFailed(runId)
    setRetrying(false)
    if (!res.ok || !res.data) {
      setControlError(res.error || 'Retry failed')
      return
    }
    setNotice(`Retrying ${res.data.retried} failed video${res.data.retried === 1 ? '' : 's'}`)
  }

  const handleStartSummaries = async () => {
    setControlError(null)
    const res = await api.pipelineResume(channel.channel_id)
    if (!res.ok) {
      setControlError(res.error || 'Could not start summaries')
    }
  }

  const estimatedTranscriptMinutes = cost
    ? Math.ceil((cost.estimated_transcript_seconds || 0) / 60)
    : 0

  const summaryStatus = state?.stages?.summaries?.status

  useEffect(() => {
    if (!initialized) return
    if (summaryStatus === 'done' || state?.status === 'completed' || state?.status === 'failed') {
      handleComplete()
    }
  }, [summaryStatus, state?.status, initialized, handleComplete])

  if (!initialized) {
    return (
      <div className="flex items-center justify-center min-h-[100svh] bg-cream dark:bg-ink-900">
        <div className="flex items-center gap-3 text-ink-400">
          <span className="w-3 h-3 rounded-full border-2 border-current border-r-transparent animate-spin" />
          <span className="text-[14px]">Loading</span>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-[100svh] bg-cream dark:bg-ink-900 pb-32">
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

        {(controlError || notice || canRetryFailed) && (
          <div className="mb-4 px-4 py-3 bg-white dark:bg-ios-card-dark rounded-xl border border-black/[0.04] dark:border-white/[0.06]">
            {controlError && <p className="text-[13px] text-ios-red mb-3">{controlError}</p>}
            {notice && <p className="text-[13px] text-ios-green mb-3">{notice}</p>}
            {canRetryFailed && (
              <button
                onClick={handleRetryFailed}
                disabled={retrying}
                className="inline-flex items-center gap-2 px-5 h-[36px] rounded-xl bg-ios-blue text-white font-semibold text-[14px] active:scale-[0.98] disabled:opacity-50 transition"
              >
                {retrying && <span className="w-3 h-3 rounded-full border-2 border-current border-r-transparent animate-spin" />}
                Retry failed videos
              </button>
            )}
          </div>
        )}

        {/* Cost estimate + confirmation */}
        {cost && state?.status === 'awaiting_confirm_summaries' && (
          <div className="mb-4 px-4 py-3 bg-white dark:bg-ios-card-dark rounded-xl border border-black/[0.04] dark:border-white/[0.06]">
            <p className="text-[13px] text-ios-text-secondary mb-3">
              Estimated cost:{' '}
              <span className="font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
                ~${cost.estimated_cost_usd.toFixed(2)}
              </span>{' '}
              for {estimatedTranscriptMinutes.toLocaleString()} transcript minutes
              across {cost.video_count} videos
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
              for {estimatedTranscriptMinutes.toLocaleString()} transcript minutes
              across {cost.video_count} videos
            </p>
          </div>
        )}

        {/* Stats strip */}
        <ProgressStats
          total={total}
          done={doneCount}
          failed={failedCount}
          startedAt={state?.started_at}
        />

        {/* Progress bar */}
        <div className="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden my-4">
          <div
            className="h-full bg-ios-blue transition-all duration-500 rounded-full"
            style={{ width: `${progress}%` }}
          />
        </div>

        {/* Live activity */}
        <div className="mb-4">
          <LiveActivityPanel
            activeItems={activeItems}
            recentLog={activityLog}
            verb="Summarizing"
          />
        </div>

        {/* Collapsible video list */}
        <div>
          <button
            onClick={() => setVideoListOpen((o) => !o)}
            className="w-full flex items-center justify-between mb-2"
          >
            <span className="text-[15px] font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
              All videos ({total})
            </span>
            <span className="text-[13px] text-ios-text-secondary">
              {videoListOpen ? '▾' : '▸'}
            </span>
          </button>
          {videoListOpen && (
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
          )}
        </div>
      </div>
    </div>
  )
}
