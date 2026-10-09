/**
 * The image a text tile draws in place of its title, if any.
 *
 * A wordmark is drawn for one background: the nf-core logos come in dark ink
 * for a light page and white for a dark one. Without its dark variant a dark
 * page gets the title as text instead, never a logo it cannot read.
 */
export function textLogoSrc(
  logo: unknown,
  logoDark: unknown,
  isDark: boolean,
): string | null {
  const str = (v: unknown) => (typeof v === 'string' ? v.trim() : '');
  const light = str(logo);
  if (!light) return null;
  return isDark ? str(logoDark) || null : light;
}
