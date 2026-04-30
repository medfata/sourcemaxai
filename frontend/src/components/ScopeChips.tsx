import { useMemo } from 'react'
import type { Profile } from '../types'

interface Scope {
  themes: string[]
  tones: string[]
  dateFrom?: string
  dateTo?: string
}

interface Props {
  profile: Profile | null
  scope: Scope
  onScopeChange: (scope: Scope) => void
}

const DATE_PRESETS = [
  { label: 'All time', dateFrom: undefined, dateTo: undefined },
  { label: 'Since 2024', dateFrom: '20240101', dateTo: undefined },
  { label: 'Since 2023', dateFrom: '20230101', dateTo: undefined },
  { label: '2022 only', dateFrom: '20220101', dateTo: '20221231' },
  { label: 'Since 2021', dateFrom: '20210101', dateTo: undefined },
]

export default function ScopeChips({ profile, scope, onScopeChange }: Props) {
  const topThemes = useMemo(() => {
    if (!profile?.rollups?.all_themes) return []
    return profile.rollups.all_themes.slice(0, 8).map(t => t.theme)
  }, [profile])

  const topTones = useMemo(() => {
    if (!profile?.rollups?.tone_distribution) return []
    return Object.entries(profile.rollups.tone_distribution)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
      .map(([tone]) => tone)
  }, [profile])

  const currentDatePreset = useMemo(() => {
    return DATE_PRESETS.find(p =>
      p.dateFrom === scope.dateFrom && p.dateTo === scope.dateTo
    ) || DATE_PRESETS[0]
  }, [scope.dateFrom, scope.dateTo])

  const toggleTheme = (theme: string) => {
    const newThemes = scope.themes.includes(theme)
      ? scope.themes.filter(t => t !== theme)
      : [...scope.themes, theme]
    onScopeChange({ ...scope, themes: newThemes })
  }

  const toggleTone = (tone: string) => {
    const newTones = scope.tones.includes(tone)
      ? scope.tones.filter(t => t !== tone)
      : [...scope.tones, tone]
    onScopeChange({ ...scope, tones: newTones })
  }

  const setDatePreset = (preset: typeof DATE_PRESETS[0]) => {
    onScopeChange({ ...scope, dateFrom: preset.dateFrom, dateTo: preset.dateTo })
  }

  const clearAll = () => {
    onScopeChange({ themes: [], tones: [], dateFrom: undefined, dateTo: undefined })
  }

  const hasActiveFilters = scope.themes.length > 0 || scope.tones.length > 0 || scope.dateFrom || scope.dateTo

  if (!profile) return null

  return (
    <div className="px-4 pb-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[12px] text-ios-text-secondary">Filter:</span>
        {hasActiveFilters && (
          <button onClick={clearAll} className="text-[12px] text-ios-blue hover:underline">
            Clear
          </button>
        )}
      </div>

      {topThemes.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {topThemes.map(theme => (
            <button
              key={theme}
              onClick={() => toggleTheme(theme)}
              className={`text-[11px] px-2 py-1 rounded-full border transition-colors ${
                scope.themes.includes(theme)
                  ? 'bg-ios-blue text-white border-ios-blue'
                  : 'bg-white dark:bg-ios-card-dark border-ios-separator dark:border-white/[0.08] text-ios-text-primary dark:text-ios-text-primary-dark hover:border-ios-blue/30'
              }`}
            >
              {theme}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-1.5 mb-2">
        {DATE_PRESETS.map(preset => (
          <button
            key={preset.label}
            onClick={() => setDatePreset(preset)}
            className={`text-[11px] px-2 py-1 rounded-full border transition-colors ${
              currentDatePreset.label === preset.label
                ? 'bg-ios-blue text-white border-ios-blue'
                : 'bg-white dark:bg-ios-card-dark border-ios-separator dark:border-white/[0.08] text-ios-text-primary dark:text-ios-text-primary-dark hover:border-ios-blue/30'
            }`}
          >
            {preset.label}
          </button>
        ))}
      </div>

      {topTones.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {topTones.map(tone => (
            <button
              key={tone}
              onClick={() => toggleTone(tone)}
              className={`text-[11px] px-2 py-1 rounded-full border transition-colors ${
                scope.tones.includes(tone)
                  ? 'bg-ios-blue text-white border-ios-blue'
                  : 'bg-white dark:bg-ios-card-dark border-ios-separator dark:border-white/[0.08] text-ios-text-primary dark:text-ios-text-primary-dark hover:border-ios-blue/30'
              }`}
            >
              {tone}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}