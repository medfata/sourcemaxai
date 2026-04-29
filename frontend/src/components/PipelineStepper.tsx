import type { Stage, StageStatus } from '../types'

interface PipelineStepperProps {
  stages: Stage[]
  onStageClick?: (stage: Stage) => void
}

function stageCircle(status: StageStatus, index: number) {
  const base =
    'w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold transition-colors duration-200'
  switch (status) {
    case 'done':
      return (
        <div className={`${base} bg-ios-green text-white`}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </div>
      )
    case 'active':
      return (
        <div className={`${base} bg-ios-blue text-white relative`}>
          <span className="relative z-10">{index + 1}</span>
          <span className="absolute inset-0 rounded-full bg-ios-blue animate-ping opacity-30" />
        </div>
      )
    case 'error':
      return (
        <div className={`${base} bg-ios-red text-white`}>!</div>
      )
    default:
      return (
        <div className={`${base} bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400`}>
          {index + 1}
        </div>
      )
  }
}

function stageLabelColor(status: StageStatus) {
  switch (status) {
    case 'active':
      return 'text-ios-blue font-medium'
    case 'error':
      return 'text-ios-red'
    default:
      return 'text-gray-400 dark:text-gray-500'
  }
}

export default function PipelineStepper({ stages, onStageClick }: PipelineStepperProps) {
  return (
    <div className="sticky top-0 z-50 bg-ios-bg/90 dark:bg-black/90 backdrop-blur-md border-b border-ios-separator">
      <div className="max-w-3xl mx-auto px-4 py-3">
        <div className="flex items-center justify-between overflow-x-auto scrollbar-hide">
          {stages.map((stage, i) => {
            const isClickable = stage.status === 'done' && onStageClick
            return (
              <div key={stage.id} className="flex items-center flex-1 min-w-fit">
                <button
                  onClick={() => isClickable && onStageClick?.(stage)}
                  disabled={!isClickable}
                  className={`flex flex-col items-center gap-1 px-2 ${
                    isClickable ? 'cursor-pointer' : 'cursor-default'
                  }`}
                >
                  {stageCircle(stage.status, i)}
                  <span className={`text-[11px] whitespace-nowrap ${stageLabelColor(stage.status)}`}>
                    {stage.label}
                  </span>
                </button>
                {i < stages.length - 1 && (
                  <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700 mx-1 min-w-[16px]" />
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
