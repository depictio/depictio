/**
 * Which Delta commit the component-history modal should read, and the options
 * every data-version select offers (`buildDataVersionOptions`).
 *
 * Extracted from the modal so it can be executed by a check rather than
 * re-implemented in one: this feature twice passed a source review while not
 * working, so its decisions are worth testing directly.
 *
 * Three inputs, in precedence order. The order is the whole design — the two
 * axes ("which version of the chart" and "which version of the data") are
 * deliberately independent, and this is where that independence lives.
 */

import type { DataVersionPins } from 'depictio-react-core';

/** What the user picked in the dataset select, if anything.
 *
 *   `undefined` — no explicit choice; follow the version.
 *   `null`      — explicitly "current data", overriding the version.
 *   number      — an explicit commit.
 *
 * The three-way distinction matters: `null` and `undefined` mean opposite
 * things here, and collapsing them would make "show me this old chart against
 * today's data" unreachable.
 */
export type DataOverride = number | null | undefined;

export interface DataVersionChoice {
  dataOverride: DataOverride;
  /** The "Historical data" switch. Coarse form of the same question. */
  useHistoricalData: boolean;
  /** The Delta commit the selected dashboard version recorded, if any. */
  versionDataVersion: number | undefined;
}

/**
 * The commit to read, or `undefined` for current data.
 *
 * An explicit choice wins over the toggle, so the select is never silently
 * inert while the toggle disagrees with it.
 */
export function resolveDataVersion({
  dataOverride,
  useHistoricalData,
  versionDataVersion,
}: DataVersionChoice): number | undefined {
  if (dataOverride !== undefined) return dataOverride ?? undefined;
  if (!useHistoricalData) return undefined;
  return versionDataVersion;
}

/**
 * Pins for one collection at one commit.
 *
 * Guarded on `typeof === 'number'` rather than truthiness: commit 0 is falsy
 * and is the first commit, which is the one people most want to reach.
 */
export function pinsForComponent(
  dcId: string,
  dataVersion: number | undefined,
): Record<string, number> {
  return dcId && typeof dataVersion === 'number' ? { [dcId]: dataVersion } : {};
}

// ---------------------------------------------------------------------------
// The options a data-version select offers
// ---------------------------------------------------------------------------
//
// Every select that picks a data version lists the same things in the same
// words: the dataset picker, the component-history modal and each of its
// compare panes. They are built here, once, so the three cannot drift apart.
// Kept free of runtime imports so the dev checks can bundle this module alone.

/** Select value for "the data the selected dashboard version recorded".
 *  Mantine's Select needs a string, and an empty value is indistinguishable
 *  from nothing selected. */
export const VERSION_DEFAULT = '__version__';
/** Select value for "the latest data", overriding any recorded version. */
export const LIVE = '__live__';

export interface DataVersionOption {
  value: string;
  label: string;
}

/** The fields of a Delta commit an option label reads. Structural, so a
 *  `DeltaVersionEntry` fits without this module importing it. */
export interface CommitSummary {
  version?: number | null;
  rows_total?: number | null;
  rows_added?: number | null;
  operation?: string | null;
}

/** "150 rows · write": enough to recognise a commit without reading ids. */
export function describeCommit(commit: CommitSummary): string {
  const parts: string[] = [];
  if (typeof commit.rows_total === 'number') {
    parts.push(`${commit.rows_total.toLocaleString()} rows`);
  } else if (typeof commit.rows_added === 'number') {
    parts.push(`+${commit.rows_added.toLocaleString()} rows`);
  }
  if (commit.operation) parts.push(commit.operation.toLowerCase());
  return parts.join(' · ');
}

export interface DataVersionOptionsInput {
  /** The collection's commits, newest first. Ones without a Delta version are
   *  skipped: there is nothing to pin them to. */
  commits: readonly CommitSummary[];
  /** The table's newest commit, named in the "latest data" label. */
  currentVersion: number | null;
  /** Lead with "this version's data": set where the choice belongs to a
   *  stored dashboard version, whose recorded commit is then the default. */
  withVersionDefault?: boolean;
  /** The commit that dashboard version recorded; undefined when it recorded
   *  none, which the option then says rather than hiding itself. Hiding it
   *  would leave the select's default value matching no option at all. */
  versionDataVersion?: number;
}

/**
 * The options of one data-version select, in the order they are offered:
 * the version's own data (when bound to a version), the latest data, then
 * every commit.
 */
export function buildDataVersionOptions({
  commits,
  currentVersion,
  withVersionDefault = false,
  versionDataVersion,
}: DataVersionOptionsInput): DataVersionOption[] {
  const options: DataVersionOption[] = [];
  if (withVersionDefault) {
    options.push({
      value: VERSION_DEFAULT,
      label:
        typeof versionDataVersion === 'number'
          ? `This version's data (v${versionDataVersion})`
          : "This version's data (none recorded)",
    });
  }
  options.push({
    value: LIVE,
    label: typeof currentVersion === 'number' ? `Latest data (v${currentVersion})` : 'Latest data',
  });
  for (const commit of commits) {
    if (typeof commit.version !== 'number') continue;
    const detail = describeCommit(commit);
    options.push({
      value: String(commit.version),
      label: detail ? `v${commit.version} · ${detail}` : `v${commit.version}`,
    });
  }
  return options;
}

/** A `DataOverride` as the select value that shows it. */
export function dataOverrideToValue(override: DataOverride): string {
  if (override === undefined) return VERSION_DEFAULT;
  if (override === null) return LIVE;
  return String(override);
}

/** A select value back to the `DataOverride` it stands for. An empty value
 *  reads as "follow the version", the select's resting state. */
export function valueToDataOverride(value: string | null): DataOverride {
  if (!value || value === VERSION_DEFAULT) return undefined;
  if (value === LIVE) return null;
  return Number(value);
}

/** The pins after picking `value` in one collection's select: a commit pins
 *  that collection, the latest data (or an empty value) unpins it. Always a
 *  new object, so a switch replaces the previous pin rather than adding one. */
export function withPin(
  pins: DataVersionPins,
  dcId: string,
  value: string | null,
): DataVersionPins {
  const next = { ...pins };
  if (!value || value === LIVE) {
    delete next[dcId];
  } else {
    next[dcId] = Number(value);
  }
  return next;
}
