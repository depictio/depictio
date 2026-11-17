/**
 * Order values that name durations.
 *
 * Sorted as text, a time course reads `18h`, `1h`, `2h`, `30min`; a natural
 * sort gets the numbers right but still puts `30min` after `2h`, since 30
 * outranks 2. When every value ends in a duration the order is the duration's.
 * Mirrors `depictio/models/components/value_order.py`, which orders the
 * option lists the server returns.
 */

/** Trailing duration of a label: `30min`, `2h`, `1.5 hr`, `3d`, `45s`, after an
 *  underscore, dash, dot, space or nothing (`GM_12h` reads 12 hours, `REP12`
 *  none). Same rule as `depictio.recipes.lib.time_course`. */
const DURATION_RE =
  /(?:^|[_\-.\s])(\d+(?:\.\d+)?)\s*(s|sec|secs|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)$/i;

const UNIT_HOURS: Record<string, number> = { s: 1 / 3600, m: 1 / 60, h: 1, d: 24 };

const COLLATOR = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

/** Hours in the trailing duration of `label`, null when it ends in none. */
export function parseDurationHours(label: string | null | undefined): number | null {
  if (label === null || label === undefined) return null;
  const match = DURATION_RE.exec(String(label).trim());
  if (!match) return null;
  const unit = match[2].toLowerCase();
  const key = unit.startsWith('m') ? 'm' : unit[0];
  return Number(match[1]) * UNIT_HOURS[key];
}

/** A comparator: by duration when every value of `values` ends in one, else
 *  the natural order (`Sample_2` before `Sample_10`). */
export function naturalOrDurationCompare(
  values: readonly string[],
): (a: string, b: string) => number {
  const hours = new Map<string, number>();
  let allDurations = values.length > 0;
  for (const v of values) {
    const h = parseDurationHours(v);
    if (h === null) {
      allDurations = false;
      break;
    }
    hours.set(v, h);
  }
  if (!allDurations) return (a, b) => COLLATOR.compare(a, b);
  return (a, b) => (hours.get(a)! - hours.get(b)!) || COLLATOR.compare(a, b);
}

/** `values` sorted by `naturalOrDurationCompare`; the input is not modified. */
export function sortNaturalOrDuration(values: readonly string[]): string[] {
  return [...values].sort(naturalOrDurationCompare(values));
}
