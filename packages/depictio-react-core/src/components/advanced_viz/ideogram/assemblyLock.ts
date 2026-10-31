/**
 * Whether the config pins the assembly, so the viewer has no business
 * offering another one.
 *
 * A template that states `assembly: hg38` knows which genome its data was
 * called on; an Assembly menu listing hg19 and mm10 next to it only invites a
 * pick that mis-scales every bar. A template that leaves the key null (the
 * data decides) or carries an unresolved `{GENOME}` placeholder pins nothing,
 * and keeps the menu. `lock_assembly` overrides the inference either way.
 */

/** A value still holding a template placeholder (`{GENOME}`, `${GENOME}`). */
function isPlaceholder(value: string): boolean {
  return /[{}$]/.test(value);
}

/** The assembly a config pins, or null when it pins none. */
export function pinnedAssembly(config: { assembly?: string | null }): string | null {
  const raw = typeof config.assembly === 'string' ? config.assembly.trim() : '';
  return raw !== '' && !isPlaceholder(raw) ? raw : null;
}

/**
 * Whether the Assembly menu is withheld and a persisted pick ignored.
 * `lock_assembly` true/false is the author's word; unset locks exactly when
 * the config pins an assembly.
 */
export function isAssemblyLocked(config: {
  assembly?: string | null;
  lock_assembly?: boolean | null;
}): boolean {
  if (typeof config.lock_assembly === 'boolean') return config.lock_assembly;
  return pinnedAssembly(config) !== null;
}
