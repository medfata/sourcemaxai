export interface ApiResponse<T> {
  ok: boolean
  data?: T
  error?: string
}

export interface ChannelMeta {
  channel_id: string
  channel_name: string
  channel_handle: string | null
  avatar_url: string | null
}

export interface Video {
  id: string
  title: string
  upload_date: string
  duration: number
  view_count: number
  thumbnail: string
  is_short: boolean
}

export interface Playlist {
  id: string
  title: string
  video_count: number
  thumbnail: string | null
}

export interface PlaylistList {
  channel_id: string
  playlists: Playlist[]
}

export interface PlaylistVideos {
  playlist_id: string
  video_ids: string[]
}

export interface VideoList {
  channel_id: string
  videos: Video[]
}

export interface Selection {
  channel_id: string
  video_ids: string[]
}

export type StageId =
  | 'channel_input'
  | 'video_list'
  | 'transcripts'
  | 'summaries'
  | 'profile'
  | 'chat'

export type StageStatus = 'pending' | 'active' | 'done' | 'error'

export interface Stage {
  id: StageId
  label: string
  status: StageStatus
}

export const STAGES: Stage[] = [
  { id: 'channel_input', label: 'Channel', status: 'pending' },
  { id: 'video_list', label: 'Videos', status: 'pending' },
  { id: 'transcripts', label: 'Transcripts', status: 'pending' },
  { id: 'summaries', label: 'Summaries', status: 'pending' },
  { id: 'profile', label: 'Profile', status: 'pending' },
  { id: 'chat', label: 'Chat', status: 'pending' },
]

export interface ThemeCount {
  theme: string
  count: number
}

export interface ReferencedCount {
  name: string
  count: number
}

export interface ProfileRollups {
  all_themes: ThemeCount[]
  all_referenced: ReferencedCount[]
  tone_distribution: Record<string, number>
}

export interface ProfileDateRange {
  first: string | null
  last: string | null
}

export interface Evidence {
  start_seconds: number
  quote: string
}

export interface Claim {
  text: string
  evidence: Evidence[]
}

export interface ProfileVideo {
  video_id: string
  title: string
  upload_date: string
  core_topic: string
  key_claims: Claim[]
  recurring_themes: string[]
  tone_markers: string[]
  notable_opinions: Claim[]
  people_or_things_referenced: string[]
}

export interface Profile {
  channel_id: string
  channel_name: string
  channel_handle: string | null
  avatar_url: string | null
  video_count: number
  date_range: ProfileDateRange
  videos: ProfileVideo[]
  rollups: ProfileRollups
  generated_at: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}
