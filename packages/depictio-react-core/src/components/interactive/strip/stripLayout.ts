/**
 * Where filter-bar members go, and how a bar is put together — pure, so the
 * viewer, the editor, the cross-tab host and the tests all apply one rule.
 *
 * A grid section holds a filter bar in one of two ways:
 *
 * - `display: 'strip'`: the section IS the bar. Its filters filter the whole
 *   tab, exactly like the filter panel's.
 * - `filter_bar: true`: a section of tiles with a bar of its own under its
 *   heading. Its filters narrow that section's tiles only (`filterScope.ts`).
 *
 * Either way the interactive components naming the section leave the left
 * filter panel and render in the bar; everything else about them (their filter
 * events, their data) is unchanged, and their stored layout coordinates are
 * ignored.
 */
import type { FilterSectionSpec, StoredMetadata } from '../../../api';

/** A section drawn as a filter bar (`display: 'strip'`), filtering the tab. */
export function isStripSection(spec: FilterSectionSpec | null | undefined): boolean {
  return spec?.display === 'strip';
}

/** A section of tiles with a filter bar of its own, filtering only itself. */
export function hasSectionBar(spec: FilterSectionSpec | null | undefined): boolean {
  return Boolean(spec?.filter_bar) && !isStripSection(spec);
}

/** Either kind: a section whose interactive members render in a bar. */
export function isBarSection(spec: FilterSectionSpec | null | undefined): boolean {
  return isStripSection(spec) || hasSectionBar(spec);
}

/** Names of the grid sections whose interactive members render in a bar. */
export function barSectionNames(
  gridSections: readonly FilterSectionSpec[] | null | undefined,
): Set<string> {
  return new Set((gridSections ?? []).filter(isBarSection).map((s) => s.name));
}

/** Names of the grid sections carrying a bar of their own (`filter_bar`). */
export function sectionBarNames(
  gridSections: readonly FilterSectionSpec[] | null | undefined,
): Set<string> {
  return new Set((gridSections ?? []).filter(hasSectionBar).map((s) => s.name));
}

/**
 * Whether a component renders in a filter bar rather than in the panel.
 *
 * Interactive, not lifted to the footer (`placement: 'top'` wins: a Timeline
 * has no compact form), and naming a bar section (`barSectionNames`). When a
 * filter section of the same name exists too, the bar wins: the author asked
 * for it explicitly.
 */
export function isBarMember(
  m: Pick<StoredMetadata, 'component_type' | 'section' | 'placement'>,
  barNames: ReadonlySet<string>,
): boolean {
  return (
    m.component_type === 'interactive' &&
    m.placement !== 'top' &&
    typeof m.section === 'string' &&
    barNames.has(m.section)
  );
}

/** Split components into filter-bar members and everything else, order kept. */
export function partitionBarMembers<
  T extends Pick<StoredMetadata, 'component_type' | 'section' | 'placement'>,
>(components: readonly T[], barNames: ReadonlySet<string>): { bar: T[]; rest: T[] } {
  const bar: T[] = [];
  const rest: T[] = [];
  for (const m of components) (isBarMember(m, barNames) ? bar : rest).push(m);
  return { bar, rest };
}

/** What a section's own bar shows before "More filters" when the author sets
 *  nothing: enough to read as a bar, few enough to stay one line. */
export const SECTION_BAR_DEFAULT_VISIBLE = 2;

/**
 * How many of a bar's `total` filters show before its "More filters" toggle:
 * the author's `visible_filters`, else 2 on a section's own bar and every
 * filter on a `display: 'strip'` bar (which predates the toggle).
 */
export function visibleFilterCount(
  spec: FilterSectionSpec | null | undefined,
  total: number,
): number {
  const own = spec?.visible_filters;
  const wanted =
    typeof own === 'number' && Number.isFinite(own) && own >= 1
      ? Math.floor(own)
      : hasSectionBar(spec)
        ? SECTION_BAR_DEFAULT_VISIBLE
        : total;
  return Math.max(0, Math.min(total, wanted));
}

/** The compact control a filter bar draws for each interactive type. */
export type StripControlKind = 'categorical' | 'range' | 'slider' | 'toggle' | 'date' | 'unsupported';

export function stripControlKind(interactiveType: string | undefined): StripControlKind {
  switch (interactiveType) {
    case 'MultiSelect':
    case 'Select':
    case 'SegmentedControl':
      return 'categorical';
    case 'RangeSlider':
      return 'range';
    case 'Slider':
      return 'slider';
    case 'Switch':
    case 'Checkbox':
      return 'toggle';
    case 'DatePicker':
    case 'DateRangePicker':
      return 'date';
    default:
      return 'unsupported';
  }
}

/** The label a bar shows: the author's short label, else the title. */
export function stripLabel(m: Pick<StoredMetadata, 'strip_label'>, title: string): string {
  const short = typeof m.strip_label === 'string' ? m.strip_label.trim() : '';
  return short || title;
}

/** The icon badge is on unless the author switched it off. */
export function stripShowsIcon(m: Pick<StoredMetadata, 'strip_icon'>): boolean {
  return m.strip_icon !== false;
}

/** Whether a range covers the column's whole extent — i.e. filters nothing. */
export function isFullRange(range: readonly [number, number], min: number, max: number): boolean {
  return range[0] <= min && range[1] >= max;
}

export type SectionRun<T> = { strip: true; section: T } | { strip: false; sections: T[] };

/**
 * Consecutive sections grouped for rendering: each `display: 'strip'` bar
 * alone, the sections between bars together (they share one accordion, whose
 * spacing and fold state are per run). A section with a bar of its own is an
 * ordinary accordion section: its bar is drawn inside it.
 */
export function sectionRuns<T>(sections: readonly T[], isStrip: (s: T) => boolean): SectionRun<T>[] {
  const runs: SectionRun<T>[] = [];
  for (const s of sections) {
    if (isStrip(s)) {
      runs.push({ strip: true, section: s });
      continue;
    }
    const last = runs[runs.length - 1];
    if (last && !last.strip) last.sections.push(s);
    else runs.push({ strip: false, sections: [s] });
  }
  return runs;
}
