import { useState } from 'react'
import { api } from '../api'
import type { ChannelMeta } from '../types'

interface ChannelInputPageProps {
  onResolved: (meta: ChannelMeta) => void
}

const EXAMPLES = [
  'https://www.youtube.com/@mkbhd',
  'https://www.youtube.com/channel/UCBJycsmduvYEL83R_U4JriQ',
]

export default function ChannelInputPage({ onResolved }: ChannelInputPageProps) {
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!url.trim()) {
      setError('Please enter a URL')
      return
    }
    setLoading(true)
    const res = await api.channel(url.trim())
    setLoading(false)
    if (res.ok && res.data) {
      onResolved(res.data)
    } else {
      setError(res.error || 'Could not resolve channel')
    }
  }

  return (
    <div className="min-h-[calc(100svh-64px)] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <h1 className="text-[34px] font-bold tracking-tight text-ios-text-primary dark:text-ios-text-primary-dark text-center mb-2">
          Profile a channel
        </h1>
        <p className="text-ios-text-secondary text-[17px] text-center mb-8">
          Paste a YouTube channel URL to get started
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <input
              type="text"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value)
                if (error) setError('')
              }}
              placeholder="Paste a YouTube channel URL"
              className="w-full h-[52px] px-4 rounded-2xl bg-white dark:bg-ios-card-dark text-ios-text-primary dark:text-ios-text-primary-dark placeholder:text-ios-text-secondary outline-none focus:ring-2 focus:ring-ios-blue transition-shadow text-[17px]"
            />
            {error && (
              <p className="mt-2 text-ios-red text-[13px]">{error}</p>
            )}
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full h-[52px] rounded-2xl bg-ios-blue text-white font-semibold text-[17px] active:scale-[0.98] active:opacity-90 transition disabled:opacity-50 disabled:active:scale-100"
          >
            {loading ? 'Resolving…' : 'Continue'}
          </button>
        </form>

        <div className="mt-6 text-center">
          <p className="text-ios-text-secondary text-[13px] mb-2">Or try an example</p>
          <div className="flex flex-wrap justify-center gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => {
                  setUrl(ex)
                  setError('')
                }}
                className="text-ios-blue text-[13px] underline decoration-ios-blue/30 hover:decoration-ios-blue"
              >
                {ex.replace('https://www.youtube.com/', '')}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
