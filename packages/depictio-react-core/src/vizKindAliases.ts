/**
 * Advanced-viz kinds that were renamed, old name to current name.
 *
 * A stored dashboard may still carry the old name, and `stored_metadata` reaches
 * the client unvalidated, so the rewrite happens here, where a dashboard enters
 * the client: from then on every label, picker and renderer lookup sees the
 * current name. It reaches the server only if the user saves.
 */
export const RENAMED_VIZ_KINDS: Readonly<Record<string, string>> = {
  stacked_taxonomy: 'stacked_bar',
};

/** The current name of a kind: itself unless it was renamed. */
export function canonicalVizKind(kind: string): string {
  return RENAMED_VIZ_KINDS[kind] ?? kind;
}

/**
 * Rewrite every `viz_kind` naming a renamed kind, in place, anywhere in a
 * freshly parsed response (a tile's own `viz_kind` and its `config.viz_kind`).
 * Returns the same object so a fetch can `return canonicalizeVizKinds(data)`.
 */
export function canonicalizeVizKinds<T>(value: T): T {
  if (Array.isArray(value)) {
    for (const item of value) canonicalizeVizKinds(item);
  } else if (value !== null && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const kind = record.viz_kind;
    if (typeof kind === 'string' && kind in RENAMED_VIZ_KINDS) {
      record.viz_kind = RENAMED_VIZ_KINDS[kind];
    }
    for (const key of Object.keys(record)) canonicalizeVizKinds(record[key]);
  }
  return value;
}
