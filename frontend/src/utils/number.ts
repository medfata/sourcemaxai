const compactFormatter = new Intl.NumberFormat('en', {
  notation: 'compact',
  maximumFractionDigits: 2,
})

export function formatCompactNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value < 0) return ''
  return compactFormatter.format(value)
}
