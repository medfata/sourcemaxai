import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { api } from '../api'
import { formatRelativeDate } from '../utils/date'
import type { ChannelMeta, Playlist, Video } from '../types'

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

  const [tab, setTab] = useState<'videos' | 'playlists' | 'shorts'>('videos')
  const [playlists, setPlaylists] = useState<Playlist[]>([])
  const [selectedPlaylistIds, setSelectedPlaylistIds] = useState<Set<string>>(new Set())
  const [playlistsLoading, setPlaylistsLoading] = useState(false)
  const [resolvingPlaylists, setResolvingPlaylists] = useState(false)
  const [playlistsError, setPlaylistsError] = useState<string | null>(null)
  const [expansionError, setExpansionError] = useState<string | null>(null)
  const playlistsAttemptedRef = useRef(false)

  const longVideos = videos.filter((v) => !v.is_short)
  const shortVideos = videos.filter((v) => v.is_short)

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
    return () => { cancelled = true }
  }, [channel.channel_id])

  useEffect(() => {
    playlistsAttemptedRef.current = false
    setPlaylists([])
    setSelectedPlaylistIds(new Set())
    setPlaylistsError(null)
    setExpansionError(null)
  }, [channel.channel_id])

  useEffect(() => {
    const stored = localStorage.getItem(`cp_playlists_${channel.channel_id}`)
    if (stored) {
      try { setSelectedPlaylistIds(new Set(JSON.parse(stored))) } catch { /* ignore */ }
    }
  }, [channel.channel_id])

  useEffect(() => {
    localStorage.setItem(
      `cp_playlists_${channel.channel_id}`,
      JSON.stringify(Array.from(selectedPlaylistIds)),
    )
  }, [selectedPlaylistIds, channel.channel_id])

  useEffect(() => {
    if (tab === 'playlists' && !playlistsAttemptedRef.current) {
      playlistsAttemptedRef.current = true
      setPlaylistsLoading(true)
      setPlaylistsError(null)
      api.playlists(channel.channel_id).then((res) => {
        if (!res.ok) {
          setPlaylistsError(res.error ?? 'Failed to load playlists')
          setPlaylistsLoading(false)
          return
        }
        setPlaylists(res.data?.playlists ?? [])
        setPlaylistsLoading(false)
      })
    }
  }, [tab, channel.channel_id])

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

  const togglePlaylist = (id: string) => {
    setSelectedPlaylistIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const replaceSubsetSelection = (subset: Video[], newIds: Set<string>) => {
    const subsetIdSet = new Set(subset.map((v) => v.id))
    const preserved = Array.from(selectedIds).filter((id) => !subsetIdSet.has(id))
    persistSelection(new Set([...preserved, ...newIds]))
  }

  const selectVideoSubset = (subset: Video[]) => {
    const ids = subset.map((v) => v.id).slice(0, MAX_SELECTION)
    replaceSubsetSelection(subset, new Set(ids))
  }

  const deselectSubset = (subset: Video[]) => {
    replaceSubsetSelection(subset, new Set())
  }

  const selectLast50 = (subset: Video[]) => {
    const ids = subset.slice(-50).map((v) => v.id)
    replaceSubsetSelection(subset, new Set(ids))
  }

  const selectLastYear = (subset: Video[]) => {
    const oneYearAgo = new Date()
    oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1)
    const cutoff =
      `${oneYearAgo.getFullYear()}${String(oneYearAgo.getMonth() + 1).padStart(2, '0')}${String(oneYearAgo.getDate()).padStart(2, '0')}`
    const ids = subset.filter((v) => v.upload_date >= cutoff).map((v) => v.id).slice(0, MAX_SELECTION)
    replaceSubsetSelection(subset, new Set(ids))
  }

  const selectAllPlaylists = () => {
    setSelectedPlaylistIds(new Set(playlists.map((p) => p.id)))
  }

  const selectNonePlaylists = () => {
    setSelectedPlaylistIds(new Set())
  }

  const expandSelection = useCallback(async (): Promise<{ ids: string[]; error: string | null }> => {
    const expanded = new Set(selectedIds)
    for (const plId of selectedPlaylistIds) {
      const res = await api.playlistVideos(channel.channel_id, plId)
      if (!res.ok) {
        return { ids: [], error: `Failed to expand playlist "${plId}": ${res.error ?? 'Unknown error'}` }
      }
      for (const vid of res.data?.video_ids ?? []) expanded.add(vid)
    }
    return { ids: Array.from(expanded), error: null }
  }, [channel.channel_id, selectedIds, selectedPlaylistIds])

  const handleRun = async () => {
    setResolvingPlaylists(true)
    setExpansionError(null)
    const result = await expandSelection()
    if (result.error) {
      setExpansionError(result.error)
      setResolvingPlaylists(false)
      return
    }
    await api.selectVideos(channel.channel_id, result.ids)
    setResolvingPlaylists(false)
    onRunPipeline()
  }

  const selectedLongCount = longVideos.filter((v) => selectedIds.has(v.id)).length
  const selectedShortCount = shortVideos.filter((v) => selectedIds.has(v.id)).length
  const selectedPlaylistCount = selectedPlaylistIds.size
  const optimisticTotal =
    selectedIds.size +
    playlists
      .filter((p) => selectedPlaylistIds.has(p.id))
      .reduce((sum, p) => sum + p.video_count, 0)

  const hasSelection = selectedIds.size > 0 || selectedPlaylistIds.size > 0

  let quickActions: { label: string; onClick: () => void }[] = []
  if (tab === 'videos' || tab === 'shorts') {
    const subset = tab === 'videos' ? longVideos : shortVideos
    if (subset.length > 0) {
      quickActions = [
        { label: 'All', onClick: () => selectVideoSubset(subset) },
        { label: 'None', onClick: () => deselectSubset(subset) },
        { label: 'Last 50', onClick: () => selectLast50(subset) },
        { label: 'Last year', onClick: () => selectLastYear(subset) },
      ]
    }
  } else if (tab === 'playlists' && playlists.length > 0) {
    quickActions = [
      { label: 'All', onClick: selectAllPlaylists },
      { label: 'None', onClick: selectNonePlaylists },
    ]
  }

  const tabs = [
    { id: 'videos' as const, label: 'Videos', count: longVideos.length },
    { id: 'playlists' as const, label: 'Playlists', count: playlists.length },
    { id: 'shorts' as const, label: 'Shorts', count: shortVideos.length },
  ]

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[100svh] bg-cream dark:bg-ink-900">
        <div className="flex items-center gap-3 text-ink-400">
          <span className="w-3 h-3 rounded-full border-2 border-current border-r-transparent animate-spin" />
          <span className="text-[14px]">Loading library</span>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-[100svh] bg-cream dark:bg-ink-900 pb-32">
      {/* Editorial hero */}
      <div className="relative overflow-hidden border-b border-black/5 dark:border-white/10">
        <div aria-hidden className="absolute inset-0 bg-gradient-mesh opacity-60" />
        <div className="relative max-w-6xl mx-auto px-6 pt-12 pb-10">
          <div className="flex items-end justify-between gap-6 flex-wrap">
            <div className="flex items-center gap-5">
              {channel.avatar_url ? (
                <img src={channel.avatar_url} alt="" className="w-16 h-16 rounded-2xl object-cover ring-1 ring-black/5 dark:ring-white/10 shadow-soft" />
              ) : (
                <div className="w-16 h-16 rounded-2xl bg-ink-100 dark:bg-ink-700 flex items-center justify-center text-[24px] font-display text-ink-400">
                  {channel.channel_name.charAt(0).toUpperCase()}
                </div>
              )}
              <div>
                <span className="text-[11px] uppercase tracking-[0.18em] text-ink-400">Curating</span>
                <h1 className="font-display text-[40px] sm:text-[56px] leading-[0.98] tracking-tighter text-ink-900 dark:text-cream mt-1">
                  {channel.channel_name}
                </h1>
                <p className="mt-1 text-[14px] text-ink-500 dark:text-white/50">
                  <span className="font-mono">{videos.length}</span> videos available · select what to analyze
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs + quick actions */}
      <div className="sticky top-0 z-30 glass border-b border-black/5 dark:border-white/10">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-1">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`relative px-3 py-2 text-[13px] font-medium transition-colors ${
                  tab === t.id ? 'text-ink-900 dark:text-cream' : 'text-ink-400 hover:text-ink-700 dark:hover:text-white/70'
                }`}
              >
                <span>{t.label}</span>
                <span className={`ml-1.5 text-[11px] font-mono ${tab === t.id ? 'text-ink-400' : 'text-ink-300'}`}>{t.count}</span>
                {tab === t.id && (
                  <motion.span
                    layoutId="tab-underline"
                    className="absolute left-2 right-2 -bottom-px h-0.5 bg-ink-900 dark:bg-cream rounded-full"
                  />
                )}
              </button>
            ))}
          </div>

          {quickActions.length > 0 && (
            <div className="flex items-center gap-1.5">
              {quickActions.map((action) => (
                <button
                  key={action.label}
                  onClick={action.onClick}
                  className="px-3 h-8 rounded-full border border-black/[0.08] dark:border-white/10 text-[12px] text-ink-700 dark:text-white/70 hover:border-ink-900/30 hover:bg-white dark:hover:bg-white/5 transition-all"
                >
                  {action.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Grid */}
      <div className="max-w-6xl mx-auto px-6 pt-8">
        {tab === 'videos' && (
          longVideos.length === 0 ? (
            <EmptyState text="No long-form videos on this channel." />
          ) : (
            <VideoGrid videos={longVideos} aspect="aspect-video" cols="grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4" selectedIds={selectedIds} onToggle={toggleVideo} formatDuration={formatDuration} />
          )
        )}
        {tab === 'shorts' && (
          shortVideos.length === 0 ? (
            <EmptyState text="No Shorts on this channel." />
          ) : (
            <VideoGrid videos={shortVideos} aspect="aspect-[9/16]" cols="grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5" selectedIds={selectedIds} onToggle={toggleVideo} formatDuration={formatDuration} />
          )
        )}
        {tab === 'playlists' && (
          playlistsLoading ? (
            <EmptyState text="Loading playlists…" />
          ) : playlistsError ? (
            <EmptyState text={playlistsError} error />
          ) : playlists.length === 0 ? (
            <EmptyState text="This channel has no public playlists." />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {playlists.map((playlist, idx) => {
                const isSelected = selectedPlaylistIds.has(playlist.id)
                return (
                  <motion.div
                    key={playlist.id}
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3, delay: Math.min(idx * 0.02, 0.3) }}
                    onClick={() => togglePlaylist(playlist.id)}
                    className={`group cursor-pointer rounded-2xl bg-white dark:bg-ink-700 border overflow-hidden transition-all hover:-translate-y-0.5 ${
                      isSelected ? 'border-ink-900 dark:border-cream shadow-soft' : 'border-black/[0.06] dark:border-white/10 hover:border-ink-900/30 dark:hover:border-white/20'
                    }`}
                  >
                    <div className="relative aspect-video bg-ink-100 dark:bg-ink-600 flex items-center justify-center">
                      {playlist.thumbnail ? (
                        <img src={playlist.thumbnail} alt={playlist.title} loading="lazy" className="w-full h-full object-cover" />
                      ) : (
                        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-ink-300">
                          <rect x="3" y="3" width="18" height="18" rx="2" />
                          <line x1="9" y1="3" x2="9" y2="21" />
                        </svg>
                      )}
                      <SelectionBadge selected={isSelected} />
                    </div>
                    <div className="p-3.5">
                      <h3 className="text-[14px] font-medium text-ink-900 dark:text-cream line-clamp-2 leading-snug">{playlist.title}</h3>
                      <p className="mt-1 text-[12px] text-ink-400 font-mono">{playlist.video_count} videos</p>
                    </div>
                  </motion.div>
                )
              })}
            </div>
          )
        )}
      </div>

      {/* Floating action bar */}
      <motion.div
        initial={false}
        animate={{ y: 0 }}
        className="fixed bottom-4 sm:bottom-6 left-1/2 -translate-x-1/2 z-40 w-[min(720px,calc(100vw-2rem))]"
      >
        <div className="glass shadow-ring border border-black/5 dark:border-white/10 rounded-2xl px-4 py-3 flex items-center gap-4">
          <div className="flex-1 flex items-center gap-3 min-w-0">
            <div className="hidden sm:flex items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-ink-400">
              Selected
            </div>
            <div className="flex items-center gap-3 text-[12px] text-ink-500 dark:text-white/60 flex-wrap">
              <Stat label="V" value={selectedLongCount} />
              <Stat label="S" value={selectedShortCount} />
              <Stat label="P" value={selectedPlaylistCount} />
              <span className="hidden sm:inline-block w-px h-3.5 bg-ink-300/50" />
              <span className="font-mono text-ink-900 dark:text-cream font-semibold">{optimisticTotal}</span>
              <span className="text-ink-400">total</span>
              {saving && <span className="text-[11px] text-ink-400 italic">saving…</span>}
            </div>
          </div>
          <button
            onClick={handleRun}
            disabled={!hasSelection || resolvingPlaylists}
            className="h-11 px-5 rounded-xl bg-ink-900 dark:bg-cream text-cream dark:text-ink-900 font-medium text-[14px] hover:bg-ink-700 dark:hover:bg-white transition-all active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {resolvingPlaylists ? (
              <>
                <span className="w-3 h-3 rounded-full border-2 border-current border-r-transparent animate-spin" />
                Resolving
              </>
            ) : (
              <>
                Run pipeline
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="5" y1="12" x2="19" y2="12" />
                  <polyline points="12 5 19 12 12 19" />
                </svg>
              </>
            )}
          </button>
        </div>
        {(selectedIds.size > MAX_SELECTION || optimisticTotal > MAX_SELECTION) && (
          <p className="mt-2 text-center text-[12px] text-ios-yellow">
            {MAX_SELECTION}+ videos selected — pipeline may be slow and expensive
          </p>
        )}
        {expansionError && (
          <p className="mt-2 text-center text-[12px] text-ios-red">{expansionError}</p>
        )}
      </motion.div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className="text-[10px] font-mono uppercase text-ink-400">{label}</span>
      <span className="font-mono text-ink-900 dark:text-cream font-semibold">{value}</span>
    </span>
  )
}

function EmptyState({ text, error }: { text: string; error?: boolean }) {
  return (
    <div className="flex items-center justify-center py-24">
      <p className={`text-[14px] ${error ? 'text-ios-red' : 'text-ink-400'}`}>{text}</p>
    </div>
  )
}

function SelectionBadge({ selected }: { selected: boolean }) {
  return (
    <div className="absolute top-2.5 right-2.5">
      <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center transition-all ${
        selected ? 'bg-ink-900 dark:bg-cream border-ink-900 dark:border-cream scale-100' : 'bg-white/80 dark:bg-ink-900/50 border-white dark:border-ink-300 backdrop-blur-sm scale-90'
      }`}>
        {selected && (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" className="text-cream dark:text-ink-900">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        )}
      </div>
    </div>
  )
}

