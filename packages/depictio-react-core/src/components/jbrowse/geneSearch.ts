/**
 * Gene-name search in the genome browser's locus box.
 *
 * A preset assembly has no text index (JBrowse's own demo ships a Trix one per
 * annotation), so typing "BCR" found nothing. This registers a text search
 * adapter, `DepictioGeneSearchAdapter`, that asks the backend
 * (`GET /jbrowse/preset/{name}/search`, which proxies UCSC with a cache) and
 * answers with loci. The locus box then navigates to a single hit, or lists
 * several, like it does for a Trix index.
 *
 * Plumbing, from `JBrowseRenderer`: the plugin goes in `plugins`, and
 * `geneSearchAdapterConfigs(assembly)` in `aggregateTextSearchAdapters` of
 * `createViewState`. Only for a preset assembly: a custom one has no UCSC
 * genome behind it, so it keeps JBrowse's own contig search.
 */
import BaseResult from '@jbrowse/core/TextSearch/BaseResults';
import Plugin from '@jbrowse/core/Plugin';
import type PluginManager from '@jbrowse/core/PluginManager';
import { ConfigurationSchema, readConfObject } from '@jbrowse/core/configuration';
import { BaseAdapter } from '@jbrowse/core/data_adapters/BaseAdapter';
import type { BaseTextSearchArgs } from '@jbrowse/core/data_adapters/BaseAdapter';
import TextSearchAdapterType from '@jbrowse/core/pluggableElementTypes/TextSearchAdapterType';

import { searchJBrowseGenes, type JBrowseGeneHit } from '../../api';

export const GENE_SEARCH_ADAPTER = 'DepictioGeneSearchAdapter';

/** What the backend accepts as `q` (see the search endpoint): anything else is
 *  a locus ("chr4:1-100"), a contig or free text, never a gene name. */
const GENE_QUERY = /^[A-Za-z0-9._-]{2,64}$/;

/** Whether `q` is worth a request. */
export function isGeneQuery(q: string): boolean {
  return GENE_QUERY.test(q.trim());
}

/** The hits to answer with: for an exact search (the user pressed Enter) the
 *  ones named like the query when there are any, else all of them, so "BCR"
 *  goes straight to BCR rather than to a list that also holds BCRP1. */
export function selectHits(
  hits: readonly JBrowseGeneHit[],
  q: string,
  searchType?: 'full' | 'prefix' | 'exact',
): JBrowseGeneHit[] {
  if (searchType !== 'exact') return [...hits];
  const needle = q.trim().toLowerCase();
  const exact = hits.filter((h) => h.label.toLowerCase() === needle);
  return exact.length ? exact : [...hits];
}

export const geneSearchConfigSchema = ConfigurationSchema(
  GENE_SEARCH_ADAPTER,
  {
    assemblyNames: {
      type: 'stringArray',
      defaultValue: [],
      description: 'Assemblies covered by the search',
    },
    assemblyName: {
      type: 'string',
      defaultValue: '',
      description: 'Preset name the backend searches the genes of',
    },
  },
  { explicitlyTyped: true, explicitIdentifier: 'textSearchAdapterId' },
);

/** One in-flight or settled request per (assembly, query): the locus box asks
 *  again as the user types and as the box re-renders. */
const REQUESTS = new Map<string, Promise<JBrowseGeneHit[]>>();
const MAX_REQUESTS = 50;

export class DepictioGeneSearchAdapter extends BaseAdapter {
  async searchIndex(args: BaseTextSearchArgs): Promise<BaseResult[]> {
    const q = args.queryString.trim();
    if (!isGeneQuery(q)) return [];
    const assembly = String(readConfObject(this.config, 'assemblyName') ?? '');
    if (!assembly) return [];
    const key = `${assembly}\u0000${q.toLowerCase()}`;
    let request = REQUESTS.get(key);
    if (!request) {
      if (REQUESTS.size >= MAX_REQUESTS) REQUESTS.delete(REQUESTS.keys().next().value as string);
      request = searchJBrowseGenes(assembly, q, 10);
      // A failed lookup (offline, UCSC down) is not remembered.
      request.catch(() => REQUESTS.delete(key));
      REQUESTS.set(key, request);
    }
    let hits: JBrowseGeneHit[];
    try {
      hits = await request;
    } catch (err) {
      // Search is a convenience: the box falls back to its contig search.
      console.warn('jbrowse: gene search failed', err);
      return [];
    }
    return selectHits(hits, q, args.searchType).map(
      (hit) =>
        new BaseResult({
          label: hit.label,
          displayString: hit.label,
          locString: hit.locus,
          matchedAttribute: 'name',
          matchedObject: { name: hit.label },
        }),
    );
  }
}

export default class DepictioGeneSearchPlugin extends Plugin {
  name = 'DepictioGeneSearchPlugin';

  install(pluginManager: PluginManager) {
    pluginManager.addTextSearchAdapterType(
      () =>
        new TextSearchAdapterType({
          name: GENE_SEARCH_ADAPTER,
          displayName: 'Depictio gene search',
          configSchema: geneSearchConfigSchema,
          description: 'Gene names of a preset assembly, searched through the Depictio API',
          AdapterClass: DepictioGeneSearchAdapter,
        } as ConstructorParameters<typeof TextSearchAdapterType>[0]),
    );
  }
}

/** The `aggregateTextSearchAdapters` entry covering one preset assembly. */
export function geneSearchAdapterConfigs(assemblyName: string): Array<Record<string, unknown>> {
  return [
    {
      type: GENE_SEARCH_ADAPTER,
      textSearchAdapterId: `depictio-gene-search-${assemblyName}`,
      assemblyNames: [assemblyName],
      assemblyName,
    },
  ];
}
