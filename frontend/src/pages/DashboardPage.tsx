import { useCallback, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { api } from '../api'
import type { ChannelSummary } from '../types'
import { downloadBlob } from '../utils/download'

interface DashboardPageProps {
  onOpen: (channel: ChannelSummary) => void
  onAddNew: () => void
  onDeleted?: (channelId: string) => void
  onEmpty?: () => void
}

type BusyAction = 'delete' | 'export' | 'refresh' | 'retry'

function formatRelative(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const diff = Date.now() - d.getTime()
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return d.toLocaleDateString()
}

function statusLabel(status: string | null): { text: string; tone: 'idle' | 'active' | 'done' | 'error' } {
  if (!status) return { text: 'No runs yet', tone: 'idle' }
  if (status === 'completed') return { text: 'Profile ready', tone: 'done' }
  if (status === 'failed') return { text: 'Run failed', tone: 'error' }
  if (status === 'cancelled') return { text: 'Cancelled', tone: 'idle' }
  if (status === 'awaiting_confirm_summaries') return { text: 'Awaiting confirmation', tone: 'active' }
  if (status === 'queued' || status === 'running' || status === 'cancel_requested') {
    return { text: 'Pipeline running', tone: 'active' }
  }
  return { text: status, tone: 'idle' }
}

export default function DashboardPage({ onOpen, onAddNew, onDeleted, onEmpty }: DashboardPageProps) {
  const [channels, setChannels] = useState<ChannelSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<{ id: string; action: BusyAction } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setError(null)
    const res = await api.channels()
    if (!res.ok || !res.data) {
      setError(res.error || 'Failed to load channels')
      setChannels([])
      return
    }
    setChannels(res.data.channels)
    if (res.data.channels.length === 0) {
      onEmpty?.()
    }
  }, [onEmpty])

  useEffect(() => {
    void Promise.resolve().then(reload)
  }, [reload])

  const handleRefresh = async (channel: ChannelSummary) => {
    setBusy({ id: channel.channel_id, action: 'refresh' })
    setNotice(null)
    const res = await api.refreshChannel(channel.channel_id)
    setBusy(null)
    if (!res.ok || !res.data) {
      setError(res.error || 'Refresh failed')
      return
    }
    setNotice(
      res.data.added > 0
        ? `${channel.channel_name}: +${res.data.added} new (total ${res.data.total})`
        : `${channel.channel_name}: no new videos (${res.data.total} total)`
    )
    reload()
  }

  const handleDelete = async (channelId: string) => {
    setBusy({ id: channelId, action: 'delete' })
    const res = await api.deleteChannel(channelId)
    setBusy(null)
    setConfirmDelete(null)
    if (!res.ok) {
      setError(res.error || 'Delete failed')
      return
    }
    onDeleted?.(channelId)
    reload()
  }

  const handleExport = async (channel: ChannelSummary) => {
    setBusy({ id: channel.channel_id, action: 'export' })
    setError(null)
    setNotice(null)
    const res = await api.fetchExportMarkdown(channel.channel_id)
    setBusy(null)
    if (!res.ok || !res.blob) {
      setError(res.error || 'Export failed')
      return
    }
    downloadBlob(res.blob, res.filename || `${channel.channel_id}.md`)
    setNotice(`${channel.channel_name}: Markdown export ready`)
  }

  const handleRetry = async (channel: ChannelSummary) => {
    setBusy({ id: channel.channel_id, action: 'retry' })
    setError(null)
    setNotice(null)
    const stateRes = await api.pipelineState(channel.channel_id)
    const runId = stateRes.data?.run_id
    if (!stateRes.ok || typeof runId !== 'string' || !runId) {
      setBusy(null)
      setError(stateRes.error || 'No retryable run found')
      return
    }
    const res = await api.retryFailed(runId)
    setBusy(null)
    if (!res.ok || !res.data) {
      setError(res.error || 'Retry failed')
      return
    }
    setNotice(`${channel.channel_name}: retried ${res.data.retried} failed video${res.data.retried === 1 ? '' : 's'}`)
    reload()
  }

  return (
    <div className="relative min-h-[100svh] overflow-hidden bg-cream dark:bg-ink-900">
      <div aria-hidden className="absolute inset-0 bg-gradient-mesh opacity-60 pointer-events-none" />
      <div aria-hidden className="absolute -top-40 -left-40 w-[480px] h-[480px] rounded-full bg-accent-red/15 blur-3xl" />

      <div className="relative max-w-5xl mx-auto px-6 pt-12 pb-20">
        <div className="flex items-center justify-between mb-10">
          <div>
            <span className="text-[11px] uppercase tracking-[0.22em] text-ink-400">Dashboard</span>
            <h1 className="mt-2 font-display text-[40px] sm:text-[56px] tracking-tighter text-ink-900 dark:text-cream">
              Your channels
            </h1>
          </div>
          <button
            onClick={onAddNew}
            className="h-11 px-5 rounded-xl bg-ink-900 dark:bg-cream text-cream dark:text-ink-900 text-[14px] font-medium hover:bg-ink-700 dark:hover:bg-white transition flex items-center gap-2"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            Add channel
          </button>
        </div>

        {error && (
          <div className="mb-4 px-4 py-3 rounded-xl border border-ios-red/20 bg-ios-red/10 text-[13px] text-ios-red flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="text-[12px] underline">Dismiss</button>
          </div>
        )}
        {notice && (
          <div className="mb-4 px-4 py-3 rounded-xl border border-ios-green/20 bg-ios-green/10 text-[13px] text-ios-green flex items-center justify-between">
            <span>{notice}</span>
            <button onClick={() => setNotice(null)} className="text-[12px] underline">Dismiss</button>
          </div>
        )}

        {channels === null && (
          <div className="flex items-center gap-3 text-ink-400 py-12">
            <span className="w-3 h-3 rounded-full border-2 border-current border-r-transparent animate-spin" />
            <span className="text-[14px]">Loading</span>
          </div>
        )}

        {channels && channels.length === 0 && !error && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-3xl border border-dashed border-ink-200 dark:border-white/10 px-8 py-20 text-center"
          >
            <p className="font-display text-[28px] text-ink-900 dark:text-cream">No channels yet</p>
            <p className="mt-2 text-[14px] text-ink-500 dark:text-white/60">Drop in a YouTube URL to start your first profile.</p>
            <button
              onClick={onAddNew}
              className="mt-6 inline-flex items-center gap-2 h-11 px-5 rounded-xl bg-ink-900 dark:bg-cream text-cream dark:text-ink-900 text-[14px] font-medium hover:bg-ink-700 dark:hover:bg-white transition"
            >
              Analyze a channel
            </button>
          </motion.div>
        )}

        {channels && channels.length > 0 && (
          <div className="grid grid-cols-1 gap-3">
            {channels.map((channel, i) => {
              const status = statusLabel(channel.latest_run_status)
              const toneClass =
                status.tone === 'done'
                  ? 'bg-ios-green/15 text-ios-green'
                  : status.tone === 'active'
                  ? 'bg-ios-blue/15 text-ios-blue'
                  : status.tone === 'error'
                  ? 'bg-ios-red/15 text-ios-red'
                  : 'bg-ink-100 dark:bg-white/5 text-ink-500 dark:text-white/60'
              const isBusy = busy?.id === channel.channel_id
              const isConfirming = confirmDelete === channel.channel_id
              return (
                <motion.div
                  key={channel.channel_id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.04 }}
                  className="group bg-white dark:bg-ink-700 rounded-2xl border border-black/[0.05] dark:border-white/10 p-4 sm:p-5 flex items-center gap-4"
                >
                  <button
                    onClick={() => onOpen(channel)}
                    className="flex items-center gap-4 flex-1 min-w-0 text-left"
                  >
                    {channel.avatar_url ? (
                      <img src={channel.avatar_url} alt="" className="w-12 h-12 rounded-full object-cover ring-1 ring-black/5 dark:ring-white/10 flex-shrink-0" />
                    ) : (
                      <span className="w-12 h-12 rounded-full bg-gradient-aurora flex-shrink-0" />
                    )}
                    <div className="min-w-0">
                      <p className="font-display text-[20px] tracking-tight text-ink-900 dark:text-cream truncate">
                        {channel.channel_name}
                      </p>
                      <div className="flex items-center gap-2 mt-1 text-[12px] text-ink-400 dark:text-white/50">
                        {channel.channel_handle && <span>@{channel.channel_handle}</span>}
                        {channel.channel_handle && <span className="w-1 h-1 rounded-full bg-ink-300" />}
                        <span className="font-mono">{channel.video_count} videos</span>
                        {channel.updated_at && (
                          <>
                            <span className="w-1 h-1 rounded-full bg-ink-300" />
                            <span>{formatRelative(channel.updated_at)}</span>
                          </>
                        )}
                      </div>
                    </div>
                  </button>

                  <span className={`hidden sm:inline-flex text-[11px] font-medium px-2.5 py-1 rounded-full ${toneClass}`}>
                    {status.text}
                  </span>

                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleRefresh(channel)}
                      disabled={isBusy}
                      title="Refresh catalog"
                      className="h-9 w-9 rounded-full hover:bg-ink-100 dark:hover:bg-white/5 disabled:opacity-40 flex items-center justify-center transition"
                    >
                      {busy?.id === channel.channel_id && busy.action === 'refresh' ? (
                        <span className="w-3.5 h-3.5 rounded-full border-2 border-current border-r-transparent animate-spin" />
                      ) : (
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <polyline points="23 4 23 10 17 10" />
                          <polyline points="1 20 1 14 7 14" />
                          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
                        </svg>
                      )}
                    </button>
                    {channel.latest_run_status === 'failed' && (
                      <button
                        onClick={() => handleRetry(channel)}
                        disabled={isBusy}
                        title="Retry failed videos"
                        className="h-9 w-9 rounded-full hover:bg-ios-blue/10 hover:text-ios-blue disabled:opacity-40 flex items-center justify-center transition"
                      >
                        {busy?.id === channel.channel_id && busy.action === 'retry' ? (
                          <span className="w-3.5 h-3.5 rounded-full border-2 border-current border-r-transparent animate-spin" />
                        ) : (
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M21 12a9 9 0 0 1-15.5 6.2" />
                            <path d="M3 12a9 9 0 0 1 15.5-6.2" />
                            <polyline points="18 2 18 6 22 6" />
                            <polyline points="6 22 6 18 2 18" />
                          </svg>
                        )}
                      </button>
                    )}
                    {channel.has_profile && (
                      <button
                        onClick={() => handleExport(channel)}
                        disabled={isBusy}
                        title="Export Markdown"
                        className="h-9 w-9 rounded-full hover:bg-accent-red/10 hover:text-accent-red disabled:opacity-40 flex items-center justify-center transition"
                      >
                        {busy?.id === channel.channel_id && busy.action === 'export' ? (
                          <span className="w-3.5 h-3.5 rounded-full border-2 border-current border-r-transparent animate-spin" />
                        ) : (
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                            <polyline points="7 10 12 15 17 10" />
                            <line x1="12" y1="15" x2="12" y2="3" />
                          </svg>
                        )}
                      </button>
                    )}
                    {isConfirming ? (
                      <div className="flex items-center gap-1.5 ml-1">
                        <button
                          onClick={() => handleDelete(channel.channel_id)}
                          disabled={isBusy}
                          className="h-8 px-3 rounded-full bg-ios-red text-white text-[12px] font-medium disabled:opacity-50"
                        >
                          Delete
                        </button>
                        <button
                          onClick={() => setConfirmDelete(null)}
                          className="h-8 px-3 rounded-full bg-ink-100 dark:bg-white/5 text-ink-700 dark:text-white/70 text-[12px] font-medium"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDelete(channel.channel_id)}
                        title="Delete channel"
                        className="h-9 w-9 rounded-full hover:bg-ios-red/10 hover:text-ios-red flex items-center justify-center transition"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                          <path d="M10 11v6" />
                          <path d="M14 11v6" />
                          <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
                        </svg>
                      </button>
                    )}
                  </div>
                </motion.div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
