export interface ApiResponse<T> {
  ok: boolean
  data?: T
  error?: string
}

export interface WaitlistJoinResult {
  email: string
  youtube_channel: string | null
  transcript_minutes: number
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

export interface ChannelSummary {
  channel_id: string
  channel_name: string
  channel_handle: string | null
  avatar_url: string | null
  video_count: number
  has_profile: boolean
  latest_run_status: string | null
  updated_at: string | null
}

export interface ChannelList {
  channels: ChannelSummary[]
}

export interface ChannelRefreshResult {
  channel_id: string
  added: number
  total: number
}

export interface RetryFailedResult {
  run_id: string
  channel_id: string
  retried: number
  status: string
}

export interface UsageRemaining {
  tier_key: string
  display_name: string
  monthly_transcript_seconds: number
  credit_transcript_seconds: number
  transcript_seconds_used: number
  transcript_seconds_remaining: number
  monthly_chat_messages: number
  chat_messages_used: number
  chat_messages_remaining: number
  max_transcript_seconds_per_run: number
  videos_used: number
  monthly_token_limit: number
  tokens_used: number
  tokens_remaining: number
  monthly_cost_limit_usd: number
  cost_used_usd: number
  cost_remaining_usd: number
}

export interface UsageSummary {
  enforced: boolean
  quota: {
    tier_key: string
    display_name: string
    monthly_transcript_seconds: number
    credit_transcript_seconds: number
    monthly_chat_messages: number
    max_transcript_seconds_per_run: number
    monthly_token_limit: number
    monthly_cost_limit_usd: number
    max_concurrent_runs: number
    chat_per_minute_limit: number
  }
  usage: {
    videos: number
    transcript_seconds: number
    chat_messages: number
    input_tokens: number
    output_tokens: number
    total_tokens: number
    cost_usd: number
  }
  remaining: UsageRemaining
}

export interface PipelineCost {
  estimated_cost_usd: number
  estimated_transcript_seconds: number
  video_count: number
  total_input_tokens: number
  selection_count: number
  budget?: UsageRemaining
}

export interface PipelineVideoState {
  status: string
  title?: string
  [key: string]: unknown
}

export interface PipelineStageState {
  status: string
  total?: number
  completed?: number
  videos?: Record<string, PipelineVideoState>
}

export interface PipelineState {
  run_id?: string
  status: string
  current_stage?: string
  stages?: Record<string, PipelineStageState>
  error?: string
  started_at?: string
  completed_at?: string
  generated_files?: unknown
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
  sources?: ChatSource[]
  unknownSourceIds?: string[]
  id?: string
  created_at?: string
  sequence?: number
}

export interface ChatSource {
  source_id: string
  kind?: string
  chunk_id?: string
  video_id: string
  title?: string
  upload_date?: string
  start_seconds: number
  end_seconds?: number
  quote?: string
}

export interface ChatSessionSummary {
  id: string
  channel_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface PersistedChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources: ChatSource[]
  unknown_source_ids: string[]
  created_at: string
  sequence: number
}

export interface ChatSessionDetail {
  session: ChatSessionSummary
  messages: PersistedChatMessage[]
}
