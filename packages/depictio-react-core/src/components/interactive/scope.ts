/**
 * The scope of a tab that shows one unit at a time: its `always_selected`
 * Select filters (see `alwaysSelected.ts`), the unit each one holds, and the
 * facts the scope banner reads about it.
 *
 * Pure, so the banner, the tiles' unit chip and the automatic pick agree on
 * which filters set the scope.
 */
import type { BannerFact, StoredMetadata } from '../../api';
import type { FilterScopes } from '../../filterScope';
import { formatNumber } from '../card/metrics/format';
import { isAlwaysSelected, type PickableOption } from './alwaysSelected';
import { interactiveAccentRaw } from './frame';

/** Every `always_selected` interactive component, once per index. */
export function alwaysSelectedComponents(
  components: readonly StoredMetadata[],
): StoredMetadata[] {
  const seen = new Set<string>();
  return components.filter((m) => {
    if (m.component_type !== 'interactive' || !isAlwaysSelected(m) || seen.has(m.index)) {
      return false;
    }
    seen.add(m.index);
    return true;
  });
}

/**
 * The filters that set a tab's scope: its `always_selected` Selects, less
 * those on a section's own filter bar, whose value only reaches that section
 * and so says nothing about the tab as a whole.
 */
export function scopeUnits(
  components: readonly StoredMetadata[],
  filterScopes?: FilterScopes | null,
): StoredMetadata[] {
  return alwaysSelectedComponents(components).filter((m) => !filterScopes?.has(m.index));
}

/**
 * The colour of the unit chip on the tiles: the filter's own accent when one
 * filter sets the scope (undefined, the primary, when it has none), neutral
 * when several do, since the chip cannot say which of them a tile follows.
 */
export function scopeChipColor(units: readonly StoredMetadata[]): string | undefined {
  if (units.length !== 1) return 'gray';
  return interactiveAccentRaw(units[0]);
}

export interface BannerFactItem {
  label: string;
  text: string;
}

/**
 * The facts a banner shows for the row of the picked value: numbers in the
 * fact's format, text as it is. A fact whose column the row lacks, or holds
 * empty, is left out rather than shown blank.
 */
export function bannerFactItems(
  facts: readonly BannerFact[] | null | undefined,
  row: Record<string, unknown> | null | undefined,
): BannerFactItem[] {
  if (!facts || !row) return [];
  const items: BannerFactItem[] = [];
  for (const fact of facts) {
    const v = row[fact.column];
    let text: string | null = null;
    if (typeof v === 'number') text = Number.isFinite(v) ? formatNumber(v, fact.format) : null;
    else if (typeof v === 'string') text = v.trim() || null;
    else if (typeof v === 'boolean') text = v ? 'yes' : 'no';
    if (text !== null) items.push({ label: fact.label, text });
  }
  return items;
}

/** The columns a banner asks the row lookup for, once each. */
export function bannerFactColumns(facts: readonly BannerFact[] | null | undefined): string[] {
  return [...new Set((facts ?? []).map((f) => f.column))];
}

/** Where the held unit sits among the ones on offer, for the banner's
 *  previous and next keys. */
export interface UnitSteps {
  /** 1-based rank of the held value among the offered ones; 0 when it is not
   *  offered (another filter took it out, or nothing is held yet). */
  position: number;
  total: number;
  prev: string | null;
  next: string | null;
}

/**
 * The neighbours of `current` in `options` (already in the order the reader
 * sees them, `default_by` first), skipping the ones other filters rule out.
 * No wrap-around: the ends are where the keys stop, so "3 / 12" always means
 * the same thing. A held value that is not on offer steps forward to the
 * first one that is.
 */
export function unitSteps(
  options: readonly PickableOption[],
  current: string | undefined,
): UnitSteps {
  const offered = options.filter((o) => !o.disabled).map((o) => o.value);
  const i = current === undefined ? -1 : offered.indexOf(current);
  if (i < 0) return { position: 0, total: offered.length, prev: null, next: offered[0] ?? null };
  return {
    position: i + 1,
    total: offered.length,
    prev: offered[i - 1] ?? null,
    next: offered[i + 1] ?? null,
  };
}
