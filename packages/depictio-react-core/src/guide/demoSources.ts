/**
 * What the Guide's live demos are made of, picked from the dashboard itself.
 *
 * The demos use the dashboard's own components rather than invented ones: a
 * real key figure and a real filter on the same data, a real section that
 * folds. These are the pure choices behind them; the viewer does the fetching.
 */

import type { FilterSectionSpec, StoredMetadata } from '../api';
import { isStripSection } from '../components/interactive/strip/stripLayout';
import { sectionComponents } from '../utils/groupInteractive';

/** A key figure and a filter whose values change it. */
export interface GuideFilterDemoPick {
  card: StoredMetadata;
  control: StoredMetadata;
}

/** Controls that pick values from a list: the ones a reader can try at once. */
const CATEGORICAL = new Set(['MultiSelect', 'Select', 'SegmentedControl']);

const isCard = (m: StoredMetadata) => m.component_type === 'card' && Boolean(m.dc_id);
const isControl = (m: StoredMetadata) =>
  m.component_type === 'interactive' && Boolean(m.dc_id) && Boolean(m.column_name);
const isCategorical = (m: StoredMetadata) =>
  CATEGORICAL.has(String(m.interactive_component_type ?? ''));

/**
 * The first card that a filter on the same data collection can change, with
 * that filter — a categorical one when there is one. A card with no filter on
 * its data falls back to the first card and the first filter: the server
 * carries a filter across linked data collections, so it may still apply.
 */
export function pickFilterDemo(
  components: readonly StoredMetadata[],
): GuideFilterDemoPick | null {
  const cards = components.filter(isCard);
  const controls = components.filter(isControl);
  const ordered = [...controls.filter(isCategorical), ...controls.filter((m) => !isCategorical(m))];
  for (const card of cards) {
    const control = ordered.find((c) => c.dc_id === card.dc_id);
    if (control) return { card, control };
  }
  return cards[0] && ordered[0] ? { card: cards[0], control: ordered[0] } : null;
}

/** A section that folds, with what it holds. */
export interface GuideDemoSection {
  spec: FilterSectionSpec;
  members: StoredMetadata[];
}

/**
 * The sections of a tab that fold, in canvas order: named, holding something,
 * and neither `plain` (a heading with no fold) nor a filter bar.
 */
export function foldableSectionsOf(
  components: readonly StoredMetadata[],
  gridSections: readonly FilterSectionSpec[] | null | undefined,
): GuideDemoSection[] {
  return sectionComponents([...components], [...(gridSections ?? [])])
    .filter(
      (s) =>
        s.sectionName &&
        s.members.length > 0 &&
        s.spec?.appearance !== 'plain' &&
        !isStripSection(s.spec),
    )
    .map((s) => ({
      spec: s.spec ?? { name: s.sectionName as string },
      members: s.members,
    }));
}
