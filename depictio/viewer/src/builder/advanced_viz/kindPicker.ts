/**
 * How the viz-kind picker lays out the kinds: the one the component already
 * uses, the strong matches for the bound data collection, and the rest.
 *
 * Pure so the ordering can be tested without mounting the builder.
 */
import type {
  AdvancedVizKindDescriptor,
  StoredMetadata,
  VizKindSuggestion,
  VizSuggestionContext,
  VizSuggestionMatch,
} from 'depictio-react-core';
import { selectionEmitters } from './recordCardLink';

// Score at/above which a kind is surfaced under "Recommended" (mirrors
// RECOMMENDED_SCORE in depictio/models/components/advanced_viz/schemas.py).
// The score only ranks; the tile shows the qualitative `match` instead.
export const RECOMMENDED_SCORE = 0.8;

export interface MatchBadge {
  label: string;
  /** A Mantine theme colour name. */
  color: string;
}

const MATCH_BADGES: Record<VizSuggestionMatch, MatchBadge> = {
  named: { label: 'Named match', color: 'teal' },
  shape: { label: 'Shape match', color: 'blue' },
  context: { label: 'Fits your selection', color: 'violet' },
  weak: { label: 'Weak', color: 'gray' },
};

/** The qualitative badge for a suggestion: what kind of evidence it rests on,
 *  not how high it scored. Null when the API sent no `match` (older backend). */
export function matchBadge(suggestion: VizKindSuggestion | undefined): MatchBadge | null {
  const match = suggestion?.match;
  return match ? (MATCH_BADGES[match] ?? null) : null;
}

/** Tooltip lines for a kind tile: the reasons behind the match, then any
 *  required role the collection cannot fill. */
export function suggestionTooltip(suggestion: VizKindSuggestion | undefined): string[] {
  if (!suggestion) return [];
  const lines = [...(suggestion.reasons ?? [])];
  if (suggestion.unmet_roles.length) lines.push(`missing: ${suggestion.unmet_roles.join(', ')}`);
  return lines;
}

/**
 * What the suggestion endpoint should know about the tab the tile lands on:
 * the columns its selecting tiles emit (a record card needs one) and the
 * advanced-viz kinds already there. `selfIndex` is the component being edited,
 * which must not count as its own selection source.
 */
export function suggestionContextFor(
  metadata: readonly StoredMetadata[],
  selfIndex: string | null,
): VizSuggestionContext {
  const selectionColumns = new Set<string>();
  for (const e of selectionEmitters(metadata, selfIndex)) {
    if (e.column) selectionColumns.add(e.column);
  }
  const existingKinds = new Set<string>();
  for (const m of metadata) {
    if (selfIndex != null && String(m.index) === String(selfIndex)) continue;
    if (m.component_type === 'advanced_viz' && typeof m.viz_kind === 'string' && m.viz_kind) {
      existingKinds.add(m.viz_kind);
    }
  }
  return {
    selectionColumns: [...selectionColumns].sort(),
    existingKinds: [...existingKinds].sort(),
  };
}

export type RankedKind = { k: AdvancedVizKindDescriptor; suggestion?: VizKindSuggestion };

export interface KindPickerSections {
  /** The kind the component is bound to, whatever its fit score. */
  current: RankedKind | null;
  recommended: RankedKind[];
  other: RankedKind[];
}

/**
 * Split the kinds into the picker's sections.
 *
 * The selected kind is pulled out of the ranking and returned on its own.
 * Ranking it alongside the others is what made editing an existing component
 * look like the builder had guessed a different kind: the fit score describes
 * the collection, not the component, so a saved scatter or record card that
 * scores below RECOMMENDED_SCORE sank into the collapsed "Other
 * visualisations", and the only tiles on screen were unrelated recommendations
 * (a sunburst, a knee plot). The current kind is never filtered out by the
 * search box either, for the same reason.
 *
 * A legacy kind (`ma`, `qq`, `enrichment`, `roc_pr_curve`) is rewritten into a
 * view of the kind that survived it the moment it is saved, so it is never
 * offered, but it is still returned as `current` when a component carries it.
 */
export function partitionKinds(
  kinds: readonly AdvancedVizKindDescriptor[] | null,
  suggestions: readonly VizKindSuggestion[] | null,
  selectedKind: string | null,
  search = '',
): KindPickerSections {
  const scoreMap = new Map((suggestions ?? []).map((s) => [s.viz_kind, s] as const));
  const all = kinds ?? [];
  const currentDescriptor = selectedKind
    ? (all.find((k) => k.viz_kind === selectedKind) ?? null)
    : null;
  const current = currentDescriptor
    ? { k: currentDescriptor, suggestion: scoreMap.get(currentDescriptor.viz_kind) }
    : null;

  const q = search.trim().toLowerCase();
  const decorated: RankedKind[] = all
    .filter((k) => k.viz_kind !== selectedKind && !k.legacy)
    .filter(
      (k) => !q || k.label.toLowerCase().includes(q) || k.description.toLowerCase().includes(q),
    )
    .map((k) => ({ k, suggestion: scoreMap.get(k.viz_kind) }));
  const scoreOf = (d: RankedKind) => d.suggestion?.score ?? -1;
  decorated.sort((a, b) => scoreOf(b) - scoreOf(a) || a.k.label.localeCompare(b.k.label));

  // Until scores arrive (no DC bound / still loading) there is one flat list.
  if (suggestions == null) return { current, recommended: [], other: decorated };
  return {
    current,
    recommended: decorated.filter((d) => (d.suggestion?.score ?? 0) >= RECOMMENDED_SCORE),
    other: decorated.filter((d) => (d.suggestion?.score ?? 0) < RECOMMENDED_SCORE),
  };
}
