import type { ProjectProvenance } from './api';
import { compareVersions, formatVersion } from './versions';

export type ProvenanceState = 'legacy' | 'same' | 'older' | 'newer' | 'unknown_running';

export interface ProvenanceBadgeInfo {
  label: string;
  state: ProvenanceState;
  tooltipLines: string[];
}

/** What the project header says about the Depictio version behind a project.
 *  The project version is `created_with_version` (carried across imports),
 *  else the source version of the first import hop. */
export function provenanceBadge(
  provenance: ProjectProvenance | null | undefined,
  runningVersion: string | null | undefined,
): ProvenanceBadgeInfo {
  const hops = provenance?.imported_from ?? [];
  const version = provenance?.created_with_version || hops[0]?.source_depictio_version || null;
  if (!version) {
    return {
      label: 'Depictio: unknown',
      state: 'legacy',
      tooltipLines: ['Created before version tracking'],
    };
  }

  const lines = [`Created with ${formatVersion(version)}`];
  for (const hop of hops) {
    const exported = hop.source_depictio_version
      ? `exported with ${formatVersion(hop.source_depictio_version)}, `
      : '';
    lines.push(
      `Imported on ${hop.imported_at} from ${hop.source_instance} (${exported}via ${hop.via})`,
    );
  }

  let state: ProvenanceState = 'unknown_running';
  if (runningVersion) {
    lines.push(`Running instance: ${formatVersion(runningVersion)}`);
    const cmp = compareVersions(version, runningVersion);
    if (cmp === 0) state = 'same';
    else if (cmp < 0) {
      state = 'older';
      lines.push('Created with an older version: migrated to this instance');
    } else {
      state = 'newer';
      lines.push('Warning: created with a newer version than this instance runs');
    }
  } else {
    lines.push('Running instance: unknown');
  }
  return { label: `Depictio ${formatVersion(version)}`, state, tooltipLines: lines };
}
