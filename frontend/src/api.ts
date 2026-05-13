import type {
  ApiResponse,
  ChannelList,
  ChannelMeta,
  ChannelRefreshResult,
  ChatSessionDetail,
  ChatSessionSummary,
  PlaylistList,
  PlaylistVideos,
  PipelineState,
  PipelineCost,
  Profile,
  RetryFailedResult,
  Selection,
  UsageSummary,
  VideoList,
  WaitlistJoinResult,
} from './types'
import { getAccessToken } from './authState'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''

function isPublicApiPath(path: string) {
  return path === '/api/health' || path === '/api/ready' || path === '/api/waitlist'
}

function apiUrl(path: string) {
  return `${apiBaseUrl}${path}`
}

function authHeaders(path: string, headers?: HeadersInit) {
  const next = new Headers(headers)
  if (!isPublicApiPath(path)) {
    const token = getAccessToken()
    if (!token) {
      throw new Error('Not authenticated')
    }
    next.set('Authorization', `Bearer ${token}`)
  }
  return next
}

export async function apiFetch(path: string, init: RequestInit = {}) {
  return fetch(apiUrl(path), {
    ...init,
    headers: authHeaders(path, init.headers),
  })
}

export async function apiStreamFetch(path: string, init: RequestInit = {}) {
  return apiFetch(path, init)
}

async function apiPost<T>(path: string, body: unknown): Promise<ApiResponse<T>> {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  const res = await apiFetch(path, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  return res.json()
}

async function apiGet<T>(path: string): Promise<ApiResponse<T>> {
  const res = await apiFetch(path)
  return res.json()
}

async function apiDelete<T>(path: string): Promise<ApiResponse<T>> {
  const res = await apiFetch(path, { method: 'DELETE' })
  return res.json()
}

async function apiPatch<T>(path: string, body: unknown): Promise<ApiResponse<T>> {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  const res = await apiFetch(path, {
    method: 'PATCH',
    headers,
    body: JSON.stringify(body),
  })
  return res.json()
}

export const api = {
  health: () => apiGet<{ ok: boolean }>('/api/health'),
  waitlistJoin: (email: string, youtubeChannel?: string) =>
    apiPost<WaitlistJoinResult>('/api/waitlist', {
      email,
      youtube_channel: youtubeChannel || null,
    }),
  channel: (url: string) => apiPost<ChannelMeta>('/api/channel', { url }),
  videos: (channelId: string) => apiGet<VideoList>(`/api/videos?channel_id=${channelId}`),
  selection: (channelId: string) => apiGet<Selection>(`/api/selection?channel_id=${channelId}`),
  selectVideos: (channelId: string, videoIds: string[]) =>
    apiPost<Selection>('/api/videos/select', { channel_id: channelId, video_ids: videoIds }),
  pipelineState: (channelId: string) => apiGet<PipelineState>(`/api/pipeline/state?channel_id=${channelId}`),
  pipelineStart: (channelId: string) =>
    apiPost<{ channel_id: string; status: string }>('/api/pipeline/start', { channel_id: channelId }),
  pipelineCost: (channelId: string) =>
    apiGet<PipelineCost>(`/api/pipeline/cost?channel_id=${channelId}`),
  usageSummary: () => apiGet<UsageSummary>('/api/usage/summary'),
  pipelineCancel: (channelId: string) =>
    apiPost<{ status: string }>('/api/pipeline/cancel', { channel_id: channelId }),
  pipelineResume: (channelId: string) =>
    apiPost<{ channel_id: string; status: string }>('/api/pipeline/resume', { channel_id: channelId }),
  profile: (channelId: string) => apiGet<Profile>(`/api/profile?channel_id=${channelId}`),
  playlists: (channelId: string) => apiGet<PlaylistList>(`/api/playlists?channel_id=${channelId}`),
  playlistVideos: (channelId: string, playlistId: string) =>
    apiGet<PlaylistVideos>(`/api/playlists/videos?channel_id=${channelId}&playlist_id=${playlistId}`),
  channels: () => apiGet<ChannelList>('/api/channels'),
  chatSessions: (channelId: string) =>
    apiGet<{ channel_id: string; sessions: ChatSessionSummary[] }>(`/api/channels/${channelId}/chat-sessions`),
  createChatSession: (channelId: string, title?: string) =>
    apiPost<ChatSessionSummary>(`/api/channels/${channelId}/chat-sessions`, { title: title || null }),
  chatSession: (channelId: string, sessionId: string) =>
    apiGet<ChatSessionDetail>(`/api/channels/${channelId}/chat-sessions/${sessionId}`),
  renameChatSession: (channelId: string, sessionId: string, title: string) =>
    apiPatch<ChatSessionSummary>(`/api/channels/${channelId}/chat-sessions/${sessionId}`, { title }),
  deleteChatSession: (channelId: string, sessionId: string) =>
    apiDelete<{ id: string; deleted: boolean }>(`/api/channels/${channelId}/chat-sessions/${sessionId}`),
  deleteChannel: (channelId: string) =>
    apiDelete<{ channel_id: string; deleted: boolean }>(`/api/channels/${channelId}`),
  refreshChannel: (channelId: string) =>
    apiPost<ChannelRefreshResult>(`/api/channels/${channelId}/refresh`, {}),
  retryFailed: (runId: string) =>
    apiPost<RetryFailedResult>(`/api/pipeline/runs/${runId}/retry-failed`, {}),
  exportMarkdownUrl: (channelId: string) => apiUrl(`/api/channels/${channelId}/export/markdown`),
  fetchExportMarkdown: async (channelId: string): Promise<{ ok: boolean; blob?: Blob; filename?: string; error?: string }> => {
    let res: Response
    try {
      res = await apiFetch(`/api/channels/${channelId}/export/markdown`, { method: 'POST' })
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : 'Export failed' }
    }
    const contentType = res.headers.get('Content-Type') || ''
    if (contentType.includes('application/json')) {
      try {
        const body = await res.json()
        return {
          ok: false,
          error: body?.error || body?.detail || `HTTP ${res.status}`,
        }
      } catch {
        return { ok: false, error: `HTTP ${res.status}` }
      }
    }
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}` }
    }
    const disposition = res.headers.get('Content-Disposition') || ''
    const match = /filename="([^"]+)"/.exec(disposition)
    const filename = match?.[1] || `${channelId}.md`
    const blob = await res.blob()
    return { ok: true, blob, filename }
  },
}
