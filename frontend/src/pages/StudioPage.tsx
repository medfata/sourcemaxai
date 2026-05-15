import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import type { Session } from '@supabase/supabase-js'

import { api } from '../api'
import { useSSE } from '../hooks/useSSE'
import type {
  ChannelMeta,
  ChannelSummary,
  ChatSessionSummary,
  PipelineCost,
  PipelineState,
  Playlist,
  Profile,
  ProfileVideo,
  Stage,
  StageStatus,
  Video,
} from '../types'
import { STAGES } from '../types'
import { formatMonthYear, formatRelativeDate, formatShortDate, formatTimestamp } from '../utils/date'
import { formatCompactNumber } from '../utils/number'
import { useConfirm } from '../components/ConfirmDialog'
import ChatPage from './ChatPage'
import './StudioPage.css'

type StudioView = 'no_channel' | 'group' | 'videos' | 'transcripts' | 'summaries' | 'profile_ready' | 'chat' | 'error'

type StudioSelection =
  | { kind: 'channel'; channelId: string }
  | { kind: 'group'; groupId: string }
  | null

interface LocalChannelGroup {
  id: string
  name: string
  memberChannelIds: string[]
  createdAt: string
  updatedAt: string
}

interface StudioPageProps {
  session: Session
  healthy: boolean | null
  initialUrl?: string
  autoSubmitInitialUrl?: boolean
  onInitialUrlConsumed?: () => void
  onSignOut: () => Promise<void>
}

interface IconProps {
  className?: string
}

const GROUPS_STORAGE_KEY = 'cp_channel_groups_v1'
const CHAT_PANEL_COLLAPSED_KEY = 'cp_chat_panel_collapsed'
const MAX_SELECTION = 300
const EXAMPLES = [
  { label: '@mkbhd', url: 'https://www.youtube.com/@mkbhd' },
  { label: '@veritasium', url: 'https://www.youtube.com/@veritasium' },
  { label: '@lexfridman', url: 'https://www.youtube.com/@lexfridman' },
  { label: '@thediaryofaceo', url: 'https://www.youtube.com/@thediaryofaceo' },
]

const Icons = {
  Search: ({ className }: IconProps) => (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  ),
  Plus: ({ className }: IconProps) => (
    <svg className={className} width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
      <path d="M12 5v14M5 12h14" />
    </svg>
  ),
  Check: ({ className }: IconProps) => (
    <svg className={className} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <path d="m5 12 5 5L20 7" />
    </svg>
  ),
  Refresh: ({ className }: IconProps) => (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12a9 9 0 1 1-3-6.7" />
      <path d="M21 4v5h-5" />
    </svg>
  ),
  Download: ({ className }: IconProps) => (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 4v12m0 0-4-4m4 4 4-4M4 20h16" />
    </svg>
  ),
  Trash: ({ className }: IconProps) => (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />
      <path d="M10 11v5M14 11v5" />
    </svg>
  ),
  More: ({ className }: IconProps) => (
    <svg className={className} width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
      <circle cx="5" cy="12" r="1.7" />
      <circle cx="12" cy="12" r="1.7" />
      <circle cx="19" cy="12" r="1.7" />
    </svg>
  ),
  Menu: ({ className }: IconProps) => (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  ),
  Close: ({ className }: IconProps) => (
    <svg className={className} width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  ),
  Arrow: ({ className }: IconProps) => (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  ),
  Warn: ({ className }: IconProps) => (
    <svg className={className} width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 9v4M12 17h.01M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0z" />
    </svg>
  ),
  Spark: ({ className }: IconProps) => (
    <svg className={className} width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" />
    </svg>
  ),
  Filter: ({ className }: IconProps) => (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 5h18l-7 9v6l-4-2v-4z" />
    </svg>
  ),
  Ext: ({ className }: IconProps) => (
    <svg className={className} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 4h6v6M10 14 20 4M19 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h6" />
    </svg>
  ),
  Play: ({ className }: IconProps) => (
    <svg className={className} width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  ),
  Evidence: ({ className }: IconProps) => (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="6" width="14" height="12" rx="1.5" />
      <path d="M17 9h4v9a2 2 0 0 1-2 2h-2" />
    </svg>
  ),
}