function VideoGrid({
  videos, aspect, cols, selectedIds, onToggle, formatDuration,
}: {
  videos: Video[]
  aspect: string
  cols: string
  selectedIds: Set<string>
  onToggle: (id: string) => void
  formatDuration: (s: number) => string
}) {
  return (
    <div className={`grid ${cols} gap-4`}>
      {videos.map((video, idx) => {
        const isSelected = selectedIds.has(video.id)
        return (
          <motion.div
            key={video.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: Math.min(idx * 0.012, 0.3) }}
            onClick={() => onToggle(video.id)}
            className={`group cursor-pointer rounded-2xl bg-white dark:bg-ink-700 border overflow-hidden transition-all hover:-translate-y-0.5 ${
              isSelected ? 'border-ink-900 dark:border-cream shadow-soft' : 'border-black/[0.06] dark:border-white/10 hover:border-ink-900/30 dark:hover:border-white/20'
            }`}
          >
            <div className={`relative ${aspect} bg-ink-100 dark:bg-ink-600`}>
              <img src={video.thumbnail} alt={video.title} loading="lazy" className="w-full h-full object-cover" />
              <div className="absolute bottom-2 right-2 px-2 py-0.5 rounded-md bg-black/75 text-white text-[11px] font-mono">
                {formatDuration(video.duration)}
              </div>
              <SelectionBadge selected={isSelected} />
            </div>
            <div className="p-3.5">
              <h3 className="text-[14px] font-medium text-ink-900 dark:text-cream line-clamp-2 leading-snug">{video.title}</h3>
              <p className="mt-1 text-[12px] text-ink-400">{formatRelativeDate(video.upload_date)}</p>
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}
