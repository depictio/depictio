/** "812 B", "12.3 KB", "1.2 MB"; null for an unknown size. */
export function fileSize(bytes: number | null | undefined): string | null {
  if (bytes === null || bytes === undefined || bytes < 0) return null;
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}
