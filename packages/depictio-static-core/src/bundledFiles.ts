/**
 * Genome-browser files shipped inside a bundle, read back by byte range.
 *
 * JBrowse reads every track, index and assembly file through `fetch` with a
 * `Range:` header (generic-filehandle's RemoteFile, behind JBrowse's
 * RemoteFileWithRangeCache, which asks for whole 256 KiB pages). Producer A
 * rewrites each file location of a frozen session to
 * `JBROWSE_BUNDLE_ORIGIN + key` (a `.invalid` host: it can never resolve) and
 * ships the bytes in `inline_blobs`; the runtime's fetch shim answers those
 * URLs from here, so no request leaves the page.
 *
 * A file is shipped whole (`pages: null`), or only as the pages a region read
 * needs (`pages: [[firstPage, count], ...]`, ascending, the blob holding those
 * runs back to back): an indexed BAM, tabix or CRAM file sliced to the
 * session's opening locus. A read outside the shipped pages is refused with a
 * message naming the region the bundle holds — never answered with zeros,
 * which the browser would decode as garbage.
 *
 * Pure: no DOM, no fetch. `serveBundledRange` builds the answer the shim wraps
 * in a `Response`.
 */

export const JBROWSE_BUNDLE_ORIGIN = 'https://bundle.depictio.invalid/jbrowse/';

/** JBrowse's RemoteFileWithRangeCache page; the producer slices on it too. */
export const BUNDLED_PAGE_SIZE = 256 * 1024;

export interface BundledFileEntry {
  /** `inline_blobs` key of the shipped bytes. */
  blob: string;
  /** Size of the whole original file. */
  size: number;
  /** null: shipped whole. Else the runs of pages shipped, `[firstPage, count]`. */
  pages?: [number, number][] | null;
  page_size?: number;
  /** What the file is, for messages ("SAMPLE_11 reads (BAM)"). */
  label?: string;
  /** The region a sliced file covers, for messages. */
  region?: string | null;
}

export type BundledRead =
  | { ok: true; status: 200 | 206; bytes: Uint8Array; contentRange: string | null }
  | { ok: false; status: 416 | 404; message: string };

interface Run {
  start: number; // file offset
  end: number; // exclusive
  at: number; // offset in the blob
}

function runsOf(entry: BundledFileEntry): Run[] | null {
  if (!entry.pages) return null;
  const page = entry.page_size ?? BUNDLED_PAGE_SIZE;
  const runs: Run[] = [];
  let at = 0;
  for (const [first, count] of entry.pages) {
    const start = first * page;
    const end = Math.min((first + count) * page, entry.size);
    if (end <= start) continue;
    runs.push({ start, end, at });
    at += end - start;
  }
  return runs;
}

/** `bytes=a-b` / `bytes=a-` / `bytes=-n` against `size`; null when absent. */
export function parseByteRange(
  header: string | null | undefined,
  size: number,
): { start: number; end: number } | 'unsatisfiable' | null {
  if (!header) return null;
  const m = /^\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*$/i.exec(header);
  if (!m || (m[1] === '' && m[2] === '')) return 'unsatisfiable';
  let start: number;
  let end: number;
  if (m[1] === '') {
    const suffix = Number(m[2]);
    if (suffix <= 0) return 'unsatisfiable';
    start = Math.max(size - suffix, 0);
    end = size - 1;
  } else {
    start = Number(m[1]);
    end = m[2] === '' ? size - 1 : Number(m[2]);
  }
  if (start >= size || end < start) return 'unsatisfiable';
  return { start, end: Math.min(end, size - 1) };
}

/** A shipped file over its decoded blob bytes. */
export class BundledFile {
  readonly entry: BundledFileEntry;
  private readonly bytes: Uint8Array;
  private readonly runs: Run[] | null;

  constructor(entry: BundledFileEntry, bytes: Uint8Array) {
    this.entry = entry;
    this.bytes = bytes;
    this.runs = runsOf(entry);
    const expected = this.runs
      ? this.runs.reduce((n, r) => n + (r.end - r.start), 0)
      : entry.size;
    if (bytes.length !== expected) {
      throw new Error(
        `bundled file ${entry.label ?? entry.blob}: ${bytes.length} bytes shipped, ${expected} expected`,
      );
    }
  }

  get complete(): boolean {
    return this.runs === null;
  }

  /** Bytes `[start, end]` (inclusive), or null when they were not shipped. */
  slice(start: number, end: number): Uint8Array | null {
    if (!this.runs) return this.bytes.subarray(start, end + 1);
    for (const r of this.runs) {
      if (start >= r.start && end < r.end) {
        return this.bytes.subarray(r.at + start - r.start, r.at + end + 1 - r.start);
      }
    }
    return null;
  }

  private outside(what: string): BundledRead {
    const name = this.entry.label ?? 'this file';
    const where = this.entry.region ? ` (it holds ${this.entry.region})` : '';
    return {
      ok: false,
      status: 404,
      message: `${name}: ${what} is outside the region this offline bundle ships${where}`,
    };
  }

  /** The answer to one GET, ranged or not. */
  read(rangeHeader: string | null | undefined): BundledRead {
    const size = this.entry.size;
    const rng = parseByteRange(rangeHeader, size);
    if (rng === 'unsatisfiable') {
      return { ok: false, status: 416, message: `range ${rangeHeader} not satisfiable` };
    }
    if (rng === null) {
      if (!this.runs) return { ok: true, status: 200, bytes: this.bytes, contentRange: null };
      return this.outside('the whole file');
    }
    const bytes = this.slice(rng.start, rng.end);
    if (!bytes) return this.outside(`bytes ${rng.start}-${rng.end}`);
    return {
      ok: true,
      status: 206,
      bytes,
      contentRange: `bytes ${rng.start}-${rng.end}/${size}`,
    };
  }
}

/** The bundled-file key of a URL, or null when it is not one. */
export function bundledFileKey(url: string): string | null {
  if (!url.startsWith(JBROWSE_BUNDLE_ORIGIN)) return null;
  const key = url.slice(JBROWSE_BUNDLE_ORIGIN.length).split(/[?#]/, 1)[0];
  return key ? decodeURIComponent(key) : null;
}
