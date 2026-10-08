/**
 * Run-folder locations, as the "From a run folder" flow shows and walks them.
 *
 * A location is either a path on the server's disk (`/abs/path` or `~/...`)
 * or an `s3://bucket/prefix/` URL. The server spells the two differently: it
 * lists local folders without a trailing slash and S3 prefixes with one. So
 * every helper here normalises before it compares, and the folder browser,
 * the path bar and the preview all agree on which folder is which.
 */

export type FolderSource = 'local' | 's3';

const S3_SCHEME = /^s3:\/\//i;

/** True for an `s3://` URL (any case of the scheme). */
export function isS3Location(location: string): boolean {
  return S3_SCHEME.test(location.trim());
}

/** Where a location lives: the server's disk or S3. */
export function folderSource(location: string): FolderSource {
  return isS3Location(location) ? 's3' : 'local';
}

/** True for a path the server reads from its own disk: absolute, or under
 *  the server user's home (`~`, `~/...`). Expects trimmed input. */
export function isLocalFolderPath(location: string): boolean {
  return location.startsWith('/') || location.startsWith('~/') || location === '~';
}

interface SplitFolder {
  /** `s3://`, `/`, `~/`, or `` for a relative path. */
  prefix: string;
  segments: string[];
}

function splitFolder(location: string): SplitFolder {
  const value = location.trim();
  if (isS3Location(value)) {
    return { prefix: 's3://', segments: value.slice(5).split('/').filter(Boolean) };
  }
  if (value === '~' || value.startsWith('~/')) {
    return { prefix: '~/', segments: value.slice(1).split('/').filter(Boolean) };
  }
  if (value.startsWith('/')) {
    return { prefix: '/', segments: value.split('/').filter(Boolean) };
  }
  return { prefix: '', segments: value.split('/').filter(Boolean) };
}

/** True when `location` is `base` or below it: same prefix, and `base`'s
 *  segments open `location`'s. */
function isWithin(base: SplitFolder, location: SplitFolder): boolean {
  if (base.prefix !== location.prefix) return false;
  if (location.segments.length < base.segments.length) return false;
  return base.segments.every((segment, i) => segment === location.segments[i]);
}

function joinFolder({ prefix, segments }: SplitFolder): string {
  if (prefix === 's3://') {
    return segments.length ? `s3://${segments.join('/')}/` : 's3://';
  }
  if (prefix === '~/') return segments.length ? `~/${segments.join('/')}` : '~';
  return `${prefix}${segments.join('/')}`;
}

/** The canonical spelling of a folder: trimmed, repeated slashes collapsed,
 *  an S3 prefix ending with exactly one `/`, a local folder with none (`/`
 *  itself excepted). Empty input stays empty. */
export function normalizeFolder(location: string): string {
  if (!location.trim()) return '';
  return joinFolder(splitFolder(location));
}

/** The last segment of a location: `run42` for `/data/run42`, `results` for
 *  `s3://bucket/results/`, the bucket for `s3://bucket/`. `/` and `~` name
 *  themselves. */
export function folderName(location: string): string {
  const split = splitFolder(location);
  if (split.segments.length === 0) return joinFolder(split) || location.trim();
  return split.segments[split.segments.length - 1];
}

/** One level up, or null at the top: `/` locally, `~`, and a bare bucket
 *  (`s3://bucket/`), above which nothing can be listed. */
export function parentFolder(location: string): string | null {
  const split = splitFolder(location);
  if (split.segments.length === 0) return null;
  if (split.prefix === 's3://' && split.segments.length === 1) return null;
  if (split.prefix === '' && split.segments.length === 1) return null;
  return joinFolder({ ...split, segments: split.segments.slice(0, -1) });
}

/** Every folder from `root` down to `target`, both included, in that order;
 *  null when `target` is not `root` or below it. Used to open the folder tree
 *  on a location typed or found elsewhere. */
export function folderAncestors(root: string, target: string): string[] | null {
  const r = splitFolder(root);
  const t = splitFolder(target);
  if (!isWithin(r, t)) return null;
  const chain: string[] = [];
  for (let depth = r.segments.length; depth <= t.segments.length; depth += 1) {
    chain.push(joinFolder({ prefix: t.prefix, segments: t.segments.slice(0, depth) }));
  }
  return chain;
}

/** `location` relative to `base` (`multiqc/multiqc_data` for a file under
 *  the run folder), `''` when they are the same folder, null when `location`
 *  is not under `base`. Works on files as well as folders. */
