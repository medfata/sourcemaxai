import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { Stage, StageStatus } from '../types'

interface PipelineStepperProps {
  stages: Stage[]
  onStageClick?: (stage: Stage) => void
}

function StatusDot({ status }: { status: StageStatus }) {
  if (status === 'done') {
    return (
      <span className="w-5 h-5 rounded-full bg-ink-900 dark:bg-cream flex items-center justify-center">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" className="text-cream dark:text-ink-900">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      </span>
    )
  }
  if (status === 'active') {
    return (
      <span className="relative w-5 h-5 flex items-center justify-center">
        <span className="absolute inset-0 rounded-full bg-accent-red animate-ping opacity-30" />
        <span className="relative w-2.5 h-2.5 rounded-full bg-accent-red" />
      </span>
    )
  }
  if (status === 'error') {
    return <span className="w-5 h-5 rounded-full bg-ios-red text-white text-[11px] font-bold flex items-center justify-center">!</span>
  }
  return <span className="w-5 h-5 rounded-full border border-ink-300/60 dark:border-white/20" />
}

export default function PipelineStepper({ stages, onStageClick }: PipelineStepperProps) {
  const [open, setOpen] = useState(false)
  const total = stages.length
  const doneCount = stages.filter((s) => s.status === 'done').length
  const activeStage = stages.find((s) => s.status === 'active') ?? stages.find((s) => s.status !== 'done')
  const progress = total > 0 ? (doneCount / total) * 100 : 0
  const radius = 18
  const circumference = 2 * Math.PI * radius

  return (
    <div className="fixed z-50 bottom-4 right-4 sm:bottom-6 sm:right-6 select-none">
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.96 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="absolute bottom-[64px] right-0 w-[280px] rounded-2xl glass shadow-ring border border-black/5 dark:border-white/10 p-2 overflow-hidden"
          >
            <div className="px-3 pt-2 pb-1 flex items-baseline justify-between">
              <span className="text-[10px] uppercase tracking-[0.18em] text-ink-400">Pipeline</span>
              <span className="text-[11px] text-ink-500 font-mono">{doneCount}/{total}</span>
            </div>
            <div className="flex flex-col">
              {stages.map((stage, i) => {
                const isClickable = stage.status === 'done' && onStageClick
                const isActive = stage.status === 'active'
                return (
                  <button
                    key={stage.id}
                    onClick={() => {
                      if (isClickable) {
                        onStageClick?.(stage)
                        setOpen(false)
                      }
                    }}
                    disabled={!isClickable}
                    className={`group flex items-center gap-3 px-3 py-2 rounded-xl text-left transition-colors ${
                      isClickable ? 'hover:bg-black/[0.04] dark:hover:bg-white/[0.06] cursor-pointer' : 'cursor-default'
                    }`}
                  >
                    <span className="relative flex items-center justify-center">
                      <StatusDot status={stage.status} />
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className={`block text-[13px] leading-tight ${
                        isActive ? 'text-ink-900 dark:text-cream font-semibold' : stage.status === 'done' ? 'text-ink-700 dark:text-cream/90 font-medium' : 'text-ink-400 dark:text-white/50'
                      }`}>
                        {stage.label}
                      </span>
                      <span className="block text-[10px] text-ink-300 dark:text-white/30 font-mono mt-0.5">
                        {String(i + 1).padStart(2, '0')}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <motion.button
        whileHover={{ scale: 1.04 }}
        whileTap={{ scale: 0.96 }}
        onClick={() => setOpen((v) => !v)}
        className="relative h-12 pl-2 pr-4 rounded-full glass shadow-ring border border-black/5 dark:border-white/10 flex items-center gap-2.5"
      >
        <svg width="44" height="44" viewBox="0 0 44 44" className="-rotate-90">
          <circle cx="22" cy="22" r={radius} stroke="currentColor" strokeOpacity="0.12" strokeWidth="3" fill="none" />
          <motion.circle
            cx="22" cy="22" r={radius}
            stroke="url(#stepperGradient)"
            strokeWidth="3"
            strokeLinecap="round"
            fill="none"
            strokeDasharray={circumference}
            animate={{ strokeDashoffset: circumference - (progress / 100) * circumference }}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          />
          <defs>
            <linearGradient id="stepperGradient" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#B8001F" />
              <stop offset="50%" stopColor="#FF1F3D" />
              <stop offset="100%" stopColor="#FFB020" />
            </linearGradient>
          </defs>
        </svg>
        <span className="flex flex-col items-start leading-none">
          <span className="text-[10px] uppercase tracking-[0.18em] text-ink-400">Step {Math.min(doneCount + 1, total)}</span>
          <span className="text-[13px] font-medium text-ink-900 dark:text-cream truncate max-w-[120px]">
            {activeStage?.label ?? 'Done'}
          </span>
        </span>
      </motion.button>
    </div>
  )
}
