export function formatRelativeDate(yyyymmdd: string): string {
  if (!yyyymmdd || yyyymmdd.length !== 8) return 'Unknown date'
  const y = parseInt(yyyymmdd.slice(0, 4), 10)
  const m = parseInt(yyyymmdd.slice(4, 6), 10) - 1
  const d = parseInt(yyyymmdd.slice(6, 8), 10)
  const date = new Date(y, m, d)
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(date)
}

export function formatMonthYear(yyyymmdd: string | null): string {
  if (!yyyymmdd || yyyymmdd.length !== 8) return 'Unknown'
  const y = parseInt(yyyymmdd.slice(0, 4), 10)
  const m = parseInt(yyyymmdd.slice(4, 6), 10) - 1
  const date = new Date(y, m, 1)
  return new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric' }).format(date)
}

export function formatShortDate(yyyymmdd: string): string {
  if (!yyyymmdd || yyyymmdd.length !== 8) return 'Unknown'
  const y = parseInt(yyyymmdd.slice(0, 4), 10)
  const m = parseInt(yyyymmdd.slice(4, 6), 10) - 1
  const d = parseInt(yyyymmdd.slice(6, 8), 10)
  const date = new Date(y, m, d)
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(date)
}
