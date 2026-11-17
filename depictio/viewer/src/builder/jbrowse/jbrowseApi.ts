/**
 * Builder-only reads for the genome browser form: the reference assemblies and
 * the named config presets the backend ships (depictio/api/v1/endpoints/
 * jbrowse_endpoints/routes.py). Both lists are static per deployment, so they
 * are fetched once per page load and shared by every builder mount.
 */
import { authFetch } from 'depictio-react-core';

const API_BASE = '/depictio/api/v1';

export interface JBrowseAssemblyOption {
  name: string;
  display_name: string;
  organism: string;
  aliases: string[];
  has_annotation: boolean;
  default_location: string | null;
}

export interface JBrowsePresetOption {
  name: string;
  description: string;
}

let assembliesPromise: Promise<JBrowseAssemblyOption[]> | null = null;
let presetsPromise: Promise<JBrowsePresetOption[]> | null = null;

async function getList<T>(path: string): Promise<T[]> {
  const res = await authFetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`Failed to fetch ${path}: ${res.status}`);
  const body = await res.json();
  return Array.isArray(body) ? (body as T[]) : [];
}

/** A failed fetch is not cached, so reopening the builder retries it. */
export function fetchJBrowseAssemblies(): Promise<JBrowseAssemblyOption[]> {
  assembliesPromise ??= getList<JBrowseAssemblyOption>('/jbrowse/assemblies').catch((e) => {
    assembliesPromise = null;
    throw e;
  });
  return assembliesPromise;
}

export function fetchJBrowsePresets(): Promise<JBrowsePresetOption[]> {
  presetsPromise ??= getList<JBrowsePresetOption>('/jbrowse/presets').catch((e) => {
    presetsPromise = null;
    throw e;
  });
  return presetsPromise;
}

/** The subset of a genomic_tracks DC's `dc_specific_properties` the form reads. */
export interface GenomicTracksProps {
  /** The DC's `type`: `genomic_tracks`, or `jbrowse2` for a legacy collection. */
  dcType: string | null;
  assembly: string | null;
  sampleColumn: string | null;
  trackIdColumn: string | null;
  nameColumn: string | null;
  formatColumn: string | null;
  uriColumn: string;
  presets: JBrowsePresetOption[];
}

/** Reads the DC config returned by `fetchDataCollectionConfig`. The assembly is
 *  either a preset name or a custom-assembly object, which is named by `name`. */
export function readGenomicTracksProps(cfg: Record<string, unknown> | null): GenomicTracksProps {
  // `/datacollections/specs/{id}` nests the type and properties under `config`;
  // a bare config (tests, older callers) carries them at the top level.
  const root = ((cfg?.config as Record<string, unknown> | undefined) ?? cfg ?? {}) as Record<
    string,
    unknown
  >;
  const props = (root.dc_specific_properties ?? {}) as Record<string, unknown>;
  const rawAssembly = props.assembly;
  const assembly =
    typeof rawAssembly === 'string'
      ? rawAssembly
      : rawAssembly && typeof rawAssembly === 'object'
        ? String((rawAssembly as { name?: unknown }).name ?? '') || null
        : null;
  const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
  const rawPresets = (props.presets ?? {}) as Record<string, unknown>;
  const presets = Object.entries(rawPresets).map(([name, frag]) => ({
    name,
    description: str((frag as { description?: unknown } | null)?.description) ?? '',
  }));
  return {
    dcType: str(root.type)?.toLowerCase() ?? null,
    assembly,
    sampleColumn: str(props.sample_column),
    trackIdColumn: str(props.track_id_column),
    nameColumn: str(props.name_column),
    formatColumn: str(props.format_column),
    uriColumn: str(props.uri_column) ?? 'uri',
    presets,
  };
}
