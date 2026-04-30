interface ProgressStatsProps {
  total: number
  done: number
  failed: number
  unavailable?: number
  startedAt?: string
}

function formatETA(seconds: number): string {
  if (seconds < 60) return `~${Math.round(seconds)} sec left`
  return `~${Math.round(seconds / 60)} min left`
}

export default function ProgressStats({ total, done, failed, unavailable, startedAt }: ProgressStatsProps) {
  const completed = done + (failed ?? 0) + (unavailable ?? 0)
  const elapsedSec = startedAt
    ? (Date.now() - new Date(startedAt).getTime()) / 1000
    : 0
  const etaSec = completed > 0 && elapsedSec > 0
    ? (elapsedSec / completed) * (total - completed)
    : null

  return (
    <div className="flex flex-wrap gap-3">
      <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-ios-blue/10 text-ios-blue text-[13px] font-medium">
        <span className="font-semibold">{completed}</span>
        <span className="text-ios-text-secondary">/</span>
        <span>{total}</span>
      </div>
      <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-ios-green/10 text-ios-green text-[13px] font-medium">
        {done} done
      </div>
      {failed > 0 && (
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-ios-red/10 text-ios-red text-[13px] font-medium">
          {failed} failed
        </div>
      )}
      {(unavailable ?? 0) > 0 && (
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-yellow-100 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400 text-[13px] font-medium">
          {unavailable} unavailable
        </div>
      )}
      {etaSec !== null && etaSec > 0 && (
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-black/[0.04] dark:bg-white/[0.06] text-ios-text-secondary text-[13px] font-medium">
          {formatETA(etaSec)}
        </div>
      )}
    </div>
  )
}