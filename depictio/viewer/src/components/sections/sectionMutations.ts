/**
 * Pure state transitions for dashboard sections.
 *
 * Sections are stored as two things that have to move together: a presentation
 * list on the dashboard (`filter_sections` / `grid_sections`) and a `section`
 * string on each member component inside `stored_metadata`. Renaming or deleting
 * a section therefore rewrites both, and getting only one of them right is the
 * failure mode this module exists to prevent.
 *
 * Kept free of React so `EditorApp` owns the single write path: the modal emits
 * an intent, `EditorApp` reduces it against `dashboardRef.current` (never
 * against a possibly-stale prop) and hands the result to the existing autosave.
 */
import type { DashboardData, FilterSectionSpec, StoredMetadata } from 'depictio-react-core';

/**
 * Which of the two section namespaces an operation addresses.
 *
 * They are deliberately independent lists that may share a name: a section
 * called "QC" in the filter panel and one in the grid are two different
 * placements that happen to be spelled the same.
 */
export type SectionKind = 'filter' | 'grid';

export type SectionOp =
  /** Write implicitly-used section names into the spec list so they can be given
   *  an icon and a colour. Does not change what renders. */
  | { op: 'materialize'; kind: SectionKind }
  | { op: 'create'; kind: SectionKind; spec: FilterSectionSpec }
  /** `patch.name` renames, which also retargets every member. Rename is not a
   *  separate op on purpose: editing a section is one form submit, and splitting
   *  it in two would make the second half depend on the first having already
   *  been reduced. */
  | { op: 'update'; kind: SectionKind; name: string; patch: Partial<FilterSectionSpec> }
  /** `target` null leaves members unsectioned, otherwise moves them there. */
  | { op: 'delete'; kind: SectionKind; name: string; target: string | null }
  | { op: 'move'; kind: SectionKind; name: string; dir: 'up' | 'down' }
  | { op: 'assign'; componentId: string; section: string | null };

const listKey = (kind: SectionKind) =>
  kind === 'filter' ? ('filter_sections' as const) : ('grid_sections' as const);

/**
 * Which namespace a component belongs to.
 *
 * A component carries one `section` string; whether it lands in the filter panel
 * or in the grid is decided by its type, exactly as `EditorApp` splits the two
 * render paths. Scoping every mutation by this predicate is what keeps a rename
 * in one tab from touching the identically-named section in the other.
 */
export const isFilterMember = (m: StoredMetadata): boolean =>
  m.component_type === 'interactive';

export const memberOf =
  (kind: SectionKind) =>
  (m: StoredMetadata): boolean =>
    kind === 'filter' ? isFilterMember(m) : !isFilterMember(m);

export const sectionsFor = (d: DashboardData, kind: SectionKind): FilterSectionSpec[] =>
  d[listKey(kind)] ?? [];

