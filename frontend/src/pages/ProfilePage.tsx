import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, XAxis, YAxis, AreaChart, Area, Tooltip } from 'recharts'
import { api } from '../api'
import type { ChannelMeta, Profile, ProfileVideo, ThemeCount } from '../types'
import { formatMonthYear, formatShortDate, formatTimestamp } from '../utils/date'

const CHART_COLORS = ['#0a84ff', '#34c759', '#ff9f0a', '#ff453a', '#bf5af2', '#5ac8fa', '#ffd60a', '#8e8e93']

interface ProfilePageProps {
  channel: ChannelMeta
  onBack: () => void
  onStartChat: () => void
}

function SectionHeader({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <h3 className={`text-[17px] font-semibold text-ios-text-primary dark:text-ios-text-primary-dark tracking-tight mb-3 ${className}`}>
      {children}
    </h3>
  )
}

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`bg-white dark:bg-ios-card-dark rounded-2xl shadow-ios p-4 sm:p-5 ${className}`}
    >
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

function ThemePill({
  label,
  count,
  counts,
  selected,
  onClick,
}: {
  label: string
  count: number
  counts: number[]
  selected?: boolean
  onClick?: () => void
}) {
  const bucket = sizeBucket(counts, count)
  const sizeClasses = {
    sm: 'text-[11px] px-2.5 py-1',
    md: 'text-[13px] px-3 py-1.5',
    lg: 'text-[15px] px-4 py-2',
  }
  return (
    <button
      onClick={onClick}
      className={`rounded-full font-medium transition-all duration-200 ease-out ${sizeClasses[bucket]} ${
        selected
          ? 'bg-ios-blue text-white'
          : 'bg-ios-bg dark:bg-gray-800 text-ios-text-primary dark:text-ios-text-primary-dark hover:scale-[1.03]'
      }`}
    >
      {label}
    </button>
  )
}

function ReferencedPill({ label, count, counts }: { label: string; count: number; counts: number[] }) {
  const bucket = sizeBucket(counts, count)
  const sizeClasses = {
    sm: 'text-[11px] px-2.5 py-1',
    md: 'text-[13px] px-3 py-1.5',
    lg: 'text-[15px] px-4 py-2',
  }
  return (
    <span
      className={`inline-block rounded-full font-medium bg-ios-bg dark:bg-gray-800 text-ios-text-primary dark:text-ios-text-primary-dark ${sizeClasses[bucket]}`}
    >
      {label}
    </span>
  )
}

function ToneBar({ label, count, maxCount }: { label: string; count: number; maxCount: number }) {
  const pct = maxCount > 0 ? (count / maxCount) * 100 : 0
  return (
    <div className="flex items-center gap-3">
      <span className="text-[13px] text-ios-text-primary dark:text-ios-text-primary-dark w-28 sm:w-36 truncate flex-shrink-0">
        {label}
      </span>
      <div className="flex-1 h-1.5 bg-ios-bg dark:bg-gray-800 rounded-full overflow-hidden">
        <div
          className="h-full bg-ios-blue rounded-full transition-all duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[13px] text-ios-text-secondary w-8 text-right flex-shrink-0">
        {count}
      </span>
    </div>
  )
}

