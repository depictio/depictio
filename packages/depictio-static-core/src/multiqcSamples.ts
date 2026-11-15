/**
 * The MultiQC sample set of a filter state — the set algebra of the server's
 * `_resolve_multiqc_sample_filter`: every constraint (a direct sample filter,
 * or one metadata collection's pooled link values) expanded to report
 * variants, then INTERSECTED. `null` when there is no constraint (render
 * unfiltered); `[]` when the constraints share no sample (render empty).
 */
export function intersectSampleConstraints(
  constraints: readonly (readonly string[])[],
  expansion: Readonly<Record<string, readonly string[]>> | null = null,
): string[] | null {
  if (constraints.length === 0) return null;
  const expand = (values: readonly string[]) => {
    const out = new Set<string>();
    for (const v of values) {
      out.add(v);
      for (const variant of expansion?.[v] ?? []) out.add(String(variant));
    }
    return out;
  };
  let surviving = expand(constraints[0]);
  for (const c of constraints.slice(1)) {
    const next = expand(c);
    surviving = new Set([...surviving].filter((s) => next.has(s)));
  }
  return [...surviving].sort();
}
