import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'

import { api } from '../api'
import type { ProxyQuotaUsage } from '../types'

interface ProxyQuotaMeterProps {
  refreshKey?: number | string
  onBlocked?: (detail: { used: number; limit: number; tier: string }) => void
}

function formatBytes(bytes: number): string {
  if (bytes <= 0) return '0 B'
  const KB = 1024
  const MB = KB * 1024
  const GB = MB * 1024
  if (bytes >= GB) return `${(bytes / GB).toFixed(bytes >= 10 * GB ? 0 : 1)} GB`
  if (bytes >= MB) return `${(bytes / MB).toFixed(bytes >= 10 * MB ? 0 : 1)} MB`
  if (bytes >= KB) return `${(bytes / KB).toFixed(0)} KB`
  return `${bytes} B`
}

function formatCount(n: number): string {
  if (n >= 1000) return n.toLocaleString('en-US')
  return String(n)
}

function fillColorClass(pct: number): string {
  if (pct >= 90) return 'bg-red-500/80'
  if (pct >= 70) return 'bg-amber-500/80'
  return 'bg-emerald-500/80'
}

export default function ProxyQuotaMeter({ refreshKey, onBlocked }: ProxyQuotaMeterProps) {
  const [usage, setUsage] = useState<ProxyQuotaUsage | null>(null)
  const [loading, setLoading] = useState(true)
  const [hidden, setHidden] = useState(false)
  const mountedRef = useRef(true)

  const fetchUsage = useCallback(async () => {
    let res
    try {
      res = await api.getProxyUsage()
    } catch {
      if (mountedRef.current) {
        setHidden(true)
        setLoading(false)
      }
      return
    }
    if (!mountedRef.current) return
    if (!res.ok || !res.data) {
      setHidden(true)
      setLoading(false)
      return
    }
    setUsage(res.data)
    setLoading(false)
  }, [])

  useEffect(() => {
    mountedRef.current = true
    void fetchUsage()
    return () => {
      mountedRef.current = false
    }
  }, [fetchUsage, refreshKey])

  if (hidden) return null

  if (loading) {
    return (
      <div className="rounded-3xl bg-white/60 dark:bg-white/[0.03] backdrop-blur-md border border-black/[0.06] dark:border-white/10 p-5">
        <div className="h-3 w-40 rounded bg-black/[0.06] dark:bg-white/10 animate-pulse" />
        <div className="mt-4 h-7 w-32 rounded bg-black/[0.06] dark:bg-white/10 animate-pulse" />
        <div className="mt-4 h-1.5 w-full rounded-full bg-black/[0.06] dark:bg-white/10 animate-pulse" />
      </div>
    )
  }

  if (!usage) return null

  if (usage.tier_key === 'free' && usage.proxy_bytes_limit === 0) {
    return null
  }

  const used = Math.max(0, usage.proxy_bytes_used)
  const limit = Math.max(0, usage.proxy_bytes_limit)
  const remaining = Math.max(0, usage.proxy_bytes_remaining)
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0
  const exhausted = remaining === 0 && limit > 0
  const fill = exhausted ? 'bg-red-500/80' : fillColorClass(pct)
  const tierLabel = usage.tier_key.toUpperCase()

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="rounded-3xl bg-white/60 dark:bg-white/[0.03] backdrop-blur-md border border-black/[0.06] dark:border-white/10 p-5"
    >
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-[11px] uppercase tracking-[0.22em] text-ink-400">
          Transcript bandwidth
        </div>
        <div className="text-[11px] uppercase tracking-[0.22em] text-ink-400">{tierLabel}</div>
      </div>
      <div className="mt-3 flex items-end justify-between gap-4">
        <div className="text-[28px] font-display tracking-tight text-ink-900 dark:text-cream">
          {formatBytes(used)}{' '}
          <span className="text-[13px] text-ink-500 dark:text-white/60">/ {formatBytes(limit)}</span>
        </div>
        <div className="text-[13px] text-ink-500 dark:text-white/60">
          {exhausted ? (
            <button
              type="button"
              onClick={() =>
                onBlocked?.({ used, limit, tier: usage.tier_key })
              }
              className="underline-offset-4 hover:underline"
            >
              Limit reached — upgrade for more
            </button>
          ) : (
            <>~{formatCount(usage.estimated_videos_remaining)} videos left</>
          )}
        </div>
      </div>
      <div className="mt-3 h-1.5 rounded-full bg-black/[0.06] dark:bg-white/10 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${fill}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </motion.div>
  )
}