function ThemesBarChart({
  themes,
  selectedThemes,
  onThemeClick,
}: {
  themes: ThemeCount[]
  selectedThemes: Set<string>
  onThemeClick: (theme: string) => void
}) {
  const data = themes.map((t) => ({ name: t.theme, count: t.count }))
  return (
    <div className="min-h-[200px]">
      <ResponsiveContainer width="100%" height={themes.length * 32 + 20}>
        <BarChart data={data as any[]} layout="vertical" margin={{ left: 0, right: 16, top: 4, bottom: 4 }}>
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="name" width={0} hide />
          <Bar
            dataKey="count"
            radius={[4, 4, 4, 4]}
            cursor="pointer"
            onClick={(data: any) => {
              const theme = data?.name
              if (theme) onThemeClick(theme)
            }}
          >
            {data.map((entry, index) => (
              <Cell
                key={entry.name}
                fill={selectedThemes.has(entry.name) ? CHART_COLORS[0] : CHART_COLORS[index % CHART_COLORS.length]}
                opacity={selectedThemes.size === 0 || selectedThemes.has(entry.name) ? 1 : 0.4}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="space-y-1 mt-1">
        {themes.map((t) => (
          <button
            key={t.theme}
            onClick={() => onThemeClick(t.theme)}
            className={`w-full flex items-center justify-between text-[13px] px-1 py-0.5 rounded hover:bg-ios-bg dark:hover:bg-gray-800 transition-colors text-left ${
              selectedThemes.has(t.theme)
                ? 'text-ios-blue font-semibold'
                : 'text-ios-text-primary dark:text-ios-text-primary-dark'
            }`}
          >
            <span className="truncate">{t.theme}</span>
            <span className="text-ios-text-secondary ml-2 flex-shrink-0">{t.count}</span>
          </button>
        ))}
      </div>
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
            <Pie
              data={data as any[]}
              cx="50%"
              cy="50%"
              innerRadius={50}
              outerRadius={80}
              paddingAngle={2}
              dataKey="value"
            >
              {data.map((_entry, index) => (
                <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-[15px] font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">{topTone}</span>
          {total > 0 && (
            <span className="text-[12px] text-ios-text-secondary">
              {tones[0][1]}/{total}
            </span>
          )}
        </div>
      </div>
      <div className="w-full space-y-1 mt-1">
        {tones.map(([tone, count], i) => (
          <div key={tone} className="flex items-center gap-2 text-[13px]">
            <span
              className="w-2.5 h-2.5 rounded-full flex-shrink-0"
              style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }}
            />
            <span className="truncate text-ios-text-primary dark:text-ios-text-primary-dark">{tone}</span>
            <span className="text-ios-text-secondary ml-auto">{count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function UploadActivityChart({ data }: { data: { month: string; count: number }[] }) {
  return (
    <div className="min-h-[120px]">
      <ResponsiveContainer width="100%" height={120}>
        <AreaChart data={data as any[]} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <XAxis
            dataKey="month"
            tick={{ fontSize: 11, fill: 'currentColor' }}
            tickLine={false}
            axisLine={false}
            className="text-ios-text-secondary"
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--color-ios-card, #fff)',
              border: '1px solid var(--color-ios-muted, #e5e7eb)',
              borderRadius: 8,
              fontSize: 13,
            }}
          />
          <Area
            type="monotone"
            dataKey="count"
            stroke={CHART_COLORS[0]}
            fill={CHART_COLORS[0]}
            fillOpacity={0.15}
            strokeWidth={2}
          />
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
      className="inline-flex items-center text-[11px] font-medium text-ios-blue bg-ios-blue/10 hover:bg-ios-blue/20 rounded-full px-2 py-0.5 ml-1 mr-0.5 align-baseline no-underline transition-colors whitespace-nowrap"
    >
      ↗ {formatTimestamp(startSeconds)}
    </a>
  )
}

function ClaimItem({
  text,
  evidence,
  videoId,
}: {
  text: string
  evidence: { start_seconds: number; quote: string }[]
  videoId: string
}) {
  return (
    <li>
      <span>{text}</span>
      {evidence.map((ev, i) => (
        <CitationPill key={i} videoId={videoId} startSeconds={ev.start_seconds} />
      ))}
    </li>
  )
}

function TimelineRow({
  video,
  index,
}: {
  video: ProfileVideo
  index: number
}) {
  const [expanded, setExpanded] = useState(false)
  const themePills = video.recurring_themes.slice(0, 3)
  const themeOverflow = video.recurring_themes.length - 3

  return (
    <div
      className={`border-b border-black/[0.04] dark:border-white/[0.06] last:border-0 ${
        index % 2 === 0 ? 'bg-white dark:bg-ios-card-dark' : 'bg-gray-50/50 dark:bg-white/[0.02]'
      }`}
    >
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left"
      >
        <span className="text-[13px] text-ios-text-secondary w-20 flex-shrink-0">
          {formatShortDate(video.upload_date)}
        </span>
        <span className="flex-1 text-[15px] font-medium text-ios-text-primary dark:text-ios-text-primary-dark truncate">
          {video.title}
        </span>
        <div className="hidden sm:flex items-center gap-1 flex-shrink-0 max-w-[200px]">
          {themePills.map((t) => (
            <span
              key={t}
              className="text-[11px] px-2 py-0.5 rounded-full bg-ios-bg dark:bg-gray-800 text-ios-text-secondary truncate max-w-[100px]"
            >
              {t}
            </span>
          ))}
          {themeOverflow > 0 && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-ios-bg dark:bg-gray-800 text-ios-text-secondary">
              +{themeOverflow}
            </span>
          )}
        </div>
      </button>
      <div
        className={`overflow-hidden transition-all duration-200 ease-out ${
          expanded ? 'max-h-[800px] opacity-100' : 'max-h-0 opacity-0'
        }`}
      >
        <div className="px-4 pb-4 pt-1 space-y-3">
          <div>
            <p className="text-[12px] font-semibold text-ios-text-secondary uppercase tracking-wider mb-1">
              Core topic
            </p>
            <p className="text-[15px] text-ios-text-primary dark:text-ios-text-primary-dark">
              {video.core_topic}
            </p>
          </div>
          {video.key_claims.length > 0 && (
            <div>
              <p className="text-[12px] font-semibold text-ios-text-secondary uppercase tracking-wider mb-1">
                Key claims
              </p>
              <ul className="list-disc list-inside text-[15px] text-ios-text-primary dark:text-ios-text-primary-dark space-y-1">
                {video.key_claims.map((claim, i) => (
                  <ClaimItem
                    key={i}
                    text={claim.text}
                    evidence={claim.evidence}
                    videoId={video.video_id}
                  />
                ))}
              </ul>
            </div>
          )}
          {video.recurring_themes.length > 0 && (
            <div>
              <p className="text-[12px] font-semibold text-ios-text-secondary uppercase tracking-wider mb-1">
                Themes
              </p>
              <div className="flex flex-wrap gap-1.5">
                {video.recurring_themes.map((t) => (
                  <span
                    key={t}
                    className="text-[12px] px-2 py-0.5 rounded-full bg-ios-bg dark:bg-gray-800 text-ios-text-secondary"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}
          {video.notable_opinions.length > 0 && (
            <div>
              <p className="text-[12px] font-semibold text-ios-text-secondary uppercase tracking-wider mb-1">
                Notable opinions
              </p>
              <ul className="list-disc list-inside text-[15px] text-ios-text-primary dark:text-ios-text-primary-dark space-y-1">
                {video.notable_opinions.map((op, i) => (
                  <ClaimItem
                    key={i}
                    text={op.text}
                    evidence={op.evidence}
                    videoId={video.video_id}
                  />
                ))}
              </ul>
            </div>
          )}
          {video.people_or_things_referenced.length > 0 && (
            <div>
              <p className="text-[12px] font-semibold text-ios-text-secondary uppercase tracking-wider mb-1">
                Referenced
              </p>
              <div className="flex flex-wrap gap-1.5">
                {video.people_or_things_referenced.map((r) => (
                  <span
                    key={r}
                    className="text-[12px] px-2 py-0.5 rounded-full bg-ios-bg dark:bg-gray-800 text-ios-text-secondary"
                  >
                    {r}
                  </span>
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
        if (res.data.videos.length <= 30) {
          setTimelineOpen(true)
        }
      }
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [channel.channel_id])

  useEffect(() => {
    if (selectedThemes.size > 0) setTimelineOpen(true)
  }, [selectedThemes])

  const toggleTheme = (theme: string) => {
    setSelectedThemes((prev) => {
      const next = new Set(prev)
      if (next.has(theme)) {
        next.delete(theme)
      } else {
        next.add(theme)
      }
      return next
    })
  }

  const filteredVideos = useMemo(() => {
    if (!profile) return []
    if (selectedThemes.size === 0) return profile.videos
    return profile.videos.filter((v) => {
      const themes = new Set(v.recurring_themes)
      for (const t of selectedThemes) {
        if (themes.has(t)) return true
      }
      return false
    })
  }, [profile, selectedThemes])

  const themeCounts = useMemo(() => {
    if (!profile) return []
    return profile.rollups.all_themes.map((t) => t.count)
  }, [profile])

  const referencedCounts = useMemo(() => {
    if (!profile) return []
    return profile.rollups.all_referenced.map((r) => r.count)
  }, [profile])

  const toneEntries = useMemo(() => {
    if (!profile) return []
    const entries = Object.entries(profile.rollups.tone_distribution)
    entries.sort((a, b) => b[1] - a[1])
    return entries
  }, [profile])

  const maxToneCount = useMemo(() => {
    if (toneEntries.length === 0) return 0
    return Math.max(...toneEntries.map(([, c]) => c))
  }, [toneEntries])

  const monthlyCounts = useMemo(() => {
    if (!profile) return []
    const map = new Map<string, number>()
    for (const v of profile.videos) {
      const key = v.upload_date.slice(0, 7)
      map.set(key, (map.get(key) ?? 0) + 1)
    }
    return [...map.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, count]) => ({ month, count }))
  }, [profile])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100svh-64px)]">
        <div className="text-ios-text-secondary text-[17px]">Loading profile…</div>
      </div>
    )
  }

  if (error || !profile) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-12">
        <Card className="text-center py-12">
          <p className="text-[17px] font-medium text-ios-text-primary dark:text-ios-text-primary-dark mb-2">
            No profile yet
          </p>
          <p className="text-[15px] text-ios-text-secondary mb-6">
            Finish the pipeline to see this view.
          </p>
          <button
            onClick={onBack}
            className="inline-flex items-center justify-center px-6 py-3 bg-ios-blue text-white rounded-2xl text-[17px] font-semibold active:scale-95 transition-transform"
          >
            Go back
          </button>
        </Card>
      </div>
    )
  }

  const firstDate = formatMonthYear(profile.date_range.first)
  const lastDate = formatMonthYear(profile.date_range.last)
  const dateCaption =
    profile.date_range.first && profile.date_range.last
      ? `${firstDate} – ${lastDate}`
      : 'No dates available'

  return (
    <div className="pb-24">
      <div className="max-w-[1024px] mx-auto px-4 sm:px-8 py-6 space-y-6">
        {/* Header Card */}
        <Card className="relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-br from-ios-blue/5 to-transparent pointer-events-none" />
          <div className="relative flex items-center gap-4">
            {profile.avatar_url ?? channel.avatar_url ? (
              <img
                src={profile.avatar_url ?? channel.avatar_url!}
                alt=""
                className="w-20 h-20 rounded-full object-cover flex-shrink-0"
              />
            ) : (
              <div className="w-20 h-20 rounded-full bg-ios-bg dark:bg-gray-800 flex items-center justify-center text-[28px] font-bold text-ios-text-secondary flex-shrink-0">
                {channel.channel_name.charAt(0).toUpperCase()}
              </div>
            )}
            <div className="min-w-0">
              <h1 className="text-[28px] font-bold text-ios-text-primary dark:text-ios-text-primary-dark truncate leading-tight">
                {channel.channel_name}
              </h1>
              <p className="text-[15px] text-ios-text-secondary mt-1">
                {profile.video_count} videos · {dateCaption}
              </p>
            </div>
          </div>
        </Card>

        {/* Charts Row */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <SectionHeader>Top themes</SectionHeader>
            <Card>
              <ThemesBarChart
                themes={profile.rollups.all_themes.slice(0, 8)}
                selectedThemes={selectedThemes}
                onThemeClick={toggleTheme}
              />
              {profile.rollups.all_themes.length > 8 && !showAllThemes && (
                <button
                  onClick={() => setShowAllThemes(true)}
                  className="mt-2 text-[13px] text-ios-blue font-medium hover:underline"
                >
                  Show all ({profile.rollups.all_themes.length})
                </button>
              )}
              {showAllThemes && (
                <div className="mt-3">
                  <div className="flex flex-wrap gap-2">
                    {profile.rollups.all_themes.map((t: ThemeCount) => (
                      <ThemePill
                        key={t.theme}
                        label={t.theme}
                        count={t.count}
                        counts={themeCounts}
                        selected={selectedThemes.has(t.theme)}
                        onClick={() => toggleTheme(t.theme)}
                      />
                    ))}
                  </div>
                  <button
                    onClick={() => setShowAllThemes(false)}
                    className="mt-2 text-[13px] text-ios-blue font-medium hover:underline"
                  >
                    Show less
                  </button>
                </div>
              )}
              {selectedThemes.size > 0 && (
                <button
                  onClick={() => setSelectedThemes(new Set())}
                  className="mt-2 text-[13px] text-ios-blue font-medium hover:underline block"
                >
                  Clear filters
                </button>
              )}
            </Card>
          </div>
          <div>
            <SectionHeader>Frequently referenced</SectionHeader>
            <Card>
              <div className="flex flex-wrap gap-2">
                {(showAllReferenced
                  ? profile.rollups.all_referenced
                  : profile.rollups.all_referenced.slice(0, 8)
                ).map((r) => (
                  <ReferencedPill
                    key={r.name}
                    label={r.name}
                    count={r.count}
                    counts={referencedCounts}
                  />
                ))}
              </div>
              {profile.rollups.all_referenced.length > 8 && (
                <button
                  onClick={() => setShowAllReferenced(v => !v)}
                  className="mt-3 text-[13px] text-ios-blue font-medium hover:underline"
                >
                  {showAllReferenced
                    ? 'Show less'
                    : `Show all (${profile.rollups.all_referenced.length})`}
                </button>
              )}
            </Card>
          </div>
        </div>

        {/* Timeline Card */}
        <div>
          <button
            onClick={() => setTimelineOpen(o => !o)}
            className="w-full flex items-center justify-between mb-3"
          >
            <SectionHeader className="mb-0">Timeline</SectionHeader>
            <span className="text-[13px] text-ios-text-secondary">
              {filteredVideos.length} video{filteredVideos.length !== 1 ? 's' : ''}
              {selectedThemes.size > 0 && ' filtered'}
              {' '}{timelineOpen ? '▾' : '▸'}
            </span>
          </button>
          {timelineOpen && (
            <Card className="p-0 overflow-hidden">
              {filteredVideos.length === 0 ? (
                <div className="px-4 py-8 text-center text-ios-text-secondary text-[15px]">
                  No videos match the selected themes.
                </div>
              ) : (
                filteredVideos.map((video, index) => (
                  <TimelineRow key={video.video_id} video={video} index={index} />
                ))
              )}
            </Card>
          )}
        </div>

        {/* More stats */}
        <div>
          <button
            onClick={() => setMoreStatsOpen(o => !o)}
            className="w-full flex items-center justify-between mb-3"
          >
            <SectionHeader className="mb-0">More stats</SectionHeader>
            <span className="text-[13px] text-ios-text-secondary">
              {moreStatsOpen ? '▾' : '▸'}
            </span>
          </button>
          {moreStatsOpen && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Card>
                <p className="text-[13px] text-ios-text-secondary mb-2">Tone mix</p>
                {toneEntries.length < 3 ? (
                  <div className="space-y-3">
                    {toneEntries.map(([tone, count]) => (
                      <ToneBar key={tone} label={tone} count={count} maxCount={maxToneCount} />
                    ))}
                  </div>
                ) : (
                  <ToneDonutChart tones={toneEntries} />
                )}
              </Card>
              {monthlyCounts.length >= 2 && (
                <Card>
                  <p className="text-[13px] text-ios-text-secondary mb-2">Activity over time</p>
                  <UploadActivityChart data={monthlyCounts} />
                </Card>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="text-center pt-4">
          <button
            onClick={onStartChat}
            className="w-full sm:w-auto inline-flex items-center justify-center px-8 py-4 bg-ios-blue text-white rounded-2xl text-[17px] font-semibold active:scale-95 transition-transform"
          >
            Start chatting →
          </button>
        </div>
      </div>
    </div>
  )
}