function readGroups(): LocalChannelGroup[] {
  try {
    const raw = localStorage.getItem(GROUPS_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.flatMap((group): LocalChannelGroup[] => {
      if (!group || typeof group !== 'object') return []
      const id = typeof group.id === 'string' ? group.id : ''
      const name = typeof group.name === 'string' ? group.name : ''
      const memberChannelIds = Array.isArray(group.memberChannelIds)
        ? group.memberChannelIds.filter((idValue: unknown) => typeof idValue === 'string')
        : []
      const createdAt = typeof group.createdAt === 'string' ? group.createdAt : new Date().toISOString()
      const updatedAt = typeof group.updatedAt === 'string' ? group.updatedAt : createdAt
      if (!id || !name || memberChannelIds.length < 2) return []
      return [{ id, name, memberChannelIds, createdAt, updatedAt }]
    })
  } catch {
    return []
  }
}

function writeGroups(groups: LocalChannelGroup[]) {
  localStorage.setItem(GROUPS_STORAGE_KEY, JSON.stringify(groups))
}

function persistChannelMeta(meta: ChannelMeta) {
  localStorage.setItem('cp_channel_id', meta.channel_id)
  localStorage.setItem('cp_channel_name', meta.channel_name)
  if (meta.channel_handle) localStorage.setItem('cp_channel_handle', meta.channel_handle)
  else localStorage.removeItem('cp_channel_handle')
  if (meta.avatar_url) localStorage.setItem('cp_channel_avatar', meta.avatar_url)
  else localStorage.removeItem('cp_channel_avatar')
}

function clearStoredChannelMeta() {
  localStorage.removeItem('cp_channel_id')
  localStorage.removeItem('cp_channel_name')
  localStorage.removeItem('cp_channel_handle')
  localStorage.removeItem('cp_channel_avatar')
}

function metaFromSummary(channel: ChannelSummary): ChannelMeta {
  return {
    channel_id: channel.channel_id,
    channel_name: channel.channel_name,
    channel_handle: channel.channel_handle,
    avatar_url: channel.avatar_url,
    subscriber_count: channel.subscriber_count,
    total_video_count: channel.total_video_count,
  }
}

function summaryFromMeta(meta: ChannelMeta): ChannelSummary {
  return {
    channel_id: meta.channel_id,
    channel_name: meta.channel_name,
    channel_handle: meta.channel_handle,
    avatar_url: meta.avatar_url,
    subscriber_count: meta.subscriber_count,
    total_video_count: meta.total_video_count,
    video_count: 0,
    has_profile: false,
    latest_run_status: null,
    updated_at: null,
  }
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('') || 'T'
}

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatRelativeIso(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const diff = Date.now() - date.getTime()
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return date.toLocaleDateString()
}

function statusForChannel(channel: ChannelSummary | null, pipeline: PipelineState | null): {
  label: string
  tone: 'ready' | 'run' | 'warn' | 'err' | 'idle'
} {
  const status = pipeline?.status ?? channel?.latest_run_status ?? null
  if (status === 'completed' || channel?.has_profile) return { label: 'Profile ready', tone: 'ready' }
  if (status === 'failed') return { label: 'Failed', tone: 'err' }
  if (status === 'awaiting_confirm_summaries') return { label: 'Awaiting confirmation', tone: 'warn' }
  if (status === 'queued' || status === 'running' || status === 'cancel_requested') return { label: 'Pipeline running', tone: 'run' }
  if (channel) return { label: channel.video_count > 0 ? 'Videos ready' : 'Idle', tone: channel.video_count > 0 ? 'warn' : 'idle' }
  return { label: 'No channel', tone: 'idle' }
}

function inferView(channel: ChannelSummary | null, pipeline: PipelineState | null): StudioView {
  if (!channel) return 'no_channel'
  const currentStage = pipeline?.current_stage
  const pipelineStatus = pipeline?.status
  const transcriptStatus = pipeline?.stages?.transcripts?.status
  const summaryStatus = pipeline?.stages?.summaries?.status
  const profileStatus = pipeline?.stages?.profile?.status

  if (pipelineStatus === 'failed') return 'error'
  if (pipelineStatus === 'running') {
    if (currentStage === 'transcripts' || currentStage === 'chunks') return 'transcripts'
    if (currentStage === 'summaries' || currentStage === 'profile') return 'summaries'
  }
  if (pipelineStatus === 'awaiting_confirm_summaries') return 'transcripts'
  if (pipelineStatus === 'completed' || profileStatus === 'done' || channel.has_profile) return 'profile_ready'
  if (summaryStatus === 'done') return 'summaries'
  if (transcriptStatus === 'done') return 'transcripts'
  return 'videos'
}

function stagesFromState(channel: ChannelSummary | null, pipeline: PipelineState | null, view: StudioView): Stage[] {
  if (!channel) return STAGES
  const transcriptStatus = pipeline?.stages?.transcripts?.status
  const summaryStatus = pipeline?.stages?.summaries?.status
  const profileStatus = pipeline?.stages?.profile?.status
  const currentStage = pipeline?.current_stage
  const pipelineStatus = pipeline?.status

  return STAGES.map((stage) => {
    if (stage.id === 'channel_input') return { ...stage, status: 'done' as StageStatus }
    if (stage.id === 'video_list') {
      const active = view === 'videos' || currentStage === 'videos'
      return { ...stage, status: active ? 'active' as StageStatus : 'done' as StageStatus }
    }
    if (stage.id === 'transcripts') {
      if (transcriptStatus === 'done' || summaryStatus === 'done' || profileStatus === 'done' || channel.has_profile) {
        return { ...stage, status: 'done' as StageStatus }
      }
      if (pipelineStatus === 'failed' && (currentStage === 'transcripts' || currentStage === 'chunks')) {
        return { ...stage, status: 'error' as StageStatus }
      }
      if ((currentStage === 'transcripts' || currentStage === 'chunks') && pipelineStatus === 'running') {
        return { ...stage, status: 'active' as StageStatus }
      }
      return { ...stage, status: 'pending' as StageStatus }
    }
    if (stage.id === 'summaries') {
      if (summaryStatus === 'done' || profileStatus === 'done' || channel.has_profile) return { ...stage, status: 'done' as StageStatus }
      if (pipelineStatus === 'failed' && (currentStage === 'summaries' || currentStage === 'profile')) return { ...stage, status: 'error' as StageStatus }
      if (pipelineStatus === 'awaiting_confirm_summaries' || (currentStage === 'summaries' && pipelineStatus === 'running')) {
        return { ...stage, status: 'active' as StageStatus }
      }
      return { ...stage, status: 'pending' as StageStatus }
    }
    if (stage.id === 'profile') {
      if (profileStatus === 'done' || channel.has_profile) return { ...stage, status: 'done' as StageStatus }
      if (currentStage === 'profile' && pipelineStatus === 'running') return { ...stage, status: 'active' as StageStatus }
      if (currentStage === 'profile' && pipelineStatus === 'failed') return { ...stage, status: 'error' as StageStatus }
      return { ...stage, status: 'pending' as StageStatus }
    }
    if (stage.id === 'chat') {
      if (view === 'chat') return { ...stage, status: 'active' as StageStatus }
      if (channel.has_profile || profileStatus === 'done') return { ...stage, status: 'pending' as StageStatus }
      return { ...stage, status: 'pending' as StageStatus }
    }
    return stage
  })
}

function stageMeta(
  stage: Stage,
  channel: ChannelSummary | null,
  pipeline: PipelineState | null,
  selectedTotal: number | null = null,
) {
  if (!channel) return ''
  if (stage.id === 'channel_input') return 'Linked'
  if (stage.id === 'video_list') {
    if (selectedTotal && selectedTotal > 0) return `${selectedTotal.toLocaleString()} selected`
    return 'Select videos'
  }
  if (stage.id === 'transcripts') {
    const state = pipeline?.stages?.transcripts
    if (state?.total) return `${state.completed ?? 0} of ${state.total}`
    return stage.status === 'done' ? 'Fetched' : 'Queued'
  }
  if (stage.id === 'summaries') {
    const state = pipeline?.stages?.summaries
    if (state?.total) return `${state.completed ?? 0} of ${state.total}`
    return stage.status === 'done' ? 'Synthesized' : 'Queued'
  }
  if (stage.id === 'profile') return stage.status === 'done' ? 'Built' : 'Queued'
  if (stage.id === 'chat') return stage.status === 'active' ? 'Active' : 'Ready'
  return ''
}

function uniqueId(prefix: string) {
  const random = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${random}`
}

function isClaim(value: unknown): value is { text: string; evidence: { start_seconds: number; quote: string }[] } {
  return Boolean(
    value &&
      typeof value === 'object' &&
      typeof (value as { text?: unknown }).text === 'string' &&
      Array.isArray((value as { evidence?: unknown }).evidence),
  )
}

function profileClaims(profile: Profile): { text: string; video: ProfileVideo; startSeconds: number }[] {
  const out: { text: string; video: ProfileVideo; startSeconds: number }[] = []
  for (const video of profile.videos) {
    for (const claim of [...video.notable_opinions, ...video.key_claims]) {
      if (!isClaim(claim) || claim.evidence.length === 0) continue
      out.push({ text: claim.text, video, startSeconds: claim.evidence[0].start_seconds })
      if (out.length >= 5) return out
    }
  }
  return out
}

export default function StudioPage({
  session,
  healthy,
  initialUrl = '',
  autoSubmitInitialUrl = false,
  onInitialUrlConsumed,
  onSignOut,
}: StudioPageProps) {
  const [channels, setChannels] = useState<ChannelSummary[]>([])
  const [channelsLoading, setChannelsLoading] = useState(true)
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const [selection, setSelection] = useState<StudioSelection>(null)
  const [groups, setGroups] = useState<LocalChannelGroup[]>(() => readGroups())
  const [view, setView] = useState<StudioView>('no_channel')
  const [channelInput, setChannelInput] = useState(initialUrl)
  const [resolving, setResolving] = useState(false)
  const [resolveError, setResolveError] = useState<string | null>(null)
  const [pipelineSnapshot, setPipelineSnapshot] = useState<PipelineState | null>(null)
  const [selectedTotal, setSelectedTotal] = useState<number>(0)
  const [chatSeed, setChatSeed] = useState<string | undefined>()
  const [notice, setNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const { confirm, dialog: confirmDialog } = useConfirm()
  const [refreshing, setRefreshing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [chatPanelCollapsed, setChatPanelCollapsed] = useState(
    () => localStorage.getItem(CHAT_PANEL_COLLAPSED_KEY) === '1',
  )
  const [chatSessions, setChatSessions] = useState<ChatSessionSummary[]>([])
  const [chatSessionsLoading, setChatSessionsLoading] = useState(false)
  const [chatSessionsError, setChatSessionsError] = useState<string | null>(null)
  const [activeChatSessionId, setActiveChatSessionId] = useState<string | undefined>()
  const autoSubmittedUrlRef = useRef<string | null>(null)

  const selectedChannelId = selection?.kind === 'channel' ? selection.channelId : null
  const { state: streamedPipelineState } = useSSE(selectedChannelId)
  const pipelineState = streamedPipelineState ?? pipelineSnapshot
  const selectedChannel = selectedChannelId ? channels.find((channel) => channel.channel_id === selectedChannelId) ?? null : null
  const selectedGroup = selection?.kind === 'group' ? groups.find((group) => group.id === selection.groupId) ?? null : null
  const selectedMeta = selectedChannel ? metaFromSummary(selectedChannel) : null
  const stages = useMemo(() => stagesFromState(selectedChannel, pipelineState, view), [selectedChannel, pipelineState, view])
  const status = statusForChannel(selectedChannel, pipelineState)
  const chatPanelVisible = Boolean(
    selectedChannel && (selectedChannel.has_profile || pipelineState?.stages?.profile?.status === 'done'),
  )

  const reloadChannels = useCallback(async (options?: { preserveSelection?: boolean }) => {
    setLibraryError(null)
    setChannelsLoading(true)
    const res = await api.channels()
    setChannelsLoading(false)
    if (!res.ok || !res.data) {
      setLibraryError(res.error || 'Failed to load channels')
      setChannels([])
      return []
    }
    const nextChannels = res.data.channels
    setChannels(nextChannels)
    setGroups((prev) => {
      const validIds = new Set(nextChannels.map((channel) => channel.channel_id))
      const cleaned = prev
        .map((group) => ({
          ...group,
          memberChannelIds: group.memberChannelIds.filter((id) => validIds.has(id)),
          updatedAt: new Date().toISOString(),
        }))
        .filter((group) => group.memberChannelIds.length >= 2)
      writeGroups(cleaned)
      return cleaned
    })

    if (!options?.preserveSelection) {
      const savedId = localStorage.getItem('cp_channel_id')
      const preferred = nextChannels.find((channel) => channel.channel_id === savedId) ?? nextChannels[0]
      if (preferred && !autoSubmitInitialUrl) {
        setSelection({ kind: 'channel', channelId: preferred.channel_id })
        setView(preferred.has_profile ? 'profile_ready' : 'videos')
      } else if (nextChannels.length === 0) {
        setSelection(null)
        setView('no_channel')
      }
    }
    return nextChannels
  }, [autoSubmitInitialUrl])

  const reloadChatSessions = useCallback(async (channelId: string) => {
    setChatSessionsError(null)
    setChatSessionsLoading(true)
    const res = await api.chatSessions(channelId)
    setChatSessionsLoading(false)
    if (!res.ok || !res.data) {
      setChatSessions([])
      setChatSessionsError(res.error || 'Failed to load chats')
      return []
    }
    const sessions = res.data.sessions
    setChatSessions(sessions)
    setActiveChatSessionId((current) => {
      if (current && sessions.some((chat) => chat.id === current)) return current
      return sessions[0]?.id
    })
    return sessions
  }, [])

  useEffect(() => {
    void reloadChannels()
  }, [reloadChannels])

  useEffect(() => {
    localStorage.setItem(CHAT_PANEL_COLLAPSED_KEY, chatPanelCollapsed ? '1' : '0')
  }, [chatPanelCollapsed])

  useEffect(() => {
    writeGroups(groups)
  }, [groups])

  useEffect(() => {
    if (initialUrl) {
      setChannelInput(initialUrl)
    }
  }, [initialUrl])

  useEffect(() => {
    if (!selectedChannelId || !chatPanelVisible) {
      setChatSessions([])
      setChatSessionsError(null)
      setActiveChatSessionId(undefined)
      return
    }
    void reloadChatSessions(selectedChannelId)
  }, [selectedChannelId, chatPanelVisible, reloadChatSessions])

  const selectChannel = useCallback((channel: ChannelSummary, nextView?: StudioView) => {
    setSelection({ kind: 'channel', channelId: channel.channel_id })
    persistChannelMeta(metaFromSummary(channel))
    setPipelineSnapshot(null)
    setSelectedTotal(0)
    setChatSeed(undefined)
    setActiveChatSessionId(undefined)
    setMobileSidebarOpen(false)
    setView(nextView ?? (channel.has_profile ? 'profile_ready' : 'videos'))
    api.selection(channel.channel_id).then((res) => {
      if (res.ok && res.data) setSelectedTotal(res.data.video_ids.length)
    })
    api.pipelineState(channel.channel_id).then((res) => {
      if (!res.ok || !res.data || res.data.status === 'idle') return
      const data = res.data
      setPipelineSnapshot(data)
      setView((current) => {
        const inferred = inferView(channel, data)
        if (current === 'chat' && inferred === 'profile_ready') return current
        return inferred
      })
    })
  }, [])

  const resolveChannel = useCallback(async (rawUrl: string) => {
    const nextUrl = rawUrl.trim()
    setResolveError(null)
    setActionError(null)
    if (!nextUrl) {
      setResolveError('Enter a YouTube URL or handle.')
      return
    }

    setResolving(true)
    const res = await api.channel(nextUrl)
    setResolving(false)
    if (!res.ok || !res.data) {
      setResolveError(res.error || 'Could not resolve channel.')
      return
    }

    const meta = res.data
    persistChannelMeta(meta)
    onInitialUrlConsumed?.()
    setChannelInput('')
    setSelection({ kind: 'channel', channelId: meta.channel_id })
    setPipelineSnapshot(null)
    setSelectedTotal(0)
    setChatSeed(undefined)
    setActiveChatSessionId(undefined)
    setView('videos')
    setChannels((prev) => {
      if (prev.some((channel) => channel.channel_id === meta.channel_id)) {
        return prev.map((channel) => channel.channel_id === meta.channel_id ? { ...channel, ...summaryFromMeta(meta) } : channel)
      }
      return [summaryFromMeta(meta), ...prev]
    })
    void reloadChannels({ preserveSelection: true })
  }, [onInitialUrlConsumed, reloadChannels])

  useEffect(() => {
    const nextUrl = initialUrl.trim()
    if (!autoSubmitInitialUrl || !nextUrl || autoSubmittedUrlRef.current === nextUrl) return
    autoSubmittedUrlRef.current = nextUrl
    setSelection(null)
    setView('no_channel')
    void resolveChannel(nextUrl)
  }, [autoSubmitInitialUrl, initialUrl, resolveChannel])

  useEffect(() => {
    if (!selectedChannel) return
    if (!streamedPipelineState) return
    const inferred = inferView(selectedChannel, streamedPipelineState)
    if (inferred === 'transcripts' || inferred === 'summaries' || inferred === 'error') {
      setView(inferred)
      return
    }
    if (inferred === 'profile_ready') {
      setView((current) => current === 'chat' ? current : 'profile_ready')
    }
  }, [selectedChannel, streamedPipelineState])

  const handleNewChannel = () => {
    clearStoredChannelMeta()
    setSelection(null)
    setPipelineSnapshot(null)
    setSelectedTotal(0)
    setChatSeed(undefined)
    setActiveChatSessionId(undefined)
    setResolveError(null)
    setActionError(null)
    setView('no_channel')
    setMobileSidebarOpen(false)
  }

  const handleSelectGroup = (group: LocalChannelGroup) => {
    setSelection({ kind: 'group', groupId: group.id })
    setPipelineSnapshot(null)
    setChatSeed(undefined)
    setActiveChatSessionId(undefined)
    setView('group')
    setMobileSidebarOpen(false)
  }

  const handleCreateGroup = (name: string, memberChannelIds: string[]) => {
    const now = new Date().toISOString()
    const group: LocalChannelGroup = {
      id: uniqueId('group'),
      name: name.trim(),
      memberChannelIds,
      createdAt: now,
      updatedAt: now,
    }
    setGroups((prev) => [group, ...prev])
    setSelection({ kind: 'group', groupId: group.id })
    setView('group')
  }

  const handleDeleteGroup = (groupId: string) => {
    setGroups((prev) => prev.filter((group) => group.id !== groupId))
    if (selection?.kind === 'group' && selection.groupId === groupId) {
      setSelection(null)
      setView('no_channel')
    }
  }

  const handleRefreshChannel = async () => {
    if (!selectedChannel) return
    setRefreshing(true)
    setActionError(null)
    setNotice(null)
    const res = await api.refreshChannel(selectedChannel.channel_id)
    setRefreshing(false)
    if (!res.ok || !res.data) {
      setActionError(res.error || 'Refresh failed')
      return
    }
    setNotice(
      res.data.added > 0
        ? `${selectedChannel.channel_name}: +${res.data.added} new videos`
        : `${selectedChannel.channel_name}: no new videos`,
    )
    await reloadChannels({ preserveSelection: true })
  }

  const handleExportChannel = async () => {
    if (!selectedChannel) return
    setExporting(true)
    setActionError(null)
    setNotice(null)
    const res = await api.fetchExportMarkdown(selectedChannel.channel_id)
    setExporting(false)
    if (!res.ok || !res.blob) {
      setActionError(res.error || 'Export failed')
      return
    }
    const filename = res.filename || `${selectedChannel.channel_id}.md`
    const url = window.URL.createObjectURL(res.blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    window.URL.revokeObjectURL(url)
    setNotice(`${selectedChannel.channel_name}: Markdown export ready`)
  }

  const handleDeleteChannel = async () => {
    if (!selectedChannel) return
    setActionError(null)
    const ok = await confirm({
      title: 'Delete channel',
      message: `Delete ${selectedChannel.channel_name}? This removes it from your library.`,
      confirmLabel: 'Delete',
      variant: 'danger',
      action: async () => {
        const res = await api.deleteChannel(selectedChannel.channel_id)
        if (!res.ok) throw new Error(res.error || 'Delete failed')
      },
    })
    if (!ok) return
    setGroups((prev) => {
      const cleaned = prev
        .map((group) => ({
          ...group,
          memberChannelIds: group.memberChannelIds.filter((id) => id !== selectedChannel.channel_id),
          updatedAt: new Date().toISOString(),
        }))
        .filter((group) => group.memberChannelIds.length >= 2)
      writeGroups(cleaned)
      return cleaned
    })
    clearStoredChannelMeta()
    setSelection(null)
    setView('no_channel')
    await reloadChannels({ preserveSelection: true })
  }

  const handleRunPipeline = () => {
    if (!selectedChannel) return
    setActionError(null)
    setView('transcripts')
  }

  const handleStepClick = (stage: Stage) => {
    if (!selectedChannel) return
    if (stage.id === 'channel_input') {
      handleNewChannel()
    } else if (stage.id === 'video_list') {
      setView('videos')
    } else if (stage.id === 'transcripts') {
      setView('transcripts')
    } else if (stage.id === 'summaries') {
      setView('summaries')
    } else if (stage.id === 'profile' && (selectedChannel.has_profile || pipelineState?.stages?.profile?.status === 'done')) {
      setView('profile_ready')
    } else if (stage.id === 'chat' && (selectedChannel.has_profile || pipelineState?.stages?.profile?.status === 'done')) {
      setView('chat')
    }
  }

  const handleStartChat = (seed?: string) => {
    setChatSeed(seed)
    if (!seed && !activeChatSessionId && chatSessions[0]) {
      setActiveChatSessionId(chatSessions[0].id)
    }
    if (seed) {
      setActiveChatSessionId(undefined)
    }
    setView('chat')
  }

  const handleNewChatSession = async () => {
    if (!selectedChannel) return
    setActionError(null)
    const res = await api.createChatSession(selectedChannel.channel_id)
    if (!res.ok || !res.data) {
      setActionError(res.error || 'Could not create chat')
      return
    }
    const session = res.data
    setChatSessions((prev) => [session, ...prev.filter((chat) => chat.id !== session.id)])
    setActiveChatSessionId(session.id)
    setChatSeed(undefined)
    setView('chat')
  }

  const handleSelectChatSession = (sessionId: string) => {
    setActiveChatSessionId(sessionId)
    setChatSeed(undefined)
    setView('chat')
  }

  const handleChatSessionCreated = useCallback((session: ChatSessionSummary) => {
    setChatSessions((prev) => [session, ...prev.filter((chat) => chat.id !== session.id)])
    setActiveChatSessionId(session.id)
  }, [])

  const handleChatSessionUpdated = useCallback((session: ChatSessionSummary) => {
    setChatSessions((prev) => {
      const next = [session, ...prev.filter((chat) => chat.id !== session.id)]
      return next.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    })
    setActiveChatSessionId(session.id)
  }, [])

  const handleRenameChatSession = async (session: ChatSessionSummary) => {
    if (!selectedChannel) return
    const title = window.prompt('Rename chat', session.title)
    if (title === null || title.trim() === session.title) return
    const res = await api.renameChatSession(selectedChannel.channel_id, session.id, title.trim())
    if (!res.ok || !res.data) {
      setActionError(res.error || 'Could not rename chat')
      return
    }
    handleChatSessionUpdated(res.data)
  }

  const handleDeleteChatSession = async (session: ChatSessionSummary) => {
    if (!selectedChannel) return
    const ok = await confirm({
      title: 'Delete chat',
      message: `Delete "${session.title}"? This conversation will be removed.`,
      confirmLabel: 'Delete',
      variant: 'danger',
      action: async () => {
        const res = await api.deleteChatSession(selectedChannel.channel_id, session.id)
        if (!res.ok) throw new Error(res.error || 'Could not delete chat')
      },
    })
    if (!ok) return
    setChatSessions((prev) => {
      const next = prev.filter((chat) => chat.id !== session.id)
      if (activeChatSessionId === session.id) {
        const fallback = next[0]?.id
        setActiveChatSessionId(fallback)
        if (!fallback && view === 'chat') setView('profile_ready')
      }
      return next
    })
  }

  const shellClass = [
    'studio-page',
    mobileSidebarOpen ? 'sidebar-open' : '',
    chatPanelVisible ? 'has-chat-panel' : '',
    chatPanelCollapsed ? 'chat-panel-collapsed' : '',
  ].filter(Boolean).join(' ')

  return (
    <div className={shellClass}>
      <button type="button" className="studio-mobile-menu" onClick={() => setMobileSidebarOpen(true)} aria-label="Open channels">
        <Icons.Menu />
      </button>

      {mobileSidebarOpen && <button type="button" className="studio-mobile-backdrop" onClick={() => setMobileSidebarOpen(false)} aria-label="Close channels" />}

      <StudioSidebar
        session={session}
        channels={channels}
        groups={groups}
        loading={channelsLoading}
        error={libraryError}
        selection={selection}
        selectedChannelId={selectedChannelId}
        selectedGroupId={selectedGroup?.id ?? null}
        selectedPipeline={pipelineState}
        onSelectChannel={selectChannel}
        onSelectGroup={handleSelectGroup}
        onNewChannel={handleNewChannel}
        onCreateGroup={handleCreateGroup}
        onDeleteGroup={handleDeleteGroup}
        onSignOut={onSignOut}
      />

      {chatPanelVisible && selectedChannel && (
        <ChatSessionsPanel
          channel={selectedChannel}
          sessions={chatSessions}
          activeSessionId={activeChatSessionId}
          loading={chatSessionsLoading}
          error={chatSessionsError}
          collapsed={chatPanelCollapsed}
          onToggleCollapsed={() => setChatPanelCollapsed((value) => !value)}
          onNewChat={handleNewChatSession}
          onSelectSession={handleSelectChatSession}
          onRenameSession={handleRenameChatSession}
          onDeleteSession={handleDeleteChatSession}
        />
      )}

      <main className="studio-main">
        <StudioHeader
          channel={selectedChannel}
          group={selectedGroup}
          status={status}
          refreshing={refreshing}
          exporting={exporting}
          onRefresh={handleRefreshChannel}
          onExport={handleExportChannel}
          onDelete={handleDeleteChannel}
          onNewChannel={handleNewChannel}
        />

        {selectedChannel && (
          <StudioStepper
            stages={stages}
            channel={selectedChannel}
            pipeline={pipelineState}
            selectedTotal={selectedTotal}
            onStageClick={handleStepClick}
          />
        )}

        {(healthy === false || notice || actionError) && (
          <div className="studio-notices">
            {healthy === false && (
              <div className="studio-notice danger">Backend unavailable. Is the server running?</div>
            )}
            {notice && (
              <div className="studio-notice success">
                <span>{notice}</span>
                <button type="button" onClick={() => setNotice(null)}>Dismiss</button>
              </div>
            )}
            {actionError && (
              <div className="studio-notice danger">
                <span>{actionError}</span>
                <button type="button" onClick={() => setActionError(null)}>Dismiss</button>
              </div>
            )}
          </div>
        )}

        <section className="studio-workspace">
          {view === 'no_channel' && (
            <NoChannelPanel
              value={channelInput}
              resolving={resolving}
              error={resolveError}
              onValueChange={(value) => {
                setChannelInput(value)
                setResolveError(null)
              }}
              onResolve={resolveChannel}
            />
          )}

          {view === 'group' && selectedGroup && (
            <GroupWorkspace
              group={selectedGroup}
              channels={channels}
              onDeleteGroup={handleDeleteGroup}
              onSelectChannel={(channel) => selectChannel(channel, channel.has_profile ? 'profile_ready' : 'videos')}
            />
          )}

          {view === 'videos' && selectedMeta && (
            <VideoSelectionPanel
              channel={selectedMeta}
              summary={selectedChannel}
              onRunPipeline={handleRunPipeline}
              onSelectionChange={setSelectedTotal}
            />
          )}

          {(view === 'transcripts' || view === 'summaries' || view === 'error') && selectedMeta && (
            <ProgressPanel
              channel={selectedMeta}
              stage={view === 'summaries' ? 'summaries' : 'transcripts'}
              pipeline={pipelineState}
              isError={view === 'error'}
              onBackToVideos={() => setView('videos')}
              onProfileReady={() => setView('profile_ready')}
              onSwitchToSummaries={() => setView('summaries')}
            />
          )}

          {view === 'profile_ready' && selectedMeta && (
            <ProfileSummaryPanel
              channel={selectedMeta}
              onStartChat={handleStartChat}
              onOpenVideos={() => setView('videos')}
            />
          )}

          {view === 'chat' && selectedMeta && (
            <div className="studio-chat">
              <ChatPage
                channel={selectedMeta}
                onBack={() => setView('profile_ready')}
                onComplete={() => undefined}
                initialInput={chatSeed}
                chatSessionId={activeChatSessionId}
                onSessionCreated={handleChatSessionCreated}
                onSessionUpdated={handleChatSessionUpdated}
                embedded
              />
            </div>
          )}
        </section>
      </main>
      {confirmDialog}
    </div>
  )
}

function ChatSessionsPanel({
  channel,
  sessions,
  activeSessionId,
  loading,
  error,
  collapsed,
  onToggleCollapsed,
  onNewChat,
  onSelectSession,
  onRenameSession,
  onDeleteSession,
}: {
  channel: ChannelSummary
  sessions: ChatSessionSummary[]
  activeSessionId?: string
  loading: boolean
  error: string | null
  collapsed: boolean
  onToggleCollapsed: () => void
  onNewChat: () => void
  onSelectSession: (sessionId: string) => void
  onRenameSession: (session: ChatSessionSummary) => void
  onDeleteSession: (session: ChatSessionSummary) => void
}) {
  if (collapsed) {
    return (
      <aside className="studio-chat-rail collapsed" aria-label="Channel chats">
        <button
          type="button"
          className="studio-icon-btn"
          onClick={onToggleCollapsed}
          title="Expand chats"
          aria-label="Expand chats"
        >
          <Icons.Arrow />
        </button>
        <button
          type="button"
          className="studio-chat-rail-new"
          onClick={onNewChat}
          title="New chat"
          aria-label="New chat"
        >
          <Icons.Plus />
        </button>
        <div className="studio-chat-rail-dots">
          {sessions.slice(0, 8).map((session) => (
            <button
              key={session.id}
              type="button"
              className={session.id === activeSessionId ? 'active' : ''}
              onClick={() => onSelectSession(session.id)}
              title={session.title}
              aria-label={session.title}
            >
              {session.title.charAt(0).toUpperCase()}
            </button>
          ))}
        </div>
      </aside>
    )
  }

  return (
    <aside className="studio-chat-rail" aria-label="Channel chats">
      <div className="studio-chat-rail-top">
        <div className="studio-chat-rail-channel">
          {channel.avatar_url ? <img src={channel.avatar_url} alt="" /> : <span>{initials(channel.channel_name)}</span>}
          <div>
            <b>Chats</b>
            <small>{channel.channel_name}</small>
          </div>
        </div>
        <button
          type="button"
          className="studio-icon-btn small"
          onClick={onToggleCollapsed}
          title="Collapse chats"
          aria-label="Collapse chats"
        >
          <Icons.Arrow />
        </button>
      </div>

      <button type="button" className="studio-chat-new" onClick={onNewChat}>
        <span><Icons.Plus /></span>
        New chat
      </button>

      <div className="studio-side-section">
        Chat history
        <span>{sessions.length}</span>
      </div>

      <div className="studio-chat-session-list">
        {loading && (
          <div className="studio-side-empty">
            <span className="studio-spinner" />
            Loading chats
          </div>
        )}
        {error && <div className="studio-side-empty danger">{error}</div>}
        {!loading && !error && sessions.length === 0 && (
          <div className="studio-side-empty">
            <b>No chats yet</b>
            <p>Create a new chat for this channel.</p>
          </div>
        )}
        {!loading && !error && sessions.map((session) => (
          <div
            key={session.id}
            role="button"
            tabIndex={0}
            className={`studio-chat-session ${session.id === activeSessionId ? 'active' : ''}`}
            onClick={() => onSelectSession(session.id)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onSelectSession(session.id)
              }
            }}
          >
            <span className="studio-chat-session-mark">
              <Icons.Spark />
            </span>
            <span className="studio-chat-session-main">
              <b>{session.title}</b>
              <small>
                {formatRelativeIso(session.updated_at)}
                {session.message_count > 0 ? ` · ${session.message_count} messages` : ' · empty'}
              </small>
            </span>
            <span className="studio-chat-session-actions">
              <button
                type="button"
                title="Rename chat"
                onClick={(event) => {
                  event.stopPropagation()
                  onRenameSession(session)
                }}
              >
                <Icons.More />
              </button>
              <button
                type="button"
                title="Delete chat"
                onClick={(event) => {
                  event.stopPropagation()
                  onDeleteSession(session)
                }}
              >
                <Icons.Trash />
              </button>
            </span>
          </div>
        ))}
      </div>
    </aside>
  )
}

function StudioSidebar({
  session,
  channels,
  groups,
  loading,
  error,
  selection,
  selectedChannelId,
  selectedGroupId,
  selectedPipeline,
  onSelectChannel,
  onSelectGroup,
  onNewChannel,
  onCreateGroup,
  onDeleteGroup,
  onSignOut,
}: {
  session: Session
  channels: ChannelSummary[]
  groups: LocalChannelGroup[]
  loading: boolean
  error: string | null
  selection: StudioSelection
  selectedChannelId: string | null
  selectedGroupId: string | null
  selectedPipeline: PipelineState | null
  onSelectChannel: (channel: ChannelSummary) => void
  onSelectGroup: (group: LocalChannelGroup) => void
  onNewChannel: () => void
  onCreateGroup: (name: string, memberChannelIds: string[]) => void
  onDeleteGroup: (groupId: string) => void
  onSignOut: () => Promise<void>
}) {
  const [query, setQuery] = useState('')
  const [composingGroup, setComposingGroup] = useState(false)
  const [groupName, setGroupName] = useState('')
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const normalizedQuery = query.trim().toLowerCase()
  const filteredChannels = normalizedQuery
    ? channels.filter((channel) =>
      channel.channel_name.toLowerCase().includes(normalizedQuery) ||
      (channel.channel_handle ?? '').toLowerCase().includes(normalizedQuery))
    : channels
  const canCreateGroup = groupName.trim().length > 0 && picked.size >= 2

  const togglePick = (channelId: string) => {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(channelId)) next.delete(channelId)
      else next.add(channelId)
      return next
    })
  }

  const resetComposer = () => {
    setComposingGroup(false)
    setGroupName('')
    setPicked(new Set())
  }

  const createGroup = () => {
    if (!canCreateGroup) return
    onCreateGroup(groupName, Array.from(picked))
    resetComposer()
  }

  const email = session.user.email ?? 'Signed in'

  return (
    <aside className="studio-side">
      <div className="studio-side-top">
        <div className="studio-brand">
          <div className="studio-brand-mark">T</div>
          <div className="studio-brand-name">Trace<sup>STUDIO</sup></div>
        </div>
        <button type="button" className="studio-icon-btn" aria-label="More">
          <Icons.More />
        </button>
      </div>

      <div className="studio-search">
        <Icons.Search />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search channels..." />
      </div>

      <button type="button" className="studio-side-new" onClick={onNewChannel}>
        <span><Icons.Plus /></span>
        New channel
      </button>

      <div className="studio-side-section">
        Library <span>{channels.length + groups.length}</span>
      </div>

      <div className="studio-side-list">
        {loading && (
          <div className="studio-side-empty">
            <span className="studio-spinner" />
            Loading channels
          </div>
        )}

        {error && !loading && (
          <div className="studio-side-empty danger">{error}</div>
        )}

        {!loading && !error && channels.length === 0 && (
          <div className="studio-side-empty">
            <div className="studio-empty-glyph"><Icons.Spark /></div>
            <b>No channels yet.</b>
            <span>Paste a YouTube URL or handle to start tracing.</span>
          </div>
        )}

        {!loading && channels.length > 0 && (
          <>
            <div className="studio-side-subsection">
              <span>Groups</span>
              <button
                type="button"
                className="studio-subsection-plus"
                onClick={() => setComposingGroup((value) => !value)}
                aria-label="Create group"
                title="Create local channel group"
              >
                <Icons.Plus />
              </button>
            </div>

            {composingGroup && (
              <div className="studio-group-composer">
                <input
                  value={groupName}
                  onChange={(event) => setGroupName(event.target.value)}
                  placeholder="Group name"
                  autoFocus
                />
                <div className="studio-group-hint">Pick 2+ channels. Groups are local UI drafts.</div>
                <div className="studio-group-picks">
                  {channels.map((channel) => (
                    <label key={channel.channel_id} className={`studio-group-pick ${picked.has(channel.channel_id) ? 'on' : ''}`}>
                      <span className="studio-group-check">{picked.has(channel.channel_id) && <Icons.Check />}</span>
                      <input
                        type="checkbox"
                        checked={picked.has(channel.channel_id)}
                        onChange={() => togglePick(channel.channel_id)}
                      />
                      <ChannelAvatar channel={channel} size="sm" />
                      <span className="studio-group-pick-name">{channel.channel_name}</span>
                    </label>
                  ))}
                </div>
                <div className="studio-group-actions">
                  <span>{picked.size} selected</span>
                  <button type="button" className="studio-btn secondary compact" onClick={resetComposer}>Cancel</button>
                  <button type="button" className="studio-btn primary compact" disabled={!canCreateGroup} onClick={createGroup}>Create</button>
                </div>
              </div>
            )}

            {groups.map((group) => (
              <GroupRow
                key={group.id}
                group={group}
                channels={channels}
                active={selection?.kind === 'group' && group.id === selectedGroupId}
                onSelect={() => onSelectGroup(group)}
                onDelete={() => onDeleteGroup(group.id)}
              />
            ))}

            <div className="studio-side-subsection">
              <span>Channels</span>
            </div>
            {filteredChannels.map((channel) => (
              <ChannelRow
                key={channel.channel_id}
                channel={channel}
                active={channel.channel_id === selectedChannelId}
                pipeline={channel.channel_id === selectedChannelId ? selectedPipeline : null}
                onSelect={() => onSelectChannel(channel)}
              />
            ))}
          </>
        )}
      </div>

      <div className="studio-side-foot">
        <div className="studio-user">
          <div className="studio-user-av">{initials(email)}</div>
          <div>
            <div className="studio-user-name">{email}</div>
            <div className="studio-user-plan">Studio beta</div>
          </div>
        </div>
        <button type="button" className="studio-btn secondary compact" onClick={onSignOut}>Sign out</button>
      </div>
    </aside>
  )
}

function ChannelAvatar({ channel, size = 'md' }: { channel: ChannelSummary | ChannelMeta; size?: 'sm' | 'md' | 'lg' }) {
  const name = 'channel_name' in channel ? channel.channel_name : ''
  const avatarUrl = 'avatar_url' in channel ? channel.avatar_url : null
  return avatarUrl ? (
    <img src={avatarUrl} alt="" className={`studio-avatar ${size}`} />
  ) : (
    <span className={`studio-avatar fallback ${size}`}>{initials(name)}</span>
  )
}

function GroupAvatar({ group, channels }: { group: LocalChannelGroup; channels: ChannelSummary[] }) {
  const members = group.memberChannelIds
    .map((id) => channels.find((channel) => channel.channel_id === id))
    .filter((channel): channel is ChannelSummary => Boolean(channel))
    .slice(0, 3)

  return (
    <span className="studio-group-avatar">
      {members.map((member, index) => (
        <span key={member.channel_id} className={`slot slot-${index}`}>
          {member.avatar_url ? <img src={member.avatar_url} alt="" /> : initials(member.channel_name)}
        </span>
      ))}
    </span>
  )
}

function ChannelRow({
  channel,
  active,
  pipeline,
  onSelect,
}: {
  channel: ChannelSummary
  active: boolean
  pipeline: PipelineState | null
  onSelect: () => void
}) {
  const status = statusForChannel(channel, pipeline)
  const stages = stagesFromState(channel, pipeline, channel.has_profile ? 'profile_ready' : 'videos')
  const updated = formatRelativeIso(channel.updated_at)

  return (
    <button type="button" className={`studio-channel-row ${active ? 'active' : ''}`} onClick={onSelect}>
      <ChannelAvatar channel={channel} />
      <span className="studio-channel-body">
        <span className="studio-channel-name">{channel.channel_name}</span>
        <span className="studio-channel-meta">
          <span>{channel.channel_handle ? `@${channel.channel_handle}` : `${channel.video_count} videos`}</span>
          {updated && <span>{updated}</span>}
          <span className={`studio-status ${status.tone}`}><span />{status.label}</span>
        </span>
      </span>
      <span className="studio-channel-progress" aria-hidden>
        {stages.map((stage) => (
          <span key={stage.id} className={stage.status} />
        ))}
      </span>
    </button>
  )
}

function GroupRow({
  group,
  channels,
  active,
  onSelect,
  onDelete,
}: {
  group: LocalChannelGroup
  channels: ChannelSummary[]
  active: boolean
  onSelect: () => void
  onDelete: () => void
}) {
  const members = group.memberChannelIds
    .map((id) => channels.find((channel) => channel.channel_id === id))
    .filter((channel): channel is ChannelSummary => Boolean(channel))

  return (
    <div className={`studio-channel-row studio-group-row ${active ? 'active' : ''}`}>
      <button type="button" className="studio-row-main" onClick={onSelect}>
        <GroupAvatar group={group} channels={channels} />
        <span className="studio-channel-body">
          <span className="studio-channel-name">{group.name}<span className="studio-group-badge">GROUP</span></span>
          <span className="studio-channel-meta">{members.length} channels · local draft</span>
        </span>
      </button>
      <button type="button" className="studio-icon-btn small danger" onClick={onDelete} aria-label="Delete group">
        <Icons.Close />
      </button>
    </div>
  )
}

function StudioHeader({
  channel,
  group,
  status,
  refreshing,
  exporting,
  onRefresh,
  onExport,
  onDelete,
  onNewChannel,
}: {
  channel: ChannelSummary | null
  group: LocalChannelGroup | null
  status: { label: string; tone: 'ready' | 'run' | 'warn' | 'err' | 'idle' }
  refreshing: boolean
  exporting: boolean
  onRefresh: () => void
  onExport: () => void
  onDelete: () => void
  onNewChannel: () => void
}) {
  return (
    <header className="studio-header">
      <div className="studio-header-title">
        {channel ? (
          <>
            <ChannelAvatar channel={channel} />
            <div>
              <div className="studio-header-name">{channel.channel_name}</div>
              <div className="studio-header-sub">
                {channel.channel_handle ? `@${channel.channel_handle}` : 'YouTube channel'} · {channel.video_count.toLocaleString()} videos
              </div>
            </div>
            <span className={`studio-status-pill ${status.tone}`}><span />{status.label}</span>
          </>
        ) : group ? (
          <>
            <span className="studio-avatar fallback md">{initials(group.name)}</span>
            <div>
              <div className="studio-header-name">{group.name}<span className="studio-group-badge">GROUP</span></div>
              <div className="studio-header-sub">{group.memberChannelIds.length} channels · local draft</div>
            </div>
            <span className="studio-status-pill idle"><span />UI only</span>
          </>
        ) : (
          <div>
            <div className="studio-header-name muted">No channel selected</div>
            <div className="studio-header-sub">Start by adding or selecting a channel.</div>
          </div>
        )}
      </div>

      <div className="studio-header-actions">
        {channel ? (
          <>
            <button type="button" className="studio-btn secondary" onClick={onRefresh} disabled={refreshing}>
              {refreshing ? <span className="studio-spinner" /> : <Icons.Refresh />}
              Refresh
            </button>
            <button type="button" className="studio-btn secondary" onClick={onExport} disabled={exporting || !channel.has_profile}>
              {exporting ? <span className="studio-spinner" /> : <Icons.Download />}
              Export
            </button>
            <button type="button" className="studio-icon-btn danger" onClick={onDelete} aria-label="Delete channel">
              <Icons.Trash />
            </button>
          </>
        ) : (
          <button type="button" className="studio-btn primary" onClick={onNewChannel}>
            <Icons.Plus />
            New channel
          </button>
        )}
      </div>
    </header>
  )
}

function StudioStepper({
  stages,
  channel,
  pipeline,
  selectedTotal,
  onStageClick,
}: {
  stages: Stage[]
  channel: ChannelSummary
  pipeline: PipelineState | null
  selectedTotal: number
  onStageClick: (stage: Stage) => void
}) {
  return (
    <nav className="studio-stepper" aria-label="Pipeline steps">
      {stages.map((stage, index) => (
        <div key={stage.id} className="studio-step-wrap">
          <button type="button" className={`studio-step ${stage.status}`} onClick={() => onStageClick(stage)}>
            <span className="studio-step-num">
              {stage.status === 'done' ? <Icons.Check /> : stage.status === 'error' ? <Icons.Warn /> : index + 1}
            </span>
            <span>
              <span className="studio-step-label">{stage.label}</span>
              <span className="studio-step-meta">{stageMeta(stage, channel, pipeline, selectedTotal)}</span>
            </span>
          </button>
          {index < stages.length - 1 && <span className={`studio-step-line ${stage.status === 'done' ? 'done' : stage.status === 'active' ? 'active' : ''}`} />}
        </div>
      ))}
    </nav>
  )
}

function NoChannelPanel({
  value,
  resolving,
  error,
  onValueChange,
  onResolve,
}: {
  value: string
  resolving: boolean
  error: string | null
  onValueChange: (value: string) => void
  onResolve: (value: string) => void
}) {
  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    onResolve(value)
  }

  return (
    <div className="studio-centered">
      <div className="studio-resolve-card">
        <div className="studio-resolve-mark">T</div>
        <h1>Trace a channel.</h1>
        <p>Paste a YouTube URL or handle. Trace will fetch the library, let you choose the slice to profile, and keep the chat cited to source.</p>
        <form className="studio-resolve-form" onSubmit={handleSubmit}>
          <input
            value={value}
            onChange={(event) => onValueChange(event.target.value)}
            placeholder="youtube.com/@mkbhd or @veritasium"
            disabled={resolving}
          />
          <button type="submit" className="studio-btn primary" disabled={resolving}>
            {resolving ? <span className="studio-spinner" /> : <Icons.Arrow />}
            Trace
          </button>
        </form>
        {error && <div className="studio-form-error">{error}</div>}
        <div className="studio-examples">
          <span>Try</span>
          {EXAMPLES.map((example) => (
            <button key={example.url} type="button" onClick={() => onValueChange(example.url)}>{example.label}</button>
          ))}
        </div>
      </div>
    </div>
  )
}

function GroupWorkspace({
  group,
  channels,
  onDeleteGroup,
  onSelectChannel,
}: {
  group: LocalChannelGroup
  channels: ChannelSummary[]
  onDeleteGroup: (groupId: string) => void
  onSelectChannel: (channel: ChannelSummary) => void
}) {
  const members = group.memberChannelIds
    .map((id) => channels.find((channel) => channel.channel_id === id))
    .filter((channel): channel is ChannelSummary => Boolean(channel))

  return (
    <div className="studio-scroll">
      <div className="studio-panel narrow">
        <div className="studio-panel-head">
          <div>
            <div className="studio-eyebrow">Local group</div>
            <h2>{group.name}</h2>
            <p>Groups are available in the Studio UI now. Backend analysis, chat, and export still run on individual channels.</p>
          </div>
          <button type="button" className="studio-btn secondary danger" onClick={() => onDeleteGroup(group.id)}>
            <Icons.Trash />
            Delete group
          </button>
        </div>

        <div className="studio-member-list">
          {members.map((member) => (
            <button key={member.channel_id} type="button" className="studio-member-row" onClick={() => onSelectChannel(member)}>
              <ChannelAvatar channel={member} />
              <span>
                <b>{member.channel_name}</b>
                <small>{member.channel_handle ? `@${member.channel_handle}` : `${member.video_count} videos`}</small>
              </span>
              <Icons.Arrow />
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function VideoSelectionPanel({
  channel,
  summary,
  onRunPipeline,
  onSelectionChange,
}: {
  channel: ChannelMeta
  summary: ChannelSummary | null
  onRunPipeline: () => void
  onSelectionChange?: (total: number) => void
}) {
  const PAGE_SIZE = 50
  const isPlaylistMode = (channel.kind ?? 'channel') === 'playlist'
  const [tab, setTab] = useState<'videos' | 'playlists' | 'shorts'>('videos')
  const [counts, setCounts] = useState<{ videos: number; shorts: number; playlists: number } | null>(null)
  const [longVideos, setLongVideos] = useState<Video[]>([])
  const [shortVideos, setShortVideos] = useState<Video[]>([])
  const [longHasMore, setLongHasMore] = useState(false)
  const [shortHasMore, setShortHasMore] = useState(false)
  const [longTotal, setLongTotal] = useState(0)
  const [shortTotal, setShortTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [playlists, setPlaylists] = useState<Playlist[]>([])
  const [selectedPlaylistIds, setSelectedPlaylistIds] = useState<Set<string>>(new Set())
  const [playlistsLoading, setPlaylistsLoading] = useState(false)
  const [playlistsError, setPlaylistsError] = useState<string | null>(null)
  const [resolvingPlaylists, setResolvingPlaylists] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const playlistsAttemptedRef = useRef(false)
  const shortsAttemptedRef = useRef(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      const [longRes, selectionRes] = await Promise.all([
        api.videoPage(channel.channel_id, 'videos', 0, PAGE_SIZE),
        api.selection(channel.channel_id),
      ])
      if (cancelled) return
      const longList = longRes.data?.videos ?? []
      setLongVideos(longList)
      setLongHasMore(longRes.data?.has_more ?? false)
      setLongTotal(longRes.data?.total ?? longList.length)
      const persistedIds = selectionRes.data?.video_ids ?? []
      setSelectedIds(new Set(persistedIds))
      setLoading(false)
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [channel.channel_id])

  useEffect(() => {
    let cancelled = false
    void api.channelCounts(channel.channel_id).then((res) => {
      if (cancelled) return
      if (res.data) setCounts({ videos: res.data.videos, shorts: res.data.shorts, playlists: res.data.playlists })
    })
    return () => {
      cancelled = true
    }
  }, [channel.channel_id])

  useEffect(() => {
    playlistsAttemptedRef.current = false
    shortsAttemptedRef.current = false
    setPlaylists([])
    setShortVideos([])
    setSelectedPlaylistIds(new Set())
    setPlaylistsError(null)
  }, [channel.channel_id])

  useEffect(() => {
    const stored = localStorage.getItem(`cp_playlists_${channel.channel_id}`)
    if (!stored) return
    try {
      setSelectedPlaylistIds(new Set(JSON.parse(stored)))
    } catch {
      setSelectedPlaylistIds(new Set())
    }
  }, [channel.channel_id])

  useEffect(() => {
    localStorage.setItem(`cp_playlists_${channel.channel_id}`, JSON.stringify(Array.from(selectedPlaylistIds)))
  }, [channel.channel_id, selectedPlaylistIds])

  useEffect(() => {
    if (!onSelectionChange) return
    const plCount = playlists
      .filter((playlist) => selectedPlaylistIds.has(playlist.id))
      .reduce((sum, playlist) => sum + playlist.video_count, 0)
    onSelectionChange(selectedIds.size + plCount)
  }, [selectedIds, selectedPlaylistIds, playlists, onSelectionChange])

  useEffect(() => {
    if (isPlaylistMode) return
    if (tab === 'playlists' && !playlistsAttemptedRef.current) {
      playlistsAttemptedRef.current = true
      setPlaylistsLoading(true)
      setPlaylistsError(null)
      void api.playlists(channel.channel_id).then((res) => {
        setPlaylistsLoading(false)
        if (!res.ok) {
          setPlaylistsError(res.error || 'Failed to load playlists')
          return
        }
        setPlaylists(res.data?.playlists ?? [])
      })
    }
    if (tab === 'shorts' && !shortsAttemptedRef.current) {
      shortsAttemptedRef.current = true
      void api.videoPage(channel.channel_id, 'shorts', 0, PAGE_SIZE).then((res) => {
        if (!res.ok || !res.data) return
        setShortVideos(res.data.videos)
        setShortHasMore(res.data.has_more)
        setShortTotal(res.data.total)
      })
    }
  }, [tab, channel.channel_id, isPlaylistMode])

  const loadMore = async () => {
    setLoadingMore(true)
    if (tab === 'videos') {
      const res = await api.videoPage(channel.channel_id, 'videos', longVideos.length, PAGE_SIZE)
      if (res.ok && res.data) {
        setLongVideos((prev) => [...prev, ...res.data!.videos])
        setLongHasMore(res.data.has_more)
      }
    } else if (tab === 'shorts') {
      const res = await api.videoPage(channel.channel_id, 'shorts', shortVideos.length, PAGE_SIZE)
      if (res.ok && res.data) {
        setShortVideos((prev) => [...prev, ...res.data!.videos])
        setShortHasMore(res.data.has_more)
      }
    }
    setLoadingMore(false)
  }

  const longCount =
    counts?.videos ??
    (longTotal > 0 ? longTotal : undefined) ??
    summary?.video_count ??
    longVideos.length

  const optimisticPlaylistCount = playlists
    .filter((playlist) => selectedPlaylistIds.has(playlist.id))
    .reduce((sum, playlist) => sum + playlist.video_count, 0)
  const optimisticTotal = selectedIds.size + optimisticPlaylistCount
  const hasSelection = selectedIds.size > 0 || selectedPlaylistIds.size > 0

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
    void persistSelection(next)
  }

  const replaceSubsetSelection = (videoSubset: Video[], newIds: Set<string>) => {
    const subsetIds = new Set(videoSubset.map((video) => video.id))
    const preserved = Array.from(selectedIds).filter((id) => !subsetIds.has(id))
    void persistSelection(new Set([...preserved, ...newIds]))
  }

  const expandSelection = async (): Promise<{ ids: string[]; error: string | null }> => {
    const expanded = new Set(selectedIds)
    for (const playlistId of selectedPlaylistIds) {
      const res = await api.playlistVideos(channel.channel_id, playlistId)
      if (!res.ok) return { ids: [], error: res.error || `Failed to expand playlist ${playlistId}` }
      for (const videoId of res.data?.video_ids ?? []) expanded.add(videoId)
    }
    return { ids: Array.from(expanded), error: null }
  }

  const handleRun = async () => {
    setResolvingPlaylists(true)
    setRunError(null)
    const expanded = await expandSelection()
    if (expanded.error) {
      setResolvingPlaylists(false)
      setRunError(expanded.error)
      return
    }
    await api.selectVideos(channel.channel_id, expanded.ids)
    setResolvingPlaylists(false)
    onRunPipeline()
  }

  if (loading) {
    return <WorkspaceLoading label="Loading library" />
  }

  const handle = channel.channel_handle ? (channel.channel_handle.startsWith('@') ? channel.channel_handle : `@${channel.channel_handle}`) : null
  const youtubeUrl = isPlaylistMode
    ? `https://www.youtube.com/playlist?list=${channel.playlist_id ?? channel.channel_id}`
    : handle
      ? `https://www.youtube.com/${handle}`
      : `https://www.youtube.com/channel/${channel.channel_id}`
  const lastUpload = longVideos[0]?.upload_date
  const subscriberLabel = formatCompactNumber(channel.subscriber_count ?? undefined)
  const estMin = Math.max(1, Math.ceil(optimisticTotal * 0.1))
  const tabs = [
    { id: 'videos' as const, label: 'Videos' },
    { id: 'playlists' as const, label: 'Playlists' },
    { id: 'shorts' as const, label: 'Shorts' },
  ]
  const subset = tab === 'shorts' ? shortVideos : longVideos

  return (
    <>
      <div className={`studio-scroll${hasSelection ? ' has-runbar' : ''}`}>
        <div className="state-card">
          <div className="studio-vids-channel">
            {channel.avatar_url ? (
              <img src={channel.avatar_url} alt="" className="studio-vids-channel-av" />
            ) : (
              <div className="studio-vids-channel-av-fallback">{initials(channel.channel_name)}</div>
            )}
            <div className="studio-vids-channel-body">
              <div className="studio-vids-channel-row">
                {isPlaylistMode && (
                  <span className="studio-vids-channel-stat" style={{ textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: 11 }}>Playlist</span>
                )}
                <span className="studio-vids-channel-name">{channel.channel_name}</span>
                {handle && <span className="studio-vids-channel-handle">{handle}</span>}
                {!isPlaylistMode && subscriberLabel && (
                  <span className="studio-vids-channel-stat">· {subscriberLabel} subscribers</span>
                )}
                {isPlaylistMode && channel.owner_channel_name && (
                  <span className="studio-vids-channel-stat">· by {channel.owner_channel_name}</span>
                )}
              </div>
              {lastUpload && (
                <div className="studio-vids-channel-meta">
                  <span>Last upload <b>{formatRelativeDate(lastUpload)}</b></span>
                </div>
              )}
            </div>
            <a className="studio-vids-channel-link" href={youtubeUrl} target="_blank" rel="noreferrer noopener">
              <Icons.Ext /> View on YouTube
            </a>
          </div>

          <div className="studio-vids-tabs" role="tablist">
            {!isPlaylistMode && tabs.map((item) => (
              <button
                key={item.id}
                role="tab"
                aria-selected={tab === item.id}
                className={`studio-vids-tab${tab === item.id ? ' is-active' : ''}`}
                onClick={() => setTab(item.id)}
              >
                <span className="studio-vids-tab-label">{item.label}</span>
              </button>
            ))}
            {isPlaylistMode && (
              <span className="studio-vids-tab is-active" aria-current="true">
                <span className="studio-vids-tab-label">Playlist videos</span>
              </span>
            )}
            <div className="studio-vids-tabs-spacer" />
            {tab !== 'playlists' && subset.length > 0 && (
              <div className="studio-vids-quick">
                <button type="button" onClick={() => replaceSubsetSelection(subset, new Set(subset.map((video) => video.id).slice(0, MAX_SELECTION)))}>All</button>
                <button type="button" onClick={() => replaceSubsetSelection(subset, new Set())}>None</button>
                <button type="button" onClick={() => replaceSubsetSelection(subset, new Set(subset.slice(0, 50).map((video) => video.id)))}>First 50</button>
              </div>
            )}
          </div>

          {tab === 'videos' && (
            <>
              <div className="state-card-head" style={{ marginTop: 14, marginBottom: 10 }}>
                <div>
                  <div className="state-card-title">
                    <Icons.Evidence /> Choose videos to trace
                  </div>
                  <div className="state-card-sub">
                    Select the slice you want profiled — or run the full pipeline.
                  </div>
                </div>
              </div>
              <VidGrid videos={longVideos} selectedIds={selectedIds} onToggle={toggleVideo} />
              {longHasMore && (
                <div className="studio-vids-loadmore">
                  <button type="button" onClick={loadMore} disabled={loadingMore}>
                    {loadingMore ? 'Loading…' : `Load ${PAGE_SIZE} more`}
                  </button>
                </div>
              )}
            </>
          )}

          {tab === 'shorts' && (
            <>
              <div className="state-card-head" style={{ marginTop: 14, marginBottom: 10 }}>
                <div>
                  <div className="state-card-title">
                    <Icons.Evidence /> Choose shorts to trace
                  </div>
                  <div className="state-card-sub">
                    Pick a slice — or run the long-form pipeline.
                  </div>
                </div>
              </div>
              {shortVideos.length === 0 ? (
                <div className="studio-empty-state">No Shorts found.</div>
              ) : (
                <ShortsGrid videos={shortVideos} selectedIds={selectedIds} onToggle={toggleVideo} />
              )}
              {shortHasMore && (
                <div className="studio-vids-loadmore">
                  <button type="button" onClick={loadMore} disabled={loadingMore}>
                    {loadingMore ? 'Loading…' : `Load ${PAGE_SIZE} more`}
                  </button>
                </div>
              )}
            </>
          )}

          {tab === 'playlists' && (
            <>
              <div className="state-card-head" style={{ marginTop: 14, marginBottom: 10 }}>
                <div>
                  <div className="state-card-title">
                    <Icons.Evidence /> Add playlists
                  </div>
                  <div className="state-card-sub">
                    Selected playlists expand into their videos when the pipeline starts.
                  </div>
                </div>
              </div>
              {playlistsLoading ? (
                <WorkspaceLoading label="Loading playlists" compact />
              ) : playlistsError ? (
                <div className="studio-empty-state danger">{playlistsError}</div>
              ) : playlists.length === 0 ? (
                <div className="studio-empty-state">No public playlists found.</div>
              ) : (
                <div className="studio-vids-playlists">
                  {playlists.map((playlist) => {
                    const selected = selectedPlaylistIds.has(playlist.id)
                    return (
                      <button
                        key={playlist.id}
                        type="button"
                        className={`studio-vids-pl${selected ? ' is-selected' : ''}`}
                        onClick={() => {
                          setSelectedPlaylistIds((prev) => {
                            const next = new Set(prev)
                            if (next.has(playlist.id)) next.delete(playlist.id)
                            else next.add(playlist.id)
                            return next
                          })
                        }}
                      >
                        <div className="studio-vids-pl-thumb-wrap">
                          {playlist.thumbnail ? (
                            <img className="studio-vids-pl-thumb" src={playlist.thumbnail} alt="" loading="lazy" />
                          ) : (
                            <div className="studio-vids-pl-thumb" />
                          )}
                          <span className="studio-vids-pl-count">
                            <Icons.Play /> {playlist.video_count.toLocaleString()}
                          </span>
                        </div>
                        <div className="studio-vids-pl-body">
                          <div className="studio-vids-pl-title">{playlist.title}</div>
                          <div className="studio-vids-pl-meta">{playlist.video_count.toLocaleString()} videos</div>
                        </div>
                        <div className="vid-check">{selected && <Icons.Check />}</div>
                      </button>
                    )
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <div className={`studio-vids-runbar${hasSelection ? ' is-visible' : ''}`} aria-hidden={!hasSelection}>
        <div className="studio-vids-runbar-inner">
          <div className="counts">
            <b>{optimisticTotal.toLocaleString()}</b> videos selected
            {optimisticTotal > 0 && <span>· est. <b>~{estMin} min</b></span>}
            {saving && <span className="saving">saving…</span>}
            {optimisticTotal > MAX_SELECTION && <span className="warn">{MAX_SELECTION}+ may be slow</span>}
            {runError && <span className="warn">{runError}</span>}
          </div>
          <div className="studio-vids-runbar-actions">
            <button type="button" className="btn-primary-sm" disabled={!hasSelection || resolvingPlaylists} onClick={handleRun}>
              {resolvingPlaylists ? <span className="studio-spinner" /> : null}
              Transcript <Icons.Arrow />
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

function VidGrid({
  videos,
  selectedIds,
  onToggle,
}: {
  videos: Video[]
  selectedIds: Set<string>
  onToggle: (id: string) => void
}) {
  if (videos.length === 0) {
    return <div className="studio-empty-state">No long-form videos found.</div>
  }
  return (
    <div className="vidgrid">
      {videos.map((video) => {
        const selected = selectedIds.has(video.id)
        return (
          <button key={video.id} type="button" className={`vid${selected ? ' sel' : ''}`} onClick={() => onToggle(video.id)}>
            <div className="vid-thumb">
              <img src={video.thumbnail} alt="" loading="lazy" />
              {video.duration > 0 && <span className="dur">{formatDuration(video.duration)}</span>}
            </div>
            <div>
              <div className="vid-title">{video.title}</div>
              <div className="vid-meta">{formatRelativeDate(video.upload_date)}</div>
            </div>
            <div className="vid-check">{selected && <Icons.Check />}</div>
          </button>
        )
      })}
    </div>
  )
}

function ShortsGrid({
  videos,
  selectedIds,
  onToggle,
}: {
  videos: Video[]
  selectedIds: Set<string>
  onToggle: (id: string) => void
}) {
  return (
    <div className="studio-vids-shorts">
      {videos.map((video) => {
        const selected = selectedIds.has(video.id)
        return (
          <button
            key={video.id}
            type="button"
            className={`studio-vids-short${selected ? ' is-selected' : ''}`}
            onClick={() => onToggle(video.id)}
          >
            <div className="studio-vids-short-thumb">
              <img src={video.thumbnail} alt="" loading="lazy" />
              {video.view_count > 0 && (
                <span className="studio-vids-short-views">
                  {video.view_count >= 1_000_000
                    ? `${(video.view_count / 1_000_000).toFixed(1)}M`
                    : video.view_count >= 1_000
                      ? `${(video.view_count / 1_000).toFixed(0)}K`
                      : video.view_count.toLocaleString()}
                </span>
              )}
              <span className="studio-vids-short-check">{selected && <Icons.Check />}</span>
            </div>
            <div className="studio-vids-short-title">{video.title}</div>
          </button>
        )
      })}
    </div>
  )
}

const STATUS_PILL: Record<string, { cls: string; label: string }> = {
  done: { cls: 'is-done', label: 'Done' },
  failed: { cls: 'is-failed', label: 'Failed' },
  unavailable: { cls: 'is-unavail', label: 'Unavailable' },
  skipped: { cls: 'is-skipped', label: 'Skipped' },
  queued: { cls: 'is-queued', label: 'Queued' },
  fetching: { cls: 'is-fetching', label: 'Running' },
}

function ProgressPanel({
  channel,
  stage,
  pipeline,
  isError,
  onBackToVideos,
  onProfileReady,
  onSwitchToSummaries,
}: {
  channel: ChannelMeta
  stage: 'transcripts' | 'summaries'
  pipeline: PipelineState | null
  isError: boolean
  onBackToVideos: () => void
  onProfileReady: () => void
  onSwitchToSummaries: () => void
}) {
  const [baseVideos, setBaseVideos] = useState<Video[]>([])
  const [loading, setLoading] = useState(true)
  const [cost, setCost] = useState<PipelineCost | null>(null)
  const [controlError, setControlError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [resuming, setResuming] = useState(false)
  const [starting, setStarting] = useState(false)
  const { confirm, dialog: confirmDialog } = useConfirm()

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      const [videosRes, costRes] = await Promise.all([
        api.videos(channel.channel_id),
        stage === 'summaries' ? api.pipelineCost(channel.channel_id) : Promise.resolve(null),
      ])
      if (cancelled) return
      setBaseVideos(videosRes.data?.videos ?? [])
      if (costRes && costRes.ok && costRes.data) setCost(costRes.data)
      setLoading(false)
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [channel.channel_id, stage])

  useEffect(() => {
    if (pipeline?.status === 'completed' || pipeline?.stages?.profile?.status === 'done') {
      onProfileReady()
    }
  }, [pipeline?.status, pipeline?.stages?.profile?.status, onProfileReady])

  const stageState = pipeline?.stages?.[stage]
  const statusMap = stageState?.videos ?? {}
  const videoMetaMap = useMemo(() => {
    const map = new Map<string, { title: string; thumbnail: string; duration: number }>()
    for (const v of baseVideos) {
      map.set(v.id, { title: v.title, thumbnail: v.thumbnail, duration: v.duration })
    }
    return map
  }, [baseVideos])

  const terminalStatuses = useMemo(
    () =>
      stage === 'transcripts'
        ? new Set(['done', 'skipped', 'unavailable', 'failed'])
        : new Set(['done', 'skipped', 'failed']),
    [stage],
  )

  type Row = {
    id: string
    idx: number
    title: string
    thumbnail: string
    duration: number
    status: string
    subPct?: number
    subLabel: string
  }

  const rows: Row[] = useMemo(() => {
    const statusIds = new Set(Object.keys(statusMap))
    const fromBase = baseVideos
      .filter((video) => statusIds.has(video.id))
      .map((video) => ({
        id: video.id,
        title: video.title,
        thumbnail: video.thumbnail,
        duration: video.duration,
        status: typeof statusMap[video.id]?.status === 'string' ? (statusMap[video.id].status as string) : 'queued',
      }))
    const seen = new Set(fromBase.map((r) => r.id))
    const fromStatus = Object.entries(statusMap)
      .filter(([id]) => !seen.has(id))
      .map(([id, vstate]) => {
        const meta = videoMetaMap.get(id)
        const stateTitle = typeof vstate.title === 'string' && vstate.title.trim() ? vstate.title : ''
        return {
          id,
          title: meta?.title || stateTitle || 'Untitled',
          thumbnail: meta?.thumbnail || `https://i.ytimg.com/vi/${id}/mqdefault.jpg`,
          duration: meta?.duration ?? 0,
          status: typeof vstate.status === 'string' ? vstate.status : 'queued',
        }
      })
    const base = [...fromBase, ...fromStatus].map((r, i) => ({ ...r, idx: i + 1 }))
    let fetchIdx = 0
    return base.map((r) => {
      let subLabel = 'Queued'
      let subPct: number | undefined
      if (r.status === 'fetching') {
        subLabel = stage === 'summaries' ? 'Synthesizing themes' : 'Transcribing (ASR)'
        subPct = [62, 34, 9][fetchIdx] ?? 12
        fetchIdx += 1
      } else if (r.status === 'done') {
        subLabel = stage === 'summaries' ? 'Summarized' : (r.duration > 0 ? formatDuration(r.duration) : 'Done')
      } else if (r.status === 'failed') {
        subLabel = 'Failed'
      } else if (r.status === 'unavailable') {
        subLabel = 'No transcript'
      } else if (r.status === 'skipped') {
        subLabel = 'Skipped'
      }
      return { ...r, subLabel, subPct }
    })
  }, [baseVideos, statusMap, stage, videoMetaMap])

  const videoStats = useMemo(() => {
    let done = 0
    let failed = 0
    let unavail = 0
    let fetching = 0
    let completed = 0
    for (const v of Object.values(statusMap)) {
      const status = typeof v.status === 'string' ? v.status : ''
      if (status === 'done') done += 1
      else if (status === 'failed') failed += 1
      else if (status === 'unavailable') unavail += 1
      else if (status === 'fetching') fetching += 1
      if (terminalStatuses.has(status)) completed += 1
    }
    return { done, failed, unavail, fetching, completed }
  }, [statusMap, terminalStatuses])

  const total = stageState?.total ?? rows.length
  const completed = stageState?.completed ?? videoStats.completed
  const { done, failed, unavail, fetching } = videoStats
  const queued = Math.max(0, total - completed - fetching)
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0
  const seg = {
    done: total > 0 ? (done / total) * 100 : 0,
    failed: total > 0 ? (failed / total) * 100 : 0,
    unavail: total > 0 ? (unavail / total) * 100 : 0,
    fetching: total > 0 ? (fetching / total) * 100 : 0,
  }
  const runId = typeof pipeline?.run_id === 'string' ? pipeline.run_id : null
  const pipelineStatus = pipeline?.status
  const currentStage = pipeline?.current_stage
  const hasSummarizableTranscript = useMemo(
    () => Object.values(statusMap).some((v) => v.status === 'done' || v.status === 'skipped'),
    [statusMap],
  )
  const hasCompletedTranscript = useMemo(
    () => Object.values(statusMap).some((v) => v.status === 'done'),
    [statusMap],
  )
  const transcriptsRunning =
    (pipelineStatus === 'running' || pipelineStatus === 'queued') &&
    (currentStage === 'transcripts' || currentStage === 'chunks')
  const summariesRunning =
    (pipelineStatus === 'running' || pipelineStatus === 'queued') &&
    (currentStage === 'summaries' || currentStage === 'profile')
  const transcriptsHalted =
    pipelineStatus === 'cancelled' ||
    (pipelineStatus === 'failed' && (currentStage === 'transcripts' || currentStage === 'chunks'))
  const transcriptStageProgress = !!pipeline?.stages?.transcripts
  const summariesAlreadyStarted = !!pipeline?.stages?.summaries
  const transcriptsNeverStarted =
    !pipelineStatus ||
    pipelineStatus === 'idle' ||
    (!transcriptStageProgress && !hasSummarizableTranscript)
  const showStartGate =
    stage === 'transcripts' &&
    !transcriptsRunning &&
    pipelineStatus !== 'awaiting_confirm_summaries' &&
    (transcriptsNeverStarted || (transcriptsHalted && !hasSummarizableTranscript))
  const canSummarize =
    hasCompletedTranscript &&
    (pipelineStatus === 'awaiting_confirm_summaries' || transcriptsHalted)
  const showSummarizeFromTranscripts =
    stage === 'transcripts' && !showStartGate && !transcriptsRunning && canSummarize
  const showResumeTranscriptsBtn =
    stage === 'transcripts' && transcriptsHalted && hasSummarizableTranscript
  const showCostGate =
    stage === 'summaries' &&
    !summariesRunning &&
    !summariesAlreadyStarted &&
    hasCompletedTranscript &&
    (pipelineStatus === 'awaiting_confirm_summaries' ||
      pipelineStatus === 'cancelled' ||
      pipelineStatus === 'failed')
  const partialTranscripts = transcriptsHalted && hasSummarizableTranscript
  const activeRows = rows.filter((r) => r.status === 'fetching')
  const extraActive = Math.max(0, activeRows.length - 3)
  const etaMin = stage === 'transcripts' ? 4 : 6

  const handleCancel = async () => {
    await confirm({
      title: 'Cancel pipeline run',
      message: 'Stop the current run? Completed work will be kept.',
      confirmLabel: 'Cancel run',
      cancelLabel: 'Keep running',
      variant: 'danger',
      action: async () => {
        const res = await api.pipelineCancel(channel.channel_id)
        if (!res.ok) throw new Error(res.error || 'Could not cancel run')
      },
    })
  }

  const handleStart = async () => {
    setStarting(true)
    setControlError(null)
    const res = await api.pipelineStart(channel.channel_id)
    setStarting(false)
    if (!res.ok) setControlError(res.error || 'Could not start transcription.')
  }

  const handleRetryFailed = async () => {
    if (!runId) {
      setControlError('No retryable run found.')
      return
    }
    setRetrying(true)
    setControlError(null)
    const res = await api.retryFailed(runId)
    setRetrying(false)
    if (!res.ok) setControlError(res.error || 'Retry failed.')
  }

  const handleResume = async () => {
    setResuming(true)
    setControlError(null)
    const res = await api.pipelineResume(channel.channel_id)
    setResuming(false)
    if (!res.ok) setControlError(res.error || 'Could not start summaries.')
  }

  if (loading) {
    return <WorkspaceLoading label="Loading pipeline state" />
  }

  return (
    <div className="studio-scroll">
      <div className="studio-panel narrow">
        {isError && (
          <div className="studio-error-card">
            <Icons.Warn />
            <div>
              <b>{stage === 'transcripts' ? 'Transcripts' : 'Summaries'} step failed.</b>
              <p>{pipeline?.error || `${failed} videos could not be processed. Retry the failed batch or return to video selection.`}</p>
            </div>
            <button type="button" className="btn-primary-sm" disabled={retrying || !runId} onClick={handleRetryFailed}>
              {retrying ? <span className="studio-spinner" /> : <Icons.Refresh />}
              Retry {failed > 0 ? `${failed} failed` : 'batch'}
            </button>
          </div>
        )}

        <div className="studio-progress-panel">
          <div className="studio-progress-head">
            <div className="studio-progress-head-text">
              <div className="studio-progress-eyebrow">
                <span className="studio-progress-eyebrow-mark" aria-hidden />
                {stage === 'transcripts' ? 'Transcripts' : 'Summaries'}
              </div>
              <h2 className="studio-progress-title">
                {showStartGate
                  ? 'Ready to transcribe.'
                  : showCostGate
                    ? 'Ready to synthesize.'
                    : stage === 'transcripts'
                      ? transcriptsHalted
                        ? 'Transcription stopped.'
                        : 'Fetching captions and falling back to ASR.'
                      : 'Distilling each transcript into themes.'}
              </h2>
              <p className="studio-progress-blurb">
                {showStartGate
                  ? 'Captions are pulled from YouTube when available, with automatic transcription as fallback. You can cancel any time.'
                  : showCostGate
                    ? partialTranscripts
                      ? 'Transcription was stopped before finishing. Only videos with completed transcripts will be summarized.'
                      : 'Transcripts are ready. Summaries will turn each one into themes, claims, tone, and evidence — cited back to source.'
                    : stage === 'transcripts'
                      ? transcriptsHalted
                        ? hasSummarizableTranscript
                          ? 'Some videos finished, others did not. Resume to fetch the rest, or jump to summaries with what you have.'
                          : 'No transcripts completed. Restart to fetch them.'
                        : "Each video gets its caption track when available, then automatic transcription where YouTube doesn't expose one."
                      : 'Synthesis is incremental — answers in chat get smarter as each summary lands.'}
              </p>
            </div>
            {transcriptsRunning && stage === 'transcripts' && (
              <button type="button" className="studio-progress-cancel" onClick={handleCancel}>
                Cancel run
              </button>
            )}
            {summariesRunning && stage === 'summaries' && !showCostGate && (
              <button type="button" className="studio-progress-cancel" onClick={handleCancel}>
                Cancel run
              </button>
            )}
            {(() => {
              const showRetryFailed =
                stage === 'transcripts' && !transcriptsRunning && !showStartGate && failed > 0 && !!runId
              if (!showRetryFailed && (showStartGate || showCostGate || (!showSummarizeFromTranscripts && !showResumeTranscriptsBtn))) return null
              return (
                <div className="studio-progress-head-actions">
                  {showRetryFailed && (
                    <button type="button" className="btn-secondary-sm" onClick={handleRetryFailed} disabled={retrying}>
                      {retrying ? <span className="studio-spinner" /> : <Icons.Refresh />}
                      Retry {failed} failed
                    </button>
                  )}
                  {showResumeTranscriptsBtn && (
                    <button type="button" className="btn-secondary-sm" onClick={handleStart} disabled={starting}>
                      {starting ? <span className="studio-spinner" /> : null}
                      Resume transcription
                    </button>
                  )}
                  {showSummarizeFromTranscripts && (
                    <button type="button" className="studio-cost-cta studio-summarize-glow" onClick={onSwitchToSummaries}>
                      {partialTranscripts ? 'Summarize what we have ' : 'Summarize '}<Icons.Arrow />
                    </button>
                  )}
                </div>
              )
            })()}
          </div>

          {controlError && <div className="studio-form-error">{controlError}</div>}

          {showStartGate ? (
            <div className="studio-cost-gate">
              <div className="studio-cost-eyebrow">
                <span className="studio-cost-eyebrow-dot" aria-hidden />
                Confirm to proceed · transcripts
              </div>
              <h3 className="studio-cost-title">Transcription is free but takes time.</h3>
              <p className="studio-cost-blurb">
                We pull YouTube captions when available, then fall back to automatic transcription for the rest. You can cancel mid-run; finished transcripts are kept.
              </p>
              <div className="studio-cost-actions">
                <button type="button" className="btn-secondary-sm" onClick={onBackToVideos}>Back to videos</button>
                <button type="button" className="studio-cost-cta" onClick={handleStart} disabled={starting}>
                  {starting ? <span className="studio-spinner" /> : null}
                  Start transcription <Icons.Arrow />
                </button>
              </div>
            </div>
          ) : showCostGate && cost ? (
            <div className="studio-cost-gate">
              <div className="studio-cost-eyebrow">
                <span className="studio-cost-eyebrow-dot" aria-hidden />
                Confirm to proceed · summaries
              </div>
              <h3 className="studio-cost-title">Summaries cost money to generate.</h3>
              <p className="studio-cost-blurb">
                Each transcript is sent to the model for theme, claim, and tone synthesis. You can cancel mid-run, but spent minutes don't refund.
              </p>
              <div className="studio-cost-grid">
                <div className="studio-cost-cell">
                  <div className="studio-cost-num">${cost.estimated_cost_usd.toFixed(2)}</div>
                  <div className="studio-cost-key">Estimated</div>
                </div>
                <div className="studio-cost-cell">
                  <div className="studio-cost-num">{Math.ceil(cost.estimated_transcript_seconds / 60)}<span>m</span></div>
                  <div className="studio-cost-key">Transcript</div>
                </div>
                <div className="studio-cost-cell">
                  <div className="studio-cost-num">{cost.video_count}</div>
                  <div className="studio-cost-key">Videos</div>
                </div>
              </div>
              <div className="studio-cost-actions">
                <button type="button" className="btn-secondary-sm" onClick={onBackToVideos}>Back to videos</button>
                <button type="button" className="studio-cost-cta" onClick={handleResume} disabled={resuming}>
                  {resuming ? <span className="studio-spinner" /> : null}
                  Start summaries <Icons.Arrow />
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="studio-progress-headline">
                <div className="studio-progress-counter">
                  <span className="studio-progress-counter-done">{completed}</span>
                  <span className="studio-progress-counter-sep">/</span>
                  <span className="studio-progress-counter-total">{total}</span>
                  <span className="studio-progress-counter-pct">{pct}<i>%</i></span>
                </div>

                <div className="studio-progress-meter" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                  {seg.done > 0     && <span className="studio-progress-seg is-done"     style={{ width: `${seg.done}%` }} />}
                  {seg.failed > 0   && <span className="studio-progress-seg is-failed"   style={{ width: `${seg.failed}%` }} />}
                  {seg.unavail > 0  && <span className="studio-progress-seg is-unavail"  style={{ width: `${seg.unavail}%` }} />}
                  {seg.fetching > 0 && <span className="studio-progress-seg is-fetching" style={{ width: `${seg.fetching}%` }} />}
                </div>

                <div className="studio-progress-legend">
                  <span className="studio-progress-leg-item">
                    <span className="studio-progress-leg-sw is-done" /><b>{done}</b> done
                  </span>
                  {failed > 0 && (
                    <span className="studio-progress-leg-item">
                      <span className="studio-progress-leg-sw is-failed" /><b>{failed}</b> failed
                    </span>
                  )}
                  {unavail > 0 && (
                    <span className="studio-progress-leg-item">
                      <span className="studio-progress-leg-sw is-unavail" /><b>{unavail}</b> unavailable
                    </span>
                  )}
                  <span className="studio-progress-leg-item">
                    <span className="studio-progress-leg-sw is-fetching" /><b>{fetching}</b> running
                  </span>
                  <span className="studio-progress-leg-item is-muted">
                    <span className="studio-progress-leg-sw is-queued" /><b>{queued}</b> queued
                  </span>
                  <span className="studio-progress-leg-spacer" />
                  {failed > 0 && runId && (
                    <button className="studio-progress-leg-action" type="button" onClick={handleRetryFailed} disabled={retrying}>
                      <Icons.Refresh /> Retry {failed} failed
                    </button>
                  )}
                  {fetching > 0 && (
                    <span className="studio-progress-leg-eta">
                      ETA <b>~{etaMin} min</b>
                    </span>
                  )}
                </div>
              </div>

              {fetching > 0 && (
                <div className="studio-progress-now">
                  <div className="studio-progress-section-head">
                    <span className="studio-progress-section-eyebrow">Now processing</span>
                    <span className="studio-progress-section-meta">
                      <span className="studio-progress-pulse" aria-hidden />
                      {fetching} active
                    </span>
                  </div>
                  <div className="studio-progress-now-rows">
                    {activeRows.slice(0, 3).map((row) => (
                      <div key={row.id} className="studio-progress-now-row">
                        <img src={row.thumbnail} alt="" loading="lazy" />
                        <div className="studio-progress-now-body">
                          <div className="studio-progress-now-title">{row.title}</div>
                          <div className="studio-progress-now-sub">
                            <span className="studio-progress-now-dot" aria-hidden />
                            {row.subLabel}{row.subPct !== undefined ? ` · ${row.subPct}%` : ''}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                  {extraActive > 0 && (
                    <div className="studio-progress-now-more">+{extraActive} more in flight</div>
                  )}
                </div>
              )}

              <div className="studio-work">
                <div className="studio-progress-section-head">
                  <span className="studio-progress-section-eyebrow">Timeline</span>
                  <span className="studio-progress-section-meta studio-work-head-meta">
                    <span>{completed} of {total}</span>
                    <span className="studio-work-head-sep" />
                    <span>scroll</span>
                  </span>
                </div>
                <div className="studio-work-list">
                  {rows.map((r) => {
                    const pill = STATUS_PILL[r.status] ?? STATUS_PILL.queued
                    return (
                      <div key={r.id} className={`studio-work-row is-${r.status}`}>
                        <span className="studio-work-idx">{String(r.idx).padStart(2, '0')}</span>
                        <img src={r.thumbnail} alt="" loading="lazy" />
                        <span className="studio-work-title">{r.title}</span>
                        <span className="studio-work-sub">{r.subLabel}</span>
                        <span className={`studio-work-pill ${pill.cls}`}>
                          <span className="studio-work-pill-dot" />
                          {pill.label}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>

              <div className="studio-progress-foot">
                {cost && (
                  <>
                    <span className="studio-progress-foot-key">Run cost so far</span>
                    <span className="studio-progress-foot-val">
                      ${(cost.estimated_cost_usd * (completed / Math.max(1, total))).toFixed(2)}
                      <i> of ${cost.estimated_cost_usd.toFixed(2)} est.</i>
                    </span>
                  </>
                )}
                <span className="studio-progress-foot-spacer" />
                <button className="studio-progress-foot-link" type="button" onClick={onBackToVideos}>Back to videos</button>
                {runId && (
                  <>
                    <span className="studio-progress-foot-sep" />
                    <span className="studio-progress-foot-runid">{runId}</span>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>
      {confirmDialog}
    </div>
  )
}

function ProfileSummaryPanel({
  channel,
  onStartChat,
  onOpenVideos,
}: {
  channel: ChannelMeta
  onStartChat: (seed?: string) => void
  onOpenVideos: () => void
}) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.profile(channel.channel_id).then((res) => {
      if (cancelled) return
      if (!res.ok || !res.data) {
        setError(res.error || 'Failed to load profile.')
        setLoading(false)
        return
      }
      setProfile(res.data)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [channel.channel_id])

  if (loading) {
    return <WorkspaceLoading label="Loading profile" />
  }

  if (error || !profile) {
    return (
      <div className="studio-centered">
        <div className="studio-resolve-card">
          <h2>No profile yet</h2>
          <p>{error || 'Finish the pipeline to see a profile summary.'}</p>
          <button type="button" className="studio-btn primary" onClick={onOpenVideos}>Back to videos</button>
        </div>
      </div>
    )
  }

  const claims = profileClaims(profile)
  const suggestions = [
    profile.rollups.all_themes[0] ? `How does ${profile.channel_name} think about ${profile.rollups.all_themes[0].theme}?` : '',
    profile.rollups.all_themes[1] ? `How has ${profile.channel_name}'s view on ${profile.rollups.all_themes[1].theme} changed?` : '',
    profile.rollups.all_referenced[0] ? `What does ${profile.channel_name} say about ${profile.rollups.all_referenced[0].name}?` : '',
    `Summarize the most distinctive opinions from ${profile.channel_name}.`,
  ].filter(Boolean)
  const dateCaption = profile.date_range.first && profile.date_range.last
    ? `${formatMonthYear(profile.date_range.first)} - ${formatMonthYear(profile.date_range.last)}`
    : 'No date range'

  return (
    <div className="studio-scroll">
      <div className="studio-profile">
        <div className="studio-profile-hero">
          <div>
            <div className="studio-eyebrow">Profile ready</div>
            <h1>{profile.channel_name}</h1>
            <p>{profile.video_count.toLocaleString()} videos · {dateCaption} · generated {formatShortDate(profile.generated_at.slice(0, 10).replaceAll('-', ''))}</p>
          </div>
          <button type="button" className="studio-btn primary" onClick={() => onStartChat()}>
            <Icons.Spark />
            Start chatting
          </button>
        </div>

        <div className="studio-profile-grid">
          <div className="studio-profile-card">
            <div className="studio-eyebrow">Top themes</div>
            <div className="studio-pill-cloud">
              {profile.rollups.all_themes.slice(0, 10).map((theme) => (
                <button key={theme.theme} type="button" onClick={() => onStartChat(`What evidence supports the theme "${theme.theme}"?`)}>
                  {theme.theme}<span>{theme.count}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="studio-profile-card">
            <div className="studio-eyebrow">References</div>
            <div className="studio-pill-cloud muted">
              {profile.rollups.all_referenced.slice(0, 10).map((ref) => (
                <button key={ref.name} type="button" onClick={() => onStartChat(`What does ${profile.channel_name} say about ${ref.name}?`)}>
                  {ref.name}<span>{ref.count}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {claims.length > 0 && (
          <div className="studio-profile-card">
            <div className="studio-eyebrow">Signature claims</div>
            <div className="studio-claim-list">
              {claims.map((claim) => (
                <button key={`${claim.video.video_id}-${claim.startSeconds}-${claim.text}`} type="button" onClick={() => onStartChat(`Show evidence for this claim: ${claim.text}`)}>
                  <b>{claim.text}</b>
                  <span>{claim.video.title} · {formatTimestamp(claim.startSeconds)}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="studio-profile-card">
          <div className="studio-eyebrow">Start with</div>
          <div className="studio-suggestions">
            {suggestions.map((suggestion) => (
              <button key={suggestion} type="button" onClick={() => onStartChat(suggestion)}>
                <Icons.Arrow />
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function WorkspaceLoading({ label, compact = false }: { label: string; compact?: boolean }) {
  return (
    <div className={compact ? 'studio-empty-state' : 'studio-centered'}>
      <div className="studio-loading">
        <span className="studio-spinner" />
        {label}
      </div>
    </div>
  )
}
