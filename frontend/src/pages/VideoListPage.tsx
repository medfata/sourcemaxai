import { useCallback, useEffect, useRef, useState } from 'react'
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
        { label: 'Select all', onClick: () => selectVideoSubset(subset) },
        { label: 'Select none', onClick: () => deselectSubset(subset) },
        { label: 'Last 50', onClick: () => selectLast50(subset) },
        { label: 'Last year', onClick: () => selectLastYear(subset) },
      ]
    }
  } else if (tab === 'playlists' && playlists.length > 0) {
    quickActions = [
      { label: 'Select all playlists', onClick: selectAllPlaylists },
      { label: 'Select none', onClick: selectNonePlaylists },
    ]
  }

  const tabs = [
    { id: 'videos' as const, label: `Videos (${longVideos.length})` },
    { id: 'playlists' as const, label: `Playlists (${playlists.length})` },
    { id: 'shorts' as const, label: `Shorts (${shortVideos.length})` },
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
      <div className="max-w-5xl mx-auto px-4 pt-4 pb-1">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-center gap-3">
            {channel.avatar_url && (
              <img src={channel.avatar_url} alt="" className="w-10 h-10 rounded-full object-cover" />
            )}
            <div>
              <h2 className="text-[17px] font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
                {channel.channel_name}
              </h2>
              <p className="text-[13px] text-ios-text-secondary">
                {videos.length} videos
              </p>
            </div>
          </div>
          {quickActions.length > 0 && (
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
          )}
        </div>
      </div>

      {/* Tab bar */}
      <div className="max-w-5xl mx-auto px-4 py-3 sticky top-0 z-30 bg-ios-bg dark:bg-black">
        <div className="flex gap-1 p-1 bg-black/[0.05] dark:bg-white/[0.08] rounded-full w-fit">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-4 h-8 rounded-full text-[13px] font-medium transition-all ${
                tab === t.id
                  ? 'bg-ios-blue text-white shadow-sm'
                  : 'text-ios-text-secondary active:opacity-70'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content Grid */}
      <div className="max-w-5xl mx-auto px-4">
        {tab === 'videos' && (
          <>
            {longVideos.length === 0 ? (
              <div className="flex items-center justify-center py-20">
                <p className="text-[15px] text-ios-text-secondary">No long-form videos on this channel.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {longVideos.map((video) => {
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
                        <img src={video.thumbnail} alt={video.title} loading="lazy"
                          className="w-full h-full object-cover" />
                        <div className="absolute bottom-2 right-2 px-1.5 py-0.5 rounded-md bg-black/70 text-white text-[11px] font-medium">
                          {formatDuration(video.duration)}
                        </div>
                        <div className="absolute top-2 right-2">
                          <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center transition-colors ${
                            isSelected
                              ? 'bg-ios-blue border-ios-blue'
                              : 'bg-white/80 dark:bg-black/50 border-white dark:border-gray-400'
                          }`}>
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
            )}
          </>
        )}

        {tab === 'shorts' && (
          <>
            {shortVideos.length === 0 ? (
              <div className="flex items-center justify-center py-20">
                <p className="text-[15px] text-ios-text-secondary">No Shorts on this channel.</p>
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
                {shortVideos.map((video) => {
                  const isSelected = selectedIds.has(video.id)
                  return (
                    <div
                      key={video.id}
                      onClick={() => toggleVideo(video.id)}
                      className={`group cursor-pointer bg-white dark:bg-ios-card-dark rounded-xl border border-black/[0.04] dark:border-white/[0.06] overflow-hidden transition active:scale-[0.98] active:opacity-90 ${
                        isSelected ? 'ring-[3px] ring-ios-blue' : ''
                      }`}
                    >
                      <div className="relative aspect-[9/16]">
                        <img src={video.thumbnail} alt={video.title} loading="lazy"
                          className="w-full h-full object-cover" />
                        <div className="absolute bottom-2 right-2 px-1.5 py-0.5 rounded-md bg-black/70 text-white text-[11px] font-medium">
                          {formatDuration(video.duration)}
                        </div>
                        <div className="absolute top-2 right-2">
                          <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center transition-colors ${
                            isSelected
                              ? 'bg-ios-blue border-ios-blue'
                              : 'bg-white/80 dark:bg-black/50 border-white dark:border-gray-400'
                          }`}>
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
            )}
          </>
        )}

        {tab === 'playlists' && (
          <>
            {playlistsLoading ? (
              <div className="flex items-center justify-center py-20">
                <p className="text-[15px] text-ios-text-secondary">Loading playlists…</p>
              </div>
            ) : playlistsError ? (
              <div className="flex items-center justify-center py-20">
                <p className="text-[15px] text-ios-red">{playlistsError}</p>
              </div>
            ) : playlists.length === 0 ? (
              <div className="flex items-center justify-center py-20">
                <p className="text-[15px] text-ios-text-secondary">This channel has no public playlists.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {playlists.map((playlist) => {
                  const isSelected = selectedPlaylistIds.has(playlist.id)
                  return (
                    <div
                      key={playlist.id}
                      onClick={() => togglePlaylist(playlist.id)}
                      className={`group cursor-pointer bg-white dark:bg-ios-card-dark rounded-xl border border-black/[0.04] dark:border-white/[0.06] overflow-hidden transition active:scale-[0.98] active:opacity-90 ${
                        isSelected ? 'ring-[3px] ring-ios-blue' : ''
                      }`}
                    >
                      <div className="relative aspect-video bg-black/10 dark:bg-white/10 flex items-center justify-center">
                        {playlist.thumbnail ? (
                          <img src={playlist.thumbnail} alt={playlist.title} loading="lazy"
                            className="w-full h-full object-cover" />
                        ) : (
                          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
                            className="text-black/20 dark:text-white/20">
                            <rect x="3" y="3" width="18" height="18" rx="2" />
                            <line x1="9" y1="3" x2="9" y2="21" />
                          </svg>
                        )}
                        <div className="absolute top-2 right-2">
                          <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center transition-colors ${
                            isSelected
                              ? 'bg-ios-blue border-ios-blue'
                              : 'bg-white/80 dark:bg-black/50 border-white dark:border-gray-400'
                          }`}>
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
                          {playlist.title}
                        </h3>
                        <p className="mt-1 text-[12px] text-ios-text-secondary">
                          {playlist.video_count} videos
                        </p>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )}
      </div>

      {/* Sticky bottom bar */}
      <div className="fixed bottom-0 left-0 right-0 bg-white/90 dark:bg-ios-card-dark/90 backdrop-blur-md shadow-[0_-0.5px_0_rgba(0,0,0,0.15)] dark:shadow-[0_-0.5px_0_rgba(255,255,255,0.15)] z-40 pb-[max(env(safe-area-inset-bottom),12px)]">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="text-[15px] text-ios-text-secondary">
            <span className="font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
              V {selectedLongCount}
            </span>
            <span className="mx-1">·</span>
            <span className="font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
              S {selectedShortCount}
            </span>
            <span className="mx-1">·</span>
            <span className="font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
              P {selectedPlaylistCount}
            </span>
            <span className="mx-1">·</span>
            <span className="font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
              T {optimisticTotal}
            </span>
            <span className="ml-1">total</span>
            {saving && <span className="ml-2 text-[12px]">Saving…</span>}
            {resolvingPlaylists && <span className="ml-2 text-[12px]">Resolving playlists…</span>}
            {expansionError && (
              <div className="mt-1 text-[13px] text-ios-red leading-tight">{expansionError}</div>
            )}
          </div>
          <button
            onClick={handleRun}
            disabled={!hasSelection || resolvingPlaylists}
            className="px-6 h-[44px] rounded-2xl bg-ios-blue text-white font-semibold text-[15px] active:scale-[0.98] active:opacity-90 transition disabled:opacity-40 disabled:active:scale-100"
          >
            {resolvingPlaylists ? 'Resolving playlists…' : 'Run pipeline'}
          </button>
        </div>
        {(selectedIds.size > MAX_SELECTION || optimisticTotal > MAX_SELECTION) && (
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
