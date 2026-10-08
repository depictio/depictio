/**
 * Which Delta commit the component-history modal should read.
 *
 * Extracted from the modal so it can be executed by a check rather than
 * re-implemented in one: this feature twice passed a source review while not
 * working, so its decisions are worth testing directly.
 *
 * Three inputs, in precedence order. The order is the whole design — the two
 * axes ("which version of the chart" and "which version of the data") are
 * deliberately independent, and this is where that independence lives.
 */

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
