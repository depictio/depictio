/** Version-string helpers shared by the template flow and project provenance. */

/** A version without surrounding spaces or a leading `v`. */
export function bareVersion(version: string): string {
  return version.trim().replace(/^v/i, '');
}

function versionKey(version: string): { main: number[]; pre: string | null } {
  const bare = bareVersion(version);
  const dash = bare.indexOf('-');
  const main = dash >= 0 ? bare.slice(0, dash) : bare;
  const pre = dash >= 0 ? bare.slice(dash + 1) : null;
  return {
    main: main.split(/[.+]/).map((part) => {
      const n = Number.parseInt(part, 10);
      return Number.isNaN(n) ? -1 : n;
    }),
    pre,
  };
}

/** Compare two version strings: positive when `a` is newer. Numeric segment
 *  by segment (`2.10.0` after `2.9.1`), a missing segment counting as 0, and
 *  a pre-release (`2.0.0-rc1`) before its release. */
export function compareVersions(a: string, b: string): number {
  const ka = versionKey(a);
  const kb = versionKey(b);
  const length = Math.max(ka.main.length, kb.main.length);
  for (let i = 0; i < length; i += 1) {
    const diff = (ka.main[i] ?? 0) - (kb.main[i] ?? 0);
    if (diff !== 0) return diff;
  }
  if (ka.pre === kb.pre) return 0;
  if (ka.pre === null) return 1;
  if (kb.pre === null) return -1;
  return ka.pre.localeCompare(kb.pre, undefined, { numeric: true });
}

/** `v2.16.0` from `2.16.0` or `v2.16.0`. */
export function formatVersion(version: string): string {
  return `v${bareVersion(version)}`;
}
