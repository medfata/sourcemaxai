import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { Bar, BarChart, Cell, LabelList, Pie, PieChart, ResponsiveContainer, XAxis, YAxis, AreaChart, Area, Tooltip } from 'recharts'
import { api } from '../api'
import type { ChannelMeta, Profile, ProfileVideo, ThemeCount } from '../types'
import { formatMonthYear, formatShortDate, formatTimestamp } from '../utils/date'
import { downloadBlob } from '../utils/download'

const CHART_COLORS = ['#D90429', '#FF4D2E', '#FFB020', '#7A1F1F', '#111827', '#F97316', '#EF4444', '#991B1B']

interface ProfilePageProps {
  channel: ChannelMeta
  onBack: () => void
  onStartChat: (seed?: string) => void
}

function SectionLabel({ n, children }: { n: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-3 mb-5">
      <span className="font-mono text-[11px] text-ink-300 dark:text-white/30 uppercase tracking-[0.18em]">{n}</span>
      <span className="h-px flex-1 bg-ink-200 dark:bg-white/10" />
      <h3 className="font-display text-[24px] sm:text-[32px] tracking-tight text-ink-900 dark:text-cream">{children}</h3>
    </div>
  )
}

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white dark:bg-ink-700 rounded-3xl border border-black/[0.05] dark:border-white/10 p-5 sm:p-6 ${className}`}>
      {children}
    </div>
  )
}

function sizeBucket(counts: number[], value: number): 'sm' | 'md' | 'lg' {
  if (counts.length === 0) return 'md'
  const sorted = [...counts].sort((a, b) => a - b)
  const p33 = sorted[Math.floor(sorted.length * 0.33)] ?? sorted[0]
  const p66 = sorted[Math.floor(sorted.length * 0.66)] ?? sorted[sorted.length - 1]
  if (value <= p33) return 'sm'
  if (value >= p66) return 'lg'
  return 'md'
}

function isClaim(x: unknown): x is { text: string; evidence: { start_seconds: number; quote: string }[] } {
  return typeof x === 'object' && x !== null && 'text' in x && 'evidence' in x && Array.isArray((x as any).evidence)
}

function ThemePill({ label, count, counts, selected, onClick }: { label: string; count: number; counts: number[]; selected?: boolean; onClick?: () => void }) {
  const bucket = sizeBucket(counts, count)
  const sizeClasses = { sm: 'text-[11px] px-2.5 py-1', md: 'text-[13px] px-3 py-1.5', lg: 'text-[15px] px-4 py-2' }
  return (
    <button
      onClick={onClick}
      className={`rounded-full font-medium transition-all duration-200 ${sizeClasses[bucket]} ${
        selected
          ? 'bg-ink-900 dark:bg-cream text-cream dark:text-ink-900'
          : 'bg-ink-100 dark:bg-ink-700 text-ink-700 dark:text-white/70 hover:bg-ink-200 dark:hover:bg-ink-600'
      }`}
    >
      {label}
    </button>
  )
}

function ReferencedPill({ label, count, counts }: { label: string; count: number; counts: number[] }) {
  const bucket = sizeBucket(counts, count)
  const sizeClasses = { sm: 'text-[11px] px-2.5 py-1', md: 'text-[13px] px-3 py-1.5', lg: 'text-[15px] px-4 py-2' }
  return (
    <span className={`inline-block rounded-full font-medium bg-ink-100 dark:bg-ink-600 text-ink-700 dark:text-white/70 ${sizeClasses[bucket]}`}>
      {label}
    </span>
  )
}

function ToneBar({ label, count, maxCount }: { label: string; count: number; maxCount: number }) {
  const pct = maxCount > 0 ? (count / maxCount) * 100 : 0
  return (
    <div className="flex items-center gap-3">
      <span className="text-[13px] text-ink-700 dark:text-white/70 w-28 sm:w-36 truncate flex-shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-ink-100 dark:bg-ink-600 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
          className="h-full bg-gradient-aurora rounded-full"
        />
      </div>
      <span className="text-[13px] text-ink-400 font-mono w-8 text-right flex-shrink-0">{count}</span>
    </div>
  )
}

function ThemesBarChart({ themes, selectedThemes, onThemeClick }: { themes: ThemeCount[]; selectedThemes: Set<string>; onThemeClick: (theme: string) => void }) {
  const data = themes.map((t) => ({ name: t.theme, count: t.count }))
  return (
    <div className="min-h-[200px]">
      <ResponsiveContainer width="100%" height={themes.length * 38 + 20}>
        <BarChart data={data as any[]} layout="vertical" margin={{ left: 0, right: 48, top: 4, bottom: 4 }}>
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 12, fill: 'currentColor' }} tickLine={false} axisLine={false} />
          <Bar
            dataKey="count"
            radius={[6, 6, 6, 6]}
            cursor="pointer"
            onClick={(data: any) => { const theme = data?.name; if (theme) onThemeClick(theme) }}
          >
            {data.map((entry, index) => (
              <Cell
                key={entry.name}
                fill={selectedThemes.has(entry.name) ? CHART_COLORS[0] : CHART_COLORS[index % CHART_COLORS.length]}
                opacity={selectedThemes.size === 0 || selectedThemes.has(entry.name) ? 1 : 0.3}
              />
            ))}
            <LabelList dataKey="count" position="right" fill="currentColor" fontSize={12} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function ToneDonutChart({ tones }: { tones: [string, number][] }) {
  const data = tones.map(([name, value]) => ({ name, value }))
  const topTone = tones[0]?.[0] ?? ''
  const total = tones.reduce((sum, [, v]) => sum + v, 0)
  return (
    <div className="min-h-[200px] flex flex-col items-center justify-center">
      <div className="relative w-full" style={{ height: Math.max(180, Math.min(260, tones.length * 40)) }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data as any[]} cx="50%" cy="50%" innerRadius={56} outerRadius={86} paddingAngle={3} dataKey="value">
              {data.map((_entry, index) => (
                <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="font-display text-[20px] text-ink-900 dark:text-cream">{topTone}</span>
          {total > 0 && <span className="text-[11px] font-mono text-ink-400">{tones[0][1]}/{total}</span>}
        </div>
      </div>
      <div className="w-full space-y-1 mt-2">
        {tones.map(([tone, count], i) => (
          <div key={tone} className="flex items-center gap-2 text-[13px]">
            <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }} />
            <span className="truncate text-ink-700 dark:text-white/70">{tone}</span>
            <span className="text-ink-400 ml-auto font-mono">{count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function UploadActivityChart({ data }: { data: { month: string; count: number }[] }) {
  return (
    <div className="min-h-[120px]">
      <ResponsiveContainer width="100%" height={140}>
        <AreaChart data={data as any[]} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="auroraFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#D90429" stopOpacity={0.4} />
              <stop offset="100%" stopColor="#D90429" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <XAxis dataKey="month" tick={{ fontSize: 11, fill: 'currentColor' }} tickLine={false} axisLine={false} className="text-ink-400" />
          <Tooltip contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, fontSize: 13 }} />
          <Area type="monotone" dataKey="count" stroke="#D90429" fill="url(#auroraFill)" strokeWidth={2.5} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

function CitationPill({ videoId, startSeconds }: { videoId: string; startSeconds: number }) {
  return (
    <a
      href={`https://youtu.be/${videoId}?t=${startSeconds}s`}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center text-[11px] font-medium text-accent-red bg-accent-red/10 hover:bg-accent-red/20 rounded-full px-2 py-0.5 ml-1 mr-0.5 align-baseline no-underline transition-colors whitespace-nowrap"
    >
      ↗ {formatTimestamp(startSeconds)}
    </a>
  )
}

