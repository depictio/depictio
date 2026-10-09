/**
 * The Delta version history panel's rules, and the timestamps it shows.
 *
 * Rows the API built from depictio's own records carry no Delta `version`.
 * They used to be labelled "recorded before Delta versions were captured",
 * which is false for a write whose commit merely fell outside the window read
 * (or for every row when the object store was unreachable), and they were
 * counted as commits. The hover time showed a clock time with no date.
 *
 * Run like tests/builder (the viewer package has no vitest of its own):
 *   pnpm --filter depictio-react-core exec vitest run --root ../../depictio/viewer tests/projects
 */
import { describe, expect, it } from 'vitest';
import type { DeltaVersionEntry } from 'depictio-react-core';

import {
  isUnmatchedRecord,
  orderHistory,
  summarizeHistory,
} from '../../src/projects/detail/deltaHistory';
import { absTime, clockTime, parseTs } from '../../src/monitoring/format';
import { formatDateTimeVerbose } from '../../src/lib/datetime';

const commit = (version: number, timestamp: string): DeltaVersionEntry => ({
  version,
  timestamp,
  origin: 'both',
});
const record = (aggregation_version: number, aggregation_time: string): DeltaVersionEntry => ({
  aggregation_version,
  aggregation_time,
  origin: 'mongo',
});

describe('Delta history rows', () => {
  it('treats a depictio record as unmatched, never as a commit', () => {
    expect(isUnmatchedRecord(record(3, '2026-10-01T09:00:00'))).toBe(true);
    expect(isUnmatchedRecord(commit(4, '2026-10-02T09:00:00'))).toBe(false);
  });

  it('counts records apart from commits, and flags a full page', () => {
    const versions = [commit(5, '2026-10-03T09:00:00'), record(2, '2026-09-01T09:00:00')];
    expect(summarizeHistory(versions, 20)).toEqual({
      commits: 1,
      unmatched: 1,
      mayBeTruncated: false,
    });
    expect(summarizeHistory(versions, 2).mayBeTruncated).toBe(true);
  });

  it("trusts the API's truncated flag over the page-full guess", () => {
    const versions = [commit(5, '2026-10-03T09:00:00'), record(2, '2026-09-01T09:00:00')];
    expect(summarizeHistory(versions, 2, false).mayBeTruncated).toBe(false);
    expect(summarizeHistory(versions, 20, true).mayBeTruncated).toBe(true);
  });

  it('keeps every row, records interleaved by time and undated rows last', () => {
    const undated: DeltaVersionEntry = { origin: 'mongo', aggregation_version: 1 };
    const versions = [
      commit(5, '2026-10-03T09:00:00'),
      commit(4, '2026-09-20T09:00:00'),
      undated,
      record(3, '2026-10-01T09:00:00'),
    ];
    const ordered = orderHistory(versions);
    expect(ordered).toHaveLength(versions.length);
    expect(ordered.map((e) => e.version ?? `r${e.aggregation_version}`)).toEqual([
      5,
      'r3',
      4,
      'r1',
    ]);
  });
});

describe('timestamps', () => {
  // The API sends naive UTC. Expected values are built from the same instant
  // in the host's zone, so the test holds in any TZ.
  const instant = new Date(Date.UTC(2026, 9, 1, 9, 5, 7));
  const pad = (n: number) => String(n).padStart(2, '0');

  it('reads a naive timestamp as UTC', () => {
    expect(parseTs('2026-10-01T09:05:07')).toBe(instant.getTime());
    expect(parseTs('2026-10-01T09:05:07.123456')).toBe(instant.getTime() + 123);
  });

  it('shows the date as well as the time', () => {
    const local =
      `${instant.getFullYear()}-${pad(instant.getMonth() + 1)}-${pad(instant.getDate())} ` +
      `${pad(instant.getHours())}:${pad(instant.getMinutes())}:${pad(instant.getSeconds())}`;
    expect(absTime('2026-10-01T09:05:07')).toBe(local);
    expect(clockTime('2026-10-01T09:05:07')).toBe(local.slice(11));
    expect(absTime(null)).toBe('—');
  });

  it('gives tooltips the date, the local time and the UTC time', () => {
    const verbose = formatDateTimeVerbose('2026-10-01T09:05:07');
    expect(verbose).toContain('2026-10-01 09:05:07 UTC');
    expect(verbose).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} /);
  });
});
