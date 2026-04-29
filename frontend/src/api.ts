import type { ApiResponse, ChannelMeta, Profile, Selection, VideoList } from './types'

async function apiPost<T>(path: string, body: unknown): Promise<ApiResponse<T>> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return res.json()
}

async function apiGet<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(path)
  return res.json()
}

export const api = {
  health: () => apiGet<{ ok: boolean }>('/api/health'),
  channel: (url: string) => apiPost<ChannelMeta>('/api/channel', { url }),
  videos: (channelId: string) => apiGet<VideoList>(`/api/videos?channel_id=${channelId}`),
  selection: (channelId: string) => apiGet<Selection>(`/api/selection?channel_id=${channelId}`),
  selectVideos: (channelId: string, videoIds: string[]) =>
    apiPost<Selection>('/api/videos/select', { channel_id: channelId, video_ids: videoIds }),
  pipelineState: (channelId: string) => apiGet<any>(`/api/pipeline/state?channel_id=${channelId}`),
  pipelineCost: (channelId: string) =>
    apiGet<{ estimated_cost_usd: number; video_count: number; total_input_tokens: number }>(
      `/api/pipeline/cost?channel_id=${channelId}`
    ),
  pipelineCancel: (channelId: string) =>
    apiPost<{ status: string }>('/api/pipeline/cancel', { channel_id: channelId }),
  pipelineResume: (channelId: string) =>
    apiPost<{ channel_id: string; status: string }>('/api/pipeline/resume', { channel_id: channelId }),
  profile: (channelId: string) => apiGet<Profile>(`/api/profile?channel_id=${channelId}`),
}
