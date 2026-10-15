/**
 * A tile that carries the unit chip (see `interactive/scopeContext.tsx`) names
 * its unit there, so its echo line must not say it again: renderers lead their
 * echo with the unit (`P12345 · 412 residues`), which next to a chip reading
 * `P12345` is the same word twice in one header.
 */

const SEP = ' · ';

/** `echo` without the segments that only repeat `scope`; null when nothing
 *  else is left. */
export function echoWithoutScope(
  echo: string | null | undefined,
  scope: string | null | undefined,
): string | null {
  if (!echo) return null;
  const unit = scope?.trim();
  if (!unit) return echo;
  const kept = echo.split(SEP).filter((seg) => seg.trim() !== unit);
  return kept.length > 0 ? kept.join(SEP) : null;
}
