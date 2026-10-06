/**
 * Where filter-bar members go, and how a bar is put together — pure, so the
 * viewer, the editor, the cross-tab host and the tests all apply one rule.
 *
 * A filter bar is a grid section with `display: 'strip'`. The interactive
 * components naming it leave the left filter panel and render in the grid as
 * one compact row; everything else about them (their filter events, their
 * data) is unchanged. Their stored layout coordinates are ignored.
 */
import type { FilterSectionSpec, StoredMetadata } from '../../../api';

export function isStripSection(spec: FilterSectionSpec | null | undefined): boolean {
  return spec?.display === 'strip';
}

/** Names of the grid sections drawn as filter bars. */
export function stripSectionNames(
  gridSections: readonly FilterSectionSpec[] | null | undefined,
): Set<string> {
  return new Set((gridSections ?? []).filter(isStripSection).map((s) => s.name));
}

/**
 * Whether a component renders in a filter bar rather than in the panel.
 *
 * Interactive, not lifted to the footer (`placement: 'top'` wins: a Timeline
 * has no compact form), and naming a strip section. When a filter section of
 * the same name exists too, the bar wins: the author asked for it explicitly.
 */
export function isStripMember(
  m: Pick<StoredMetadata, 'component_type' | 'section' | 'placement'>,
  stripNames: ReadonlySet<string>,
): boolean {
  return (
    m.component_type === 'interactive' &&
    m.placement !== 'top' &&
    typeof m.section === 'string' &&
    stripNames.has(m.section)
  );
}

/** Split components into filter-bar members and everything else, order kept. */
export function partitionStripMembers<T extends Pick<StoredMetadata, 'component_type' | 'section' | 'placement'>>(
  components: readonly T[],
  stripNames: ReadonlySet<string>,
): { strip: T[]; rest: T[] } {
  const strip: T[] = [];
  const rest: T[] = [];
  for (const m of components) (isStripMember(m, stripNames) ? strip : rest).push(m);
  return { strip, rest };
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
 * Consecutive sections grouped for rendering: each filter bar alone, the
 * sections between bars together (they share one accordion, whose spacing and
 * fold state are per run).
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
