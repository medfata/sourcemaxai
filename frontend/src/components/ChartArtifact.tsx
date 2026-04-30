import type { Profile } from '../types'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

type ChartSpec =
  | { type: 'evolution'; title: string; theme: string; points: { video_id: string; upload_date: string; score: number; label?: string }[] }
  | { type: 'comparison_table'; title: string; columns: string[]; rows: string[][] }
  | { type: 'claim_cluster'; title: string; groups: { label: string; claims: { text: string; video_id: string; start_seconds: number }[] }[] }

interface Props {
  spec: ChartSpec
  profile: Profile | null
  onCitationClick: (videoId: string, startSeconds: number) => void
}

function formatDate(dateStr: string): string {
  if (!dateStr || dateStr.length !== 8) return dateStr
  const year = dateStr.substring(0, 4)
  const month = dateStr.substring(4, 6)
  const day = dateStr.substring(6, 8)
  return `${month}/${day}/${year}`
}

export default function ChartArtifact({ spec, profile: _profile, onCitationClick }: Props) {
  return (
    <div className="rounded-2xl border border-ios-separator dark:border-white/[0.08] p-4 my-3 bg-white dark:bg-ios-card-dark">
      {spec.type === 'evolution' && <EvolutionChart spec={spec} onCitationClick={onCitationClick} />}
      {spec.type === 'comparison_table' && <ComparisonTable spec={spec} />}
      {spec.type === 'claim_cluster' && <ClaimCluster spec={spec} onCitationClick={onCitationClick} />}
    </div>
  )
}

function EvolutionChart({ spec, onCitationClick }: { spec: Extract<ChartSpec, { type: 'evolution' }>; onCitationClick: (videoId: string, startSeconds: number) => void }) {
  const data = spec.points.map(p => ({
    name: formatDate(p.upload_date),
    score: p.score,
    label: p.label || '',
    videoId: p.video_id,
  }))

  return (
    <div>
      <h4 className="text-[15px] font-semibold mb-2">{spec.title}</h4>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis domain={[-1, 1]} tick={{ fontSize: 11 }} ticks={[-1, -0.5, 0, 0.5, 1]} />
            <Tooltip
              formatter={(value: any) => [Number(value).toFixed(2), 'Score']}
              labelFormatter={(label) => `Date: ${label}`}
              contentStyle={{ fontSize: 12 }}
            />
            <Line
              type="monotone"
              dataKey="score"
              stroke="#0A84FF"
              strokeWidth={2}
              dot={{ fill: '#0A84FF', r: 4 }}
              onClick={(data: any) => {
                if (data && data.payload && data.payload.videoId) {
                  onCitationClick(data.payload.videoId as string, 0)
                }
              }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3 space-y-1">
        {spec.points.map((p, i) => (
          <div key={i} className="flex items-center justify-between text-[12px]">
            <span className="text-ios-text-secondary">{formatDate(p.upload_date)} — {p.label || 'neutral'}</span>
            <button
              onClick={() => onCitationClick(p.video_id, 0)}
              className="text-ios-blue hover:underline"
            >
              View video
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

function ComparisonTable({ spec }: { spec: Extract<ChartSpec, { type: 'comparison_table' }> }) {
  return (
    <div>
      <h4 className="text-[15px] font-semibold mb-2">{spec.title}</h4>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px] border-collapse">
          <thead>
            <tr>
              {spec.columns.map((col, i) => (
                <th key={i} className="text-left font-semibold border-b border-ios-separator px-2 py-1.5">{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {spec.rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j} className="border-b border-ios-separator/40 px-2 py-1.5 align-top">{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ClaimCluster({ spec, onCitationClick }: { spec: Extract<ChartSpec, { type: 'claim_cluster' }>; onCitationClick: (videoId: string, startSeconds: number) => void }) {
  return (
    <div>
      <h4 className="text-[15px] font-semibold mb-3">{spec.title}</h4>
      <div className="space-y-4">
        {spec.groups.map((group, i) => (
          <div key={i}>
            <h5 className="text-[13px] font-medium mb-1">{group.label}</h5>
            <div className="space-y-2">
              {group.claims.map((claim, j) => (
                <div key={j} className="bg-black/5 dark:bg-white/5 rounded-lg p-2 text-[12px]">
                  <p className="mb-1">{claim.text}</p>
                  <button
                    onClick={() => onCitationClick(claim.video_id, claim.start_seconds)}
                    className="text-ios-blue hover:underline"
                  >
                    [↗ {Math.floor(claim.start_seconds / 60)}:{String(claim.start_seconds % 60).padStart(2, '0')}]
                  </button>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}