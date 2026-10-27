/**
 * `locus_from` is one source or a list of them (several collections, possibly
 * of several workflows: peaks, DE genes, variants). The first is the primary
 * one: it frames the view when the filters narrow it, carries the mate, and is
 * what "Use this region" filters on. Mirrors `locus_sources` in
 * `depictio/api/v1/services/jbrowse/render.py`.
 */
import type { JBrowseLocusFrom } from '../../api';

export interface NamedLocusSource extends JBrowseLocusFrom {
  name: string;
}

/** The sources of a tile, each with its name (the collection tag by default). */
export function locusSources(
  locusFrom: JBrowseLocusFrom | JBrowseLocusFrom[] | null | undefined,
): NamedLocusSource[] {
  if (!locusFrom) return [];
  const list = Array.isArray(locusFrom) ? locusFrom : [locusFrom];
  return list
    .filter((s): s is JBrowseLocusFrom => !!s && typeof s === 'object')
    .map((s) => ({ ...s, name: (s.name || s.data_collection_tag || '').trim() }));
}

/** The primary source, or null without `locus_from`. */
export function primaryLocusSource(
  locusFrom: JBrowseLocusFrom | JBrowseLocusFrom[] | null | undefined,
): NamedLocusSource | null {
  return locusSources(locusFrom)[0] ?? null;
}
