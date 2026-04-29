import { useEffect, useState } from 'react'
import { api } from '../api'
import { formatRelativeDate } from '../utils/date'
import type { ChannelMeta, Video } from '../types'

interface VideoListPageProps {
  channel: ChannelMeta
  onRunPipeline: () => void
}

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  return `${m}:${s.toString().padStart(2, '0')}`
}

const MAX_SELECTION = 300

export default function VideoListPage({ channel, onRunPipeline }: VideoListPageProps) {
  const [videos, setVideos] = useState<Video[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      const [videosRes, selRes] = await Promise.all([
        api.videos(channel.channel_id),
        api.selection(channel.channel_id),
      ])
      if (cancelled) return
      const vids = videosRes.data?.videos ?? []
      setVideos(vids)
      const ids = selRes.data?.video_ids ?? vids.map((v) => v.id)
      setSelectedIds(new Set(ids))
      setLoading(false)
    }
    load()
    return () => {
      cancelled = true
    }
  }, [channel.channel_id])

  const persistSelection = async (next: Set<string>) => {
    setSelectedIds(next)
    setSaving(true)
    await api.selectVideos(channel.channel_id, Array.from(next))
    setSaving(false)
  }

  const toggleVideo = (id: string) => {
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    persistSelection(next)
  }

  const selectAll = () => persistSelection(new Set(videos.map((v) => v.id).slice(0, MAX_SELECTION)))
  const selectNone = () => persistSelection(new Set())
  const selectLast50 = () => {
    const ids = videos.slice(-50).map((v) => v.id)
    persistSelection(new Set(ids))
  }
  const selectLastYear = () => {
    const oneYearAgo = new Date()
    oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1)
    const cutoff = `${oneYearAgo.getFullYear()}${String(oneYearAgo.getMonth() + 1).padStart(2, '0')}${String(oneYearAgo.getDate()).padStart(2, '0')}`
    const ids = videos.filter((v) => v.upload_date >= cutoff).map((v) => v.id).slice(0, MAX_SELECTION)
    persistSelection(new Set(ids))
  }

  const selectedCount = selectedIds.size
  const totalCount = videos.length

  const quickActions = [
    { label: 'Select all', onClick: selectAll },
    { label: 'Select none', onClick: selectNone },
    { label: 'Last 50', onClick: selectLast50 },
    { label: 'Last year', onClick: selectLastYear },
  ]

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100svh-64px)]">
        <div className="text-ios-text-secondary text-[17px]">Loading videos…</div>
      </div>
    )
  }

  return (
    <div className="pb-24">
      {/* Header */}
      <div className="max-w-5xl mx-auto px-4 py-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-center gap-3">
            {channel.avatar_url && (
              <img
                src={channel.avatar_url}
                alt=""
                className="w-10 h-10 rounded-full object-cover"
              />
            )}
            <div>
              <h2 className="text-[17px] font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
                {channel.channel_name}
              </h2>
              <p className="text-[13px] text-ios-text-secondary">
                {totalCount} videos
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {quickActions.map((action) => (
              <button
                key={action.label}
                onClick={action.onClick}
                className="px-3.5 h-8 rounded-full bg-black/[0.05] dark:bg-white/[0.08] text-[13px] text-ios-blue font-medium active:opacity-70 transition"
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Video Grid */}
      <div className="max-w-5xl mx-auto px-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {videos.map((video) => {
            const isSelected = selectedIds.has(video.id)
            return (
              <div
                key={video.id}
                onClick={() => toggleVideo(video.id)}
                className={`group cursor-pointer bg-white dark:bg-ios-card-dark rounded-xl border border-black/[0.04] dark:border-white/[0.06] overflow-hidden transition active:scale-[0.98] active:opacity-90 ${
                  isSelected ? 'ring-[3px] ring-ios-blue' : ''
                }`}
              >
                <div className="relative aspect-video">
                  <img
                    src={video.thumbnail}
                    alt={video.title}
                    loading="lazy"
                    className="w-full h-full object-cover"
                  />
                  <div className="absolute bottom-2 right-2 px-1.5 py-0.5 rounded-md bg-black/70 text-white text-[11px] font-medium">
                    {formatDuration(video.duration)}
                  </div>
                  {/* Checkbox */}
                  <div className="absolute top-2 right-2">
                    <div
                      className={`w-6 h-6 rounded-full border-2 flex items-center justify-center transition-colors ${
                        isSelected
                          ? 'bg-ios-blue border-ios-blue'
                          : 'bg-white/80 dark:bg-black/50 border-white dark:border-gray-400'
                      }`}
                    >
                      {isSelected && (
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      )}
                    </div>
                  </div>
                </div>
                <div className="p-3">
                  <h3 className="text-[15px] font-medium text-ios-text-primary dark:text-ios-text-primary-dark line-clamp-2 leading-snug">
                    {video.title}
                  </h3>
                  <p className="mt-1 text-[12px] text-ios-text-secondary">
                    {formatRelativeDate(video.upload_date)}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Sticky bottom bar */}
      <div className="fixed bottom-0 left-0 right-0 bg-white/90 dark:bg-ios-card-dark/90 backdrop-blur-md shadow-[0_-0.5px_0_rgba(0,0,0,0.15)] dark:shadow-[0_-0.5px_0_rgba(255,255,255,0.15)] z-40 pb-[max(env(safe-area-inset-bottom),12px)]">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="text-[15px] text-ios-text-secondary">
            <span className="font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
              {selectedCount}
            </span>{' '}
            of {totalCount} selected
            {saving && <span className="ml-2 text-[12px]">Saving…</span>}
          </div>
          <button
            onClick={onRunPipeline}
            disabled={selectedCount === 0}
            className="px-6 h-[44px] rounded-2xl bg-ios-blue text-white font-semibold text-[15px] active:scale-[0.98] active:opacity-90 transition disabled:opacity-40 disabled:active:scale-100"
          >
            Run pipeline
          </button>
        </div>
        {selectedCount > MAX_SELECTION && (
          <div className="max-w-5xl mx-auto px-4 pb-2">
            <p className="text-[13px] text-ios-yellow">
              {MAX_SELECTION}+ videos selected — pipeline may be slow and expensive
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
