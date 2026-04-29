import { useEffect, useState } from 'react'

import { api } from './api'
import PipelineStepper from './components/PipelineStepper'
import ChannelInputPage from './pages/ChannelInputPage'
import ChatPage from './pages/ChatPage'
import ProfilePage from './pages/ProfilePage'
import SummaryProgressPage from './pages/SummaryProgressPage'
import TranscriptProgressPage from './pages/TranscriptProgressPage'
import VideoListPage from './pages/VideoListPage'
import { useSSE } from './hooks/useSSE'
import type { ChannelMeta, Stage, StageStatus } from './types'
import { STAGES } from './types'

type AppScreen = 'channel_input' | 'video_list' | 'transcript_progress' | 'summary_progress' | 'profile' | 'chat'

function getInitialScreen(): AppScreen {
  const saved = localStorage.getItem('cp_channel_id')
  return saved ? 'video_list' : 'channel_input'
}

function App() {
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [screen, setScreen] = useState<AppScreen>(getInitialScreen)
  const [channel, setChannel] = useState<ChannelMeta | null>(null)
  const [stages, setStages] = useState<Stage[]>(STAGES)

  const channelId = channel?.channel_id ?? null
  const { state: pipelineState } = useSSE(channelId)

  useEffect(() => {
    fetch('/api/health')
      .then((res) => res.json())
      .then((data) => setHealthy(data.ok === true))
      .catch(() => setHealthy(false))
  }, [])

  useEffect(() => {
    const savedId = localStorage.getItem('cp_channel_id')
    const savedName = localStorage.getItem('cp_channel_name')
    const savedHandle = localStorage.getItem('cp_channel_handle')
    const savedAvatar = localStorage.getItem('cp_channel_avatar')
    if (savedId && savedName) {
      const meta: ChannelMeta = {
        channel_id: savedId,
        channel_name: savedName,
        channel_handle: savedHandle,
        avatar_url: savedAvatar,
      }
      setChannel(meta)

      // Restore pipeline stage state without opening SSE
      api.pipelineState(savedId).then((res) => {
        if (!res.ok || !res.data) return
        const state = res.data
        const transcriptStatus = state.stages?.transcripts?.status
        const summaryStatus = state.stages?.summaries?.status
        const profileStatus = state.stages?.profile?.status
        const currentStage = state.current_stage
        const pipelineStatus = state.status

        const nextStages: Stage[] = STAGES.map((s) => {
          if (s.id === 'channel_input') return { ...s, status: 'done' as StageStatus }
          if (s.id === 'video_list') return { ...s, status: 'done' as StageStatus }
          if (s.id === 'transcripts') {
            if (transcriptStatus === 'done') return { ...s, status: 'done' }
            if (currentStage === 'transcripts' && pipelineStatus === 'running') return { ...s, status: 'active' }
            return { ...s, status: 'pending' }
          }
          const isAwaitingConfirm = pipelineStatus === 'awaiting_confirm_summaries'
          if (s.id === 'summaries') {
            if (summaryStatus === 'done') return { ...s, status: 'done' }
            if (currentStage === 'summaries' && pipelineStatus === 'running') return { ...s, status: 'active' }
            if (isAwaitingConfirm) return { ...s, status: 'active' }
            if (transcriptStatus === 'done') return { ...s, status: 'pending' }
            return { ...s, status: 'pending' }
          }
          if (s.id === 'profile') {
            if (profileStatus === 'done') return { ...s, status: 'done' }
            if (currentStage === 'profile' && pipelineStatus === 'running') return { ...s, status: 'active' }
            if (summaryStatus === 'done') return { ...s, status: 'pending' }
            return { ...s, status: 'pending' }
          }
          return s
        })
        setStages(nextStages)

        // Determine which screen to show based on restored state
        if (pipelineStatus === 'completed' || profileStatus === 'done') {
          setScreen('profile')
        } else if (pipelineStatus === 'running') {
          if (currentStage === 'transcripts') {
            setScreen('transcript_progress')
          } else if (currentStage === 'summaries') {
            setScreen('summary_progress')
          } else if (currentStage === 'profile') {
            // Stay on summary progress while profile runs in background
            setScreen('summary_progress')
          }
        } else if (pipelineStatus === 'awaiting_confirm_summaries') {
          setScreen('summary_progress')
        } else if (pipelineStatus === 'failed') {
          if (summaryStatus === 'done' || currentStage === 'done') {
            setScreen('summary_progress')
          } else if (transcriptStatus === 'done') {
            setScreen('transcript_progress')
          }
        } else if (transcriptStatus === 'done') {
          if (state.stages?.summaries) {
            setScreen('summary_progress')
          } else {
            setScreen('transcript_progress')
          }
        }
      })
    }
  }, [])

  // Auto-advance to profile when backend finishes aggregation
  useEffect(() => {
    if (!pipelineState) return
    const profileStatus = pipelineState.stages?.profile?.status
    const pipelineStatus = pipelineState.status
    if (profileStatus === 'done' || pipelineStatus === 'completed') {
      setScreen('profile')
      setStages((prev) =>
        prev.map((s) =>
          s.id === 'profile' ? { ...s, status: 'done' } : s.id === 'summaries' ? { ...s, status: 'done' } : s
        )
      )
    }
  }, [pipelineState])

  const handleResolved = (meta: ChannelMeta) => {
    setChannel(meta)
    localStorage.setItem('cp_channel_id', meta.channel_id)
    localStorage.setItem('cp_channel_name', meta.channel_name)
    if (meta.channel_handle) localStorage.setItem('cp_channel_handle', meta.channel_handle)
    if (meta.avatar_url) localStorage.setItem('cp_channel_avatar', meta.avatar_url)
    setScreen('video_list')
    setStages((prev) =>
      prev.map((s) =>
        s.id === 'channel_input' ? { ...s, status: 'done' } : s.id === 'video_list' ? { ...s, status: 'active' } : s
      )
    )
  }

  const handleRunPipeline = async () => {
    if (!channel) return
    const res = await fetch('/api/pipeline/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel_id: channel.channel_id }),
    })
    const data = await res.json()
    if (data.data?.status === 'started' || data.data?.status === 'already_running') {
      setStages((prev) =>
        prev.map((s) =>
          s.id === 'video_list'
            ? { ...s, status: 'done' }
            : s.id === 'transcripts'
            ? { ...s, status: 'active' }
            : s
        )
      )
      setScreen('transcript_progress')
    }
  }

  const handleTranscriptComplete = () => {
    setStages((prev) =>
      prev.map((s) =>
        s.id === 'transcripts' ? { ...s, status: 'done' } : s.id === 'summaries' ? { ...s, status: 'active' } : s
      )
    )
    setScreen('summary_progress')
  }

  const handleSummaryComplete = () => {
    setStages((prev) =>
      prev.map((s) =>
        s.id === 'summaries' ? { ...s, status: 'done' } : s.id === 'profile' ? { ...s, status: 'active' } : s
      )
    )
    // Do not change screen here; the useEffect watching pipelineState will
    // advance to 'profile' once the backend signals profile is done.
  }

  const handleStageClick = (stage: Stage) => {
    if (stage.id === 'channel_input') {
      setScreen('channel_input')
    } else if (stage.id === 'video_list' && channel) {
      setScreen('video_list')
    } else if (stage.id === 'transcripts' && channel) {
      setScreen('transcript_progress')
    } else if (stage.id === 'summaries' && channel) {
      setScreen('summary_progress')
    } else if (stage.id === 'profile' && channel) {
      setScreen('profile')
    } else if (stage.id === 'chat' && channel) {
      const profileStage = stages.find((s) => s.id === 'profile')
      if (profileStage?.status === 'done') {
        setScreen('chat')
      }
    }
  }

  const handleStartChat = () => {
    setScreen('chat')
    setStages((prev) =>
      prev.map((s) =>
        s.id === 'chat' ? { ...s, status: 'active' } : s
      )
    )
  }

  const handleChatComplete = () => {
    setStages((prev) =>
      prev.map((s) =>
        s.id === 'chat' ? { ...s, status: 'done' } : s
      )
    )
  }

  return (
    <div className="min-h-screen bg-ios-bg dark:bg-black">
      <PipelineStepper stages={stages} onStageClick={handleStageClick} />

      {healthy === false && (
        <div className="bg-ios-red/10 text-ios-red text-center text-[13px] py-2">
          Backend unavailable — is the server running?
        </div>
      )}

      {screen === 'channel_input' && <ChannelInputPage onResolved={handleResolved} />}
      {screen === 'video_list' && channel && (
        <VideoListPage channel={channel} onRunPipeline={handleRunPipeline} />
      )}
      {screen === 'transcript_progress' && channel && (
        <TranscriptProgressPage channel={channel} onComplete={handleTranscriptComplete} onBack={() => setScreen('video_list')} />
      )}
      {screen === 'summary_progress' && channel && (
        <SummaryProgressPage channel={channel} onComplete={handleSummaryComplete} onBack={() => setScreen('video_list')} />
      )}
      {screen === 'profile' && channel && (
        <ProfilePage channel={channel} onBack={() => setScreen('video_list')} onStartChat={handleStartChat} />
      )}
      {screen === 'chat' && channel && (
        <ChatPage channel={channel} onBack={() => setScreen('profile')} onComplete={handleChatComplete} />
      )}
    </div>
  )
}

export default App
