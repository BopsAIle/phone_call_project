/** Giây -> "m:ss" (hoặc "h:mm:ss" khi cuộc gọi dài quá một tiếng). */
export const formatDuration = (seconds?: number | null): string => {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—'
  const total = Math.max(0, Math.round(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  const mm = hours > 0 ? String(minutes).padStart(2, '0') : String(minutes)
  return hours > 0
    ? `${hours}:${mm}:${String(secs).padStart(2, '0')}`
    : `${mm}:${String(secs).padStart(2, '0')}`
}