function ClaimItem({ text, evidence, videoId }: { text: string; evidence: { start_seconds: number; quote: string }[]; videoId: string }) {
  return (
    <li>
      <span>{text}</span>
      {evidence.map((ev, i) => <CitationPill key={i} videoId={videoId} startSeconds={ev.start_seconds} />)}
    </li>
  )
}

function TimelineRow({ video, index }: { video: ProfileVideo; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const themePills = video.recurring_themes.slice(0, 3)
  const themeOverflow = video.recurring_themes.length - 3

  return (
    <div className={`border-b border-black/[0.04] dark:border-white/[0.06] last:border-0`}>
      <button onClick={() => setExpanded((v) => !v)} className="w-full flex items-center gap-3 px-4 py-3.5 text-left hover:bg-ink-50/60 dark:hover:bg-white/[0.02] transition-colors">
        <span className="text-[12px] font-mono text-ink-300 w-8 flex-shrink-0">{String(index + 1).padStart(2, '0')}</span>
        <span className="text-[12px] text-ink-400 w-20 flex-shrink-0">{formatShortDate(video.upload_date)}</span>
        <span className="flex-1 text-[14px] font-medium text-ink-900 dark:text-cream truncate">{video.title}</span>
        <div className="hidden sm:flex items-center gap-1 flex-shrink-0 max-w-[200px]">
          {themePills.map((t) => (
            <span key={t} className="text-[10px] px-2 py-0.5 rounded-full bg-ink-100 dark:bg-ink-600 text-ink-500 dark:text-white/50 truncate max-w-[100px]">{t}</span>
          ))}
          {themeOverflow > 0 && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-ink-100 dark:bg-ink-600 text-ink-500">+{themeOverflow}</span>
          )}
        </div>
        <span className={`text-ink-300 transition-transform ${expanded ? 'rotate-90' : ''}`}>›</span>
      </button>
      <div className={`overflow-hidden transition-all duration-300 ease-out ${expanded ? 'max-h-[800px] opacity-100' : 'max-h-0 opacity-0'}`}>
        <div className="px-4 pb-5 pt-1 space-y-4">
          <div>
            <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-ink-300 mb-1.5">Core topic</p>
            <p className="text-[14px] text-ink-900 dark:text-cream">{video.core_topic}</p>
          </div>
          {video.key_claims.length > 0 && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-ink-300 mb-1.5">Key claims</p>
              <ul className="list-disc list-inside text-[14px] text-ink-700 dark:text-white/70 space-y-1.5">
                {video.key_claims.map((claim, i) =>
                  isClaim(claim) ? <ClaimItem key={i} text={claim.text} evidence={claim.evidence} videoId={video.video_id} /> : <li key={i}>{String(claim)}</li>
                )}
              </ul>
            </div>
          )}
          {video.recurring_themes.length > 0 && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-ink-300 mb-1.5">Themes</p>
              <div className="flex flex-wrap gap-1.5">
                {video.recurring_themes.map((t) => (
                  <span key={t} className="text-[12px] px-2.5 py-0.5 rounded-full bg-ink-100 dark:bg-ink-600 text-ink-700 dark:text-white/70">{t}</span>
                ))}
              </div>
            </div>
          )}
          {video.notable_opinions.length > 0 && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-ink-300 mb-1.5">Notable opinions</p>
              <ul className="list-disc list-inside text-[14px] text-ink-700 dark:text-white/70 space-y-1.5">
                {video.notable_opinions.map((op, i) =>
                  isClaim(op) ? <ClaimItem key={i} text={op.text} evidence={op.evidence} videoId={video.video_id} /> : <li key={i}>{String(op)}</li>
                )}
              </ul>
            </div>
          )}
          {video.people_or_things_referenced.length > 0 && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-ink-300 mb-1.5">Referenced</p>
              <div className="flex flex-wrap gap-1.5">
                {video.people_or_things_referenced.map((r) => (
                  <span key={r} className="text-[12px] px-2.5 py-0.5 rounded-full bg-ink-100 dark:bg-ink-600 text-ink-700 dark:text-white/70">{r}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function ProfilePage({ channel, onBack, onStartChat }: ProfilePageProps) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedThemes, setSelectedThemes] = useState<Set<string>>(new Set())
  const [timelineOpen, setTimelineOpen] = useState(false)
  const [showAllReferenced, setShowAllReferenced] = useState(false)
  const [showAllThemes, setShowAllThemes] = useState(false)
  const [moreStatsOpen, setMoreStatsOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.profile(channel.channel_id).then((res) => {
      if (cancelled) return
      if (!res.ok) {
        setError(res.error || 'Failed to load profile')
        setLoading(false)
        return
      }
      if (res.data) {
        setProfile(res.data)
        if (res.data.videos.length <= 30) setTimelineOpen(true)
      }
      setLoading(false)
    })
    return () => { cancelled = true }
  }, [channel.channel_id])

  useEffect(() => {
    if (selectedThemes.size > 0) setTimelineOpen(true)
  }, [selectedThemes])

  const toggleTheme = (theme: string) => {
    setSelectedThemes((prev) => {
      const next = new Set(prev)
      if (next.has(theme)) next.delete(theme)
      else next.add(theme)
      return next
    })
  }

  const filteredVideos = useMemo(() => {
    if (!profile) return []
    if (selectedThemes.size === 0) return profile.videos
    return profile.videos.filter((v) => {
      const themes = new Set(v.recurring_themes)
      for (const t of selectedThemes) if (themes.has(t)) return true
      return false
    })
  }, [profile, selectedThemes])

  const themeCounts = useMemo(() => profile?.rollups.all_themes.map((t) => t.count) ?? [], [profile])
  const referencedCounts = useMemo(() => profile?.rollups.all_referenced.map((r) => r.count) ?? [], [profile])

  const toneEntries = useMemo(() => {
    if (!profile) return []
    return Object.entries(profile.rollups.tone_distribution).sort((a, b) => b[1] - a[1])
  }, [profile])

  const maxToneCount = useMemo(() => toneEntries.length === 0 ? 0 : Math.max(...toneEntries.map(([, c]) => c)), [toneEntries])

  const monthlyCounts = useMemo(() => {
    if (!profile) return []
    const map = new Map<string, number>()
    for (const v of profile.videos) {
      const key = v.upload_date.slice(0, 7)
      map.set(key, (map.get(key) ?? 0) + 1)
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([month, count]) => ({ month, count }))
  }, [profile])

  interface AggregatedClaim {
    text: string
    videoId: string
    videoTitle: string
    uploadDate: string
    startSeconds: number
  }

  const signatureClaims = useMemo<AggregatedClaim[]>(() => {
    if (!profile) return []
    const all: AggregatedClaim[] = []
    for (const v of profile.videos) {
      for (const op of v.notable_opinions) {
        if (!isClaim(op) || op.evidence.length === 0) continue
        all.push({ text: op.text, videoId: v.video_id, videoTitle: v.title, uploadDate: v.upload_date, startSeconds: op.evidence[0].start_seconds })
      }
    }
    if (all.length < 5) {
      for (const v of profile.videos) {
        for (const c of v.key_claims) {
          if (!isClaim(c) || c.evidence.length === 0) continue
          all.push({ text: c.text, videoId: v.video_id, videoTitle: v.title, uploadDate: v.upload_date, startSeconds: c.evidence[0].start_seconds })
          if (all.length >= 5) break
        }
        if (all.length >= 5) break
      }
    }
    const seen = new Set<string>()
    const deduped: AggregatedClaim[] = []
    for (const c of all) {
      const key = c.text.slice(0, 60).toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      deduped.push(c)
      if (deduped.length >= 5) break
    }
    return deduped
  }, [profile])

  const suggestedQuestions = useMemo<string[]>(() => {
    if (!profile) return []
    const themes = profile.rollups.all_themes
    const refs = profile.rollups.all_referenced
    const name = profile.channel_name
    const out: string[] = []
    if (themes[0]) out.push(`How does ${name} think about ${themes[0].theme}?`)
    if (themes[1]) out.push(`Has ${name}'s view on ${themes[1].theme} changed over time?`)
    if (refs[0]) out.push(`What does ${name} say about ${refs[0].name}?`)
    out.push(`Summarize the most distinctive opinions ${name} has shared.`)
    return out.slice(0, 4)
  }, [profile])

  const handleExport = async () => {
    setExportError(null)
    setExporting(true)
    const res = await api.fetchExportMarkdown(channel.channel_id)
    setExporting(false)
    if (!res.ok || !res.blob) {
      setExportError(res.error || 'Export failed')
      return
    }
    downloadBlob(res.blob, res.filename || `${channel.channel_id}.md`)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[100svh] bg-cream dark:bg-ink-900">
        <div className="flex items-center gap-3 text-ink-400">
          <span className="w-3 h-3 rounded-full border-2 border-current border-r-transparent animate-spin" />
          <span className="text-[14px]">Building profile</span>
        </div>
      </div>
    )
  }

  if (error || !profile) {
    return (
      <div className="min-h-[100svh] bg-cream dark:bg-ink-900 flex items-center justify-center px-6">
        <Card className="text-center py-12 max-w-md">
          <p className="font-display text-[28px] text-ink-900 dark:text-cream mb-2">No profile yet</p>
          <p className="text-[14px] text-ink-500 mb-6">Finish the pipeline to see this view.</p>
          <button onClick={onBack} className="inline-flex items-center justify-center px-6 py-3 bg-ink-900 dark:bg-cream text-cream dark:text-ink-900 rounded-xl text-[14px] font-medium active:scale-95 transition-transform">
            Go back
          </button>
        </Card>
      </div>
    )
  }

  const firstDate = formatMonthYear(profile.date_range.first)
  const lastDate = formatMonthYear(profile.date_range.last)
  const dateCaption = profile.date_range.first && profile.date_range.last ? `${firstDate} – ${lastDate}` : 'No dates available'

  return (
    <div className="min-h-[100svh] bg-cream dark:bg-ink-900 pb-32">
      {/* Editorial hero */}
      <div className="relative overflow-hidden">
        <div aria-hidden className="absolute inset-0 bg-gradient-mesh" />
        <div aria-hidden className="absolute -top-32 -right-32 w-[400px] h-[400px] rounded-full bg-accent-red/15 blur-3xl" />
        <div className="relative max-w-5xl mx-auto px-6 pt-16 sm:pt-20 pb-12">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
            <span className="text-[11px] font-mono uppercase tracking-[0.22em] text-ink-400">Profile</span>
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.05 }}
            className="mt-3 font-display text-[48px] sm:text-[80px] lg:text-[104px] leading-[0.95] tracking-tighter text-ink-900 dark:text-cream text-balance"
          >
            {profile.channel_name}
          </motion.h1>
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.15 }}
            className="mt-6 flex items-center gap-5 flex-wrap"
          >
            {profile.avatar_url ?? channel.avatar_url ? (
              <img src={profile.avatar_url ?? channel.avatar_url!} alt="" className="w-14 h-14 rounded-full object-cover ring-1 ring-black/5 dark:ring-white/10" />
            ) : null}
            <div className="flex items-center gap-3 text-[14px] text-ink-500 dark:text-white/60 flex-wrap">
              <span className="font-mono">{profile.video_count} videos</span>
              <span className="w-1 h-1 rounded-full bg-ink-300" />
              <span>{dateCaption}</span>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={onBack}
                className="h-10 px-4 rounded-full bg-white/70 dark:bg-white/[0.07] border border-black/[0.06] dark:border-white/10 text-[13px] font-medium text-ink-700 dark:text-white/70 hover:bg-white dark:hover:bg-white/[0.1] transition"
              >
                Videos
              </button>
              <button
                onClick={handleExport}
                disabled={exporting}
                className="h-10 px-4 rounded-full bg-ink-900 dark:bg-cream text-cream dark:text-ink-900 text-[13px] font-medium hover:bg-ink-700 dark:hover:bg-white disabled:opacity-50 transition flex items-center gap-2"
              >
                {exporting && <span className="w-3 h-3 rounded-full border-2 border-current border-r-transparent animate-spin" />}
                Export .md
              </button>
            </div>
          </motion.div>
          {exportError && (
            <p className="mt-4 text-[13px] text-ios-red">{exportError}</p>
          )}
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 space-y-16">
        {/* Themes + Referenced */}
        <section>
          <SectionLabel n="01">Themes & references</SectionLabel>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card>
              <p className="text-[11px] font-mono uppercase tracking-[0.18em] text-ink-400 mb-4">Top themes</p>
              <ThemesBarChart themes={profile.rollups.all_themes.slice(0, 8)} selectedThemes={selectedThemes} onThemeClick={toggleTheme} />
              {profile.rollups.all_themes.length > 8 && !showAllThemes && (
                <button onClick={() => setShowAllThemes(true)} className="mt-2 text-[12px] text-accent-red font-medium hover:underline">
                  Show all ({profile.rollups.all_themes.length})
                </button>
              )}
              {showAllThemes && (
                <div className="mt-3">
                  <div className="flex flex-wrap gap-2">
                    {profile.rollups.all_themes.map((t: ThemeCount) => (
                      <ThemePill key={t.theme} label={t.theme} count={t.count} counts={themeCounts} selected={selectedThemes.has(t.theme)} onClick={() => toggleTheme(t.theme)} />
                    ))}
                  </div>
                  <button onClick={() => setShowAllThemes(false)} className="mt-2 text-[12px] text-accent-red font-medium hover:underline">Show less</button>
                </div>
              )}
              {selectedThemes.size > 0 && (
                <button onClick={() => setSelectedThemes(new Set())} className="mt-2 text-[12px] text-accent-red font-medium hover:underline block">Clear filters</button>
              )}
            </Card>
            <Card>
              <p className="text-[11px] font-mono uppercase tracking-[0.18em] text-ink-400 mb-4">Frequently referenced</p>
              <div className="flex flex-wrap gap-2">
                {(showAllReferenced ? profile.rollups.all_referenced : profile.rollups.all_referenced.slice(0, 8)).map((r) => (
                  <ReferencedPill key={r.name} label={r.name} count={r.count} counts={referencedCounts} />
                ))}
              </div>
              {profile.rollups.all_referenced.length > 8 && (
                <button onClick={() => setShowAllReferenced(v => !v)} className="mt-3 text-[12px] text-accent-red font-medium hover:underline">
                  {showAllReferenced ? 'Show less' : `Show all (${profile.rollups.all_referenced.length})`}
                </button>
              )}
            </Card>
          </div>
        </section>

        {/* Signature claims */}
        {signatureClaims.length > 0 && (
          <section>
            <SectionLabel n="02">Signature claims</SectionLabel>
            <Card>
              <ul className="space-y-5 divide-y divide-black/[0.05] dark:divide-white/10">
                {signatureClaims.map((c, i) => (
                  <li key={i} className={`text-[15px] sm:text-[16px] leading-relaxed text-ink-900 dark:text-cream ${i > 0 ? 'pt-5' : ''}`}>
                    <span className="font-display italic text-[20px] sm:text-[24px] text-ink-300 mr-2">"</span>
                    <span>{c.text}</span>
                    <CitationPill videoId={c.videoId} startSeconds={c.startSeconds} />
                    <div className="text-[12px] text-ink-400 mt-1.5 truncate">— {c.videoTitle} · {formatShortDate(c.uploadDate)}</div>
                  </li>
                ))}
              </ul>
            </Card>
          </section>
        )}

        {/* Suggested questions / chat CTA */}
        <section>
          <SectionLabel n="03">Start a conversation</SectionLabel>
          <Card className="relative overflow-hidden">
            <div aria-hidden className="absolute -top-20 -right-20 w-[280px] h-[280px] rounded-full bg-accent-coral/10 blur-3xl" />
            <p className="relative text-[14px] text-ink-500 dark:text-white/60 mb-4">
              Ask anything — get answers cited to the second.
            </p>
            <div className="relative grid grid-cols-1 sm:grid-cols-2 gap-2.5 mb-5">
              {suggestedQuestions.map((q, i) => (
                <motion.button
                  key={i}
                  whileHover={{ y: -2 }}
                  onClick={() => onStartChat(q)}
                  className="text-left text-[14px] text-ink-900 dark:text-cream px-4 py-3.5 rounded-xl bg-ink-50 dark:bg-ink-600 border border-black/[0.04] dark:border-white/[0.06] hover:border-accent-red/40 hover:bg-white dark:hover:bg-ink-700 transition-all"
                >
                  <span className="font-mono text-[10px] text-ink-300 mr-2">→</span>
                  {q}
                </motion.button>
              ))}
            </div>
            <button
              onClick={() => onStartChat()}
              className="relative w-full sm:w-auto inline-flex items-center justify-center px-6 py-3.5 bg-ink-900 dark:bg-cream text-cream dark:text-ink-900 rounded-xl text-[15px] font-medium active:scale-[0.98] transition-transform gap-2"
            >
              Start chatting
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
              </svg>
            </button>
          </Card>
        </section>

        {/* Timeline */}
        <section>
          <button onClick={() => setTimelineOpen(o => !o)} className="w-full text-left">
            <SectionLabel n="04">
              Timeline
              <span className="ml-3 text-[12px] font-mono font-normal text-ink-400 align-middle">
                {filteredVideos.length}{selectedThemes.size > 0 ? ' filtered' : ''} {timelineOpen ? '▾' : '▸'}
              </span>
            </SectionLabel>
          </button>
          {timelineOpen && (
            <Card className="p-0 overflow-hidden">
              {filteredVideos.length === 0 ? (
                <div className="px-4 py-12 text-center text-ink-400 text-[14px]">No videos match the selected themes.</div>
              ) : (
                filteredVideos.map((video, index) => (
                  <TimelineRow key={video.video_id} video={video} index={index} />
                ))
              )}
            </Card>
          )}
        </section>

        {/* More stats */}
        <section>
          <button onClick={() => setMoreStatsOpen(o => !o)} className="w-full text-left">
            <SectionLabel n="05">
              More stats
              <span className="ml-3 text-[12px] font-mono font-normal text-ink-400 align-middle">{moreStatsOpen ? '▾' : '▸'}</span>
            </SectionLabel>
          </button>
          {moreStatsOpen && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Card>
                <p className="text-[11px] font-mono uppercase tracking-[0.18em] text-ink-400 mb-3">Tone mix</p>
                {toneEntries.length < 3 ? (
                  <div className="space-y-3">{toneEntries.map(([tone, count]) => (<ToneBar key={tone} label={tone} count={count} maxCount={maxToneCount} />))}</div>
                ) : (
                  <ToneDonutChart tones={toneEntries} />
                )}
              </Card>
              {monthlyCounts.length >= 2 && (
                <Card>
                  <p className="text-[11px] font-mono uppercase tracking-[0.18em] text-ink-400 mb-3">Activity over time</p>
                  <UploadActivityChart data={monthlyCounts} />
                </Card>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
