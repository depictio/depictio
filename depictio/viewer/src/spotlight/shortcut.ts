/**
 * The dashboard search's shortcut as a reader's keyboard labels it: "⌘K" on
 * Apple keyboards, "Ctrl+K" elsewhere — the two keys Mantine's `mod+K` is.
 * Its own module so the header can name it without loading the palette.
 */
export function searchShortcutLabel(): string {
  if (typeof navigator === 'undefined') return 'Ctrl+K';
  const platform =
    (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ||
    navigator.platform ||
    navigator.userAgent;
  return /mac|iphone|ipad|ipod/i.test(platform) ? '⌘K' : 'Ctrl+K';
}
