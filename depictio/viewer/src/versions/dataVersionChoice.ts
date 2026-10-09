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

import type {
  DashboardVersionDetail,
  DataVersionPins,
  StoredMetadata,
} from 'depictio-react-core';

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

/** Find a component inside a stored version: on its own tab, by id.
 *
 * A version holds the whole tab family, and a component id is only unique
 * within a tab (ids derive from tags, which two tabs may share). Taking the
 * first match across tabs showed, and restored, a sibling tab's component.
 *
 * Returns null when the version predates the component (or its tab), which
 * is a normal outcome worth stating rather than an error: it is exactly the
 * answer to "when did this first appear?". */
export function componentInVersion(
  version: Pick<DashboardVersionDetail, 'tabs'>,
  tabId: string,
  index: string,
): StoredMetadata | null {
  const tab = (version.tabs || []).find((t) => String(t.dashboard_id) === tabId);
  for (const component of tab?.stored_metadata || []) {
    const candidate = component as Record<string, unknown>;
    if (String(candidate.index ?? '') === index) return component as StoredMetadata;
  }
  return null;
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

/** What one pane of the component-history modal asks the server for: which
 *  data (`pins`) and whose definition (`definitionVersionId`, null for the
 *  live component). */
export interface PaneRequest {
  pins: Record<string, number>;
  definitionVersionId: string | null;
}

/**
 * The request behind one pane.
 *
 * The past pane passes the version it shows; the compare pane passes null,
 * so it draws the live definition, and a choice that ignores the version's
 * stamp (`useHistoricalData: false`, no `versionDataVersion`), so it defaults
 * to live data. Both panes go through here, so the two axes stay independent
 * in exactly one place.
 */
export function paneRequest(
  dcId: string,
  choice: DataVersionChoice,
  definitionVersionId: string | null,
): PaneRequest {
  return {
    pins: pinsForComponent(dcId, resolveDataVersion(choice)),
    definitionVersionId,
  };
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

/**
 * The pins after picking `value` in one collection's select. Always a new
 * object, so a switch replaces the previous pin rather than adding one.
 *
 *   a commit             pins that collection to it;
 *   `VERSION_DEFAULT`    drops the collection's own pin, so it follows the
 *                        version's data again (or the latest data, with none);
 *   `LIVE`               the latest data. Under a version's data (`asOf`) that
 *                        is an explicit `null`, which the server reads as "stay
 *                        live" for this collection; deleting the key instead
 *                        would leave it on the version's commit, so picking
 *                        "Latest data" would do nothing. Without a version a
 *                        missing key already means live, and keeping it
 *                        missing leaves the request byte-identical.
 */
export function withPin(
  pins: DataVersionPins,
  dcId: string,
  value: string | null,
  asOf = false,
): DataVersionPins {
  const next = { ...pins };
  if (!value || value === VERSION_DEFAULT) {
    delete next[dcId];
  } else if (value === LIVE) {
    if (asOf) next[dcId] = null;
    else delete next[dcId];
  } else {
    next[dcId] = Number(value);
  }
  return next;
}

/** The select value showing one collection's pin. Under a version's data a
 *  collection with no pin of its own follows that version (`VERSION_DEFAULT`);
 *  without one it is on its latest data. */
export function pinToValue(pin: number | null | undefined, asOf: boolean): string {
  if (typeof pin === 'number') return String(pin);
  if (pin === null) return LIVE;
  return asOf ? VERSION_DEFAULT : LIVE;
}