/** Section name → number of components in it, for one namespace. */
export function memberCounts(d: DashboardData, kind: SectionKind): Map<string, number> {
  const counts = new Map<string, number>();
  const isMember = memberOf(kind);
  for (const m of d.stored_metadata ?? []) {
    if (!isMember(m)) continue;
    const name = typeof m.section === 'string' ? m.section.trim() : '';
    if (!name) continue;
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return counts;
}

/** Section names in use by a namespace but absent from its spec list. */
export function implicitNames(d: DashboardData, kind: SectionKind): string[] {
  const declared = new Set(sectionsFor(d, kind).map((s) => s.name));
  const seen: string[] = [];
  const isMember = memberOf(kind);
  for (const m of d.stored_metadata ?? []) {
    if (!isMember(m)) continue;
    const name = typeof m.section === 'string' ? m.section.trim() : '';
    if (!name || declared.has(name) || seen.includes(name)) continue;
    seen.push(name);
  }
  return seen;
}

/**
 * Every component that must move when `componentId` does.
 *
 * Interactive components sharing a `group` render inside one card and the models
 * reject a group that spans two sections. That check lives on
 * `DashboardDataLite`, not on the `DashboardData` the save endpoint validates,
 * so a split group saves happily and only fails much later on YAML export —
 * moving the whole group is the only thing preventing it.
 */
export function groupWith(
  metadata: StoredMetadata[],
  componentId: string,
): Set<string> {
  const ids = new Set([componentId]);
  const target = metadata.find((m) => m.index === componentId);
  if (!target || !isFilterMember(target) || !target.group) return ids;
  for (const m of metadata) {
    if (isFilterMember(m) && m.group === target.group) ids.add(m.index);
  }
  return ids;
}

/** Rewrite `section` on the components a predicate selects. */
function retarget(
  d: DashboardData,
  select: (m: StoredMetadata) => boolean,
  section: string | undefined,
): StoredMetadata[] {
  return (d.stored_metadata ?? []).map((m) =>
    select(m) ? { ...m, section } : m,
  );
}

export function applySectionOp(d: DashboardData, op: SectionOp): DashboardData {
  switch (op.op) {
    case 'materialize': {
      const extra = implicitNames(d, op.kind);
      if (extra.length === 0) return d;
      // Appending in first-appearance order reproduces exactly the order
      // `sectionComponents` already derives (declared first, then undeclared in
      // first-appearance order), so materialising never moves anything.
      return {
        ...d,
        [listKey(op.kind)]: [
          ...sectionsFor(d, op.kind),
          ...extra.map((name) => ({ name })),
        ],
      };
    }

    case 'create': {
      const name = op.spec.name.trim();
      if (!name) return d;
      const list = sectionsFor(d, op.kind);
      if (list.some((s) => s.name.toLowerCase() === name.toLowerCase())) return d;
      return { ...d, [listKey(op.kind)]: [...list, { ...op.spec, name }] };
    }

    case 'update': {
      const list = sectionsFor(d, op.kind);
      const renamed = op.patch.name?.trim();
      const isRename = !!renamed && renamed !== op.name;
      if (isRename) {
        // Same-list collision only: the other namespace is a different section
        // that happens to share a name.
        const clash = list.some(
          (s) => s.name !== op.name && s.name.toLowerCase() === renamed.toLowerCase(),
        );
        if (clash) return d;
      }
      const patch = isRename ? { ...op.patch, name: renamed } : { ...op.patch, name: op.name };
      const next: DashboardData = {
        ...d,
        [listKey(op.kind)]: list.map((s) => (s.name === op.name ? { ...s, ...patch } : s)),
      };
      if (!isRename) return next;
      // Every member moves at once, so a rename can never leave an interactive
      // group straddling two sections.
      return {
        ...next,
        stored_metadata: retarget(
          d,
          (m) => memberOf(op.kind)(m) && m.section === op.name,
          renamed,
        ),
      };
    }

    case 'delete':
      return {
        ...d,
        [listKey(op.kind)]: sectionsFor(d, op.kind).filter((s) => s.name !== op.name),
        // `undefined`, never '': the bucketing treats a blank name as
        // unsectioned but JSON.stringify keeps an empty string, which would
        // persist a section nobody can see.
        stored_metadata: retarget(
          d,
          (m) => memberOf(op.kind)(m) && m.section === op.name,
          op.target ?? undefined,
        ),
      };

    case 'move': {
      const list = [...sectionsFor(d, op.kind)];
      const i = list.findIndex((s) => s.name === op.name);
      const j = op.dir === 'up' ? i - 1 : i + 1;
      if (i < 0 || j < 0 || j >= list.length) return d;
      [list[i], list[j]] = [list[j], list[i]];
      return { ...d, [listKey(op.kind)]: list };
    }

    case 'assign': {
      const ids = groupWith(d.stored_metadata ?? [], op.componentId);
      return {
        ...d,
        stored_metadata: retarget(
          d,
          (m) => ids.has(m.index),
          op.section?.trim() || undefined,
        ),
      };
    }
  }
}