export function relativeToFolder(base: string, location: string): string | null {
  if (!base.trim() || !location.trim()) return null;
  const b = splitFolder(base);
  const l = splitFolder(location);
  if (!isWithin(b, l)) return null;
  return l.segments.slice(b.segments.length).join('/');
}

const GUESSED_HOME = /^\/(?:Users|home)\/[^/]+(?=\/|$)|^\/root(?=\/|$)/;

/** A local path with the home folder written `~`. The home folder is the
 *  given one, or else guessed from the usual layouts (`/Users/<name>`,
 *  `/home/<name>`, `/root`): this is for display only, the full path stays
 *  one hover or one copy away. S3 URLs are returned unchanged. */
export function shortenHome(path: string, home?: string | null): string {
  const value = path.trim();
  if (!value || isS3Location(value)) return value;
  if (home) {
    const h = normalizeFolder(home);
    if (h && h !== '/') {
      if (value === h) return '~';
      if (value.startsWith(`${h}/`)) return `~${value.slice(h.length)}`;
    }
  }
  const match = value.match(GUESSED_HOME);
  if (!match) return value;
  return `~${value.slice(match[0].length)}`;
}

function ellipsizeChars(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  const keep = Math.max(maxLength - 1, 2);
  const head = Math.ceil(keep / 2);
  const tail = Math.floor(keep / 2);
  return `${text.slice(0, head)}…${text.slice(text.length - tail)}`;
}

/** A long location cut in the middle, on segment boundaries when it can:
 *  the first segment and as many of the last ones as fit, joined by `…`.
 *  `~/results/…/ampliseq/run42` rather than a path that wraps over three
 *  lines. The last segment is always kept (cut itself only as a last
 *  resort). */
export function middleEllipsis(location: string, maxLength = 48): string {
  const value = location.trim();
  if (value.length <= maxLength) return value;
  const split = splitFolder(value);
  const trailing = split.prefix === 's3://' && value.endsWith('/') ? '/' : '';
  const { segments } = split;
  if (segments.length <= 2) return ellipsizeChars(value, maxLength);
  const head = `${split.prefix}${segments[0]}`;
  const tail: string[] = [segments[segments.length - 1]];
  for (let i = segments.length - 2; i >= 1; i -= 1) {
    const candidate = `${head}/…/${[segments[i], ...tail].join('/')}${trailing}`;
    if (candidate.length > maxLength) break;
    tail.unshift(segments[i]);
  }
  const hidden = segments.length - 1 - tail.length;
  const out =
    hidden > 0
      ? `${head}/…/${tail.join('/')}${trailing}`
      : `${head}/${tail.join('/')}${trailing}`;
  return ellipsizeChars(out, maxLength);
}

/** Home shortening then middle ellipsis: how the flow writes a location
 *  where space is short. */
export function shortenFolder(
  location: string,
  options: { home?: string | null; maxLength?: number } = {},
): string {
  return middleEllipsis(shortenHome(location, options.home), options.maxLength ?? 48);
}

/** `location` relative to the run folder, trying the paths as written and
 *  then with the home folder written `~` on both sides (a run folder entered
 *  as `~/...` against locations the server wrote out in full). Same answers
 *  as `relativeToFolder`. */
export function relativeToRunFolder(
  runFolder: string,
  location: string,
  home?: string | null,
): string | null {
  const direct = relativeToFolder(runFolder, location);
  if (direct !== null) return direct;
  return relativeToFolder(shortenHome(runFolder, home), shortenHome(location, home));
}

/** What the path bar suggests while the reader types: the sub-folders of
 *  `parent` whose name starts with `partial`. A trailing slash asks for the
 *  folder's own contents; text without any folder yet (`/Us`, `s3://buck`)
 *  has no parent, and is matched against the roots instead. */
export function pathBarQuery(typed: string): { parent: string | null; partial: string } {
  const value = typed.trim();
  if (!value) return { parent: null, partial: '' };
  if (isS3Location(value)) {
    const rest = value.slice(5);
    if (!rest.includes('/')) return { parent: null, partial: value };
  }
  if (value.endsWith('/')) {
    return { parent: normalizeFolder(value), partial: '' };
  }
  const slash = value.lastIndexOf('/');
  if (slash < 0) return { parent: null, partial: value };
  const parentText = value.slice(0, slash + 1);
  return { parent: normalizeFolder(parentText) || '/', partial: value.slice(slash + 1) };
}
