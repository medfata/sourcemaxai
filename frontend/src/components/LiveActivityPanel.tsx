

interface ActivityItem {
  videoId: string
  title: string
  status: 'fetching' | 'done' | 'failed' | 'unavailable' | 'skipped'
  ts: number
}

interface LiveActivityPanelProps {
  activeItems: ActivityItem[]
  recentLog: ActivityItem[]
  verb: string
}

function TypingDots() {
  return (
    <span className="inline-flex gap-0.5 items-center">
      <span className="w-1 h-1 rounded-full bg-ios-blue animate-pulse" style={{ animationDelay: '0ms' }} />
      <span className="w-1 h-1 rounded-full bg-ios-blue animate-pulse" style={{ animationDelay: '150ms' }} />
      <span className="w-1 h-1 rounded-full bg-ios-blue animate-pulse" style={{ animationDelay: '300ms' }} />
    </span>
  )
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function StatusIcon({ status }: { status: ActivityItem['status'] }) {
  if (status === 'done') return <span className="text-ios-green">✓</span>
  if (status === 'failed') return <span className="text-ios-red">✗</span>
  return <span className="text-yellow-500">!</span>
}

export default function LiveActivityPanel({ activeItems, recentLog, verb }: LiveActivityPanelProps) {
  if (activeItems.length === 0 && recentLog.length === 0) {
    return (
      <div className="bg-white dark:bg-ios-card-dark rounded-2xl shadow-ios p-4 text-center text-ios-text-secondary text-[15px]">
        Waiting to start…
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-ios-card-dark rounded-2xl shadow-ios p-4 space-y-3">
      {activeItems.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[12px] font-semibold text-ios-text-secondary uppercase tracking-wider mb-1">
            Active
          </p>
          {activeItems.map((item) => (
            <div key={item.videoId} className="flex items-center gap-2 text-[13px]">
              <TypingDots />
              <span className="text-ios-text-primary dark:text-ios-text-primary-dark">{verb}:</span>
              <span className="truncate min-w-0 text-ios-text-secondary">{item.title}</span>
            </div>
          ))}
        </div>
      )}
      {activeItems.length > 0 && recentLog.length > 0 && (
        <div className="border-t border-black/[0.04] dark:border-white/[0.06]" />
      )}
      {recentLog.length > 0 && (
        <div className="space-y-1">
          <p className="text-[12px] font-semibold text-ios-text-secondary uppercase tracking-wider mb-1">
            Recent
          </p>
          {recentLog.map((item) => (
            <div key={`${item.videoId}-${item.ts}`} className="flex items-center gap-2 text-[13px]">
              <StatusIcon status={item.status} />
              <span className="text-ios-text-secondary font-mono text-[11px]">{formatTime(item.ts)}</span>
              <span className="truncate min-w-0 text-ios-text-primary dark:text-ios-text-primary-dark">{item.title}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export type { ActivityItem }