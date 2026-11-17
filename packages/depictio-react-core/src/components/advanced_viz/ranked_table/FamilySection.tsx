import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Icon } from '@iconify/react';
import { Loader, Text, UnstyledButton } from '@mantine/core';

import { fetchAdvancedVizData, type StoredMetadata } from '../../../api';
import { isStaleFetch } from '../../../fetchQueue';
import { buildPedigree, type ColumnarRows, type PedigreeFamily } from '../pedigree/pedigreeLayout';
import FamilyPedigree from './FamilyPedigree';
import { familyFetchFilters } from './familyRequests';
import {
  carriersFromLong,
  carriersFromRow,
  findProband,
  type GenotypeClass,
  type MissingAs,
} from './familyData';

/** The family-related keys of `RankedTableConfig` (configs.py). */
export interface FamilyConfig {
  family_dc_id?: string | null;
  family_wf_id?: string | null;
  family_dc_tag?: string | null;
  family_individual_col: string;
  family_father_col: string;
  family_mother_col: string;
  family_sex_col: string;
  family_status_col: string;
  family_proband_col?: string | null;
  family_label_col?: string | null;
  family_family_col?: string | null;
  family_row_col?: string | null;
  genotype_columns?: Record<string, string> | null;
  genotypes_dc_id?: string | null;
  genotypes_wf_id?: string | null;
  genotypes_dc_tag?: string | null;
  genotypes_key_col: string;
  genotypes_row_col?: string | null;
  genotypes_individual_col: string;
  genotypes_genotype_col: string;
  /** What a person with no genotype row is drawn as (default `missing`). */
  genotypes_missing_as?: MissingAs | null;
}

/** Whether the config binds a family at all: no pedigree collection, no section. */
export function hasFamily(config: Partial<FamilyConfig>): boolean {
  return Boolean(config.family_dc_tag || config.family_dc_id);
}

/** The columns of the row the section reads: the family and the variant key,
 *  and every column a genotype is read from. */
export function familyRowColumns(config: Partial<FamilyConfig>, keyFallback: string): string[] {
  if (!hasFamily(config)) return [];
  const out: string[] = [];
  if (config.family_row_col) out.push(config.family_row_col);
  if (config.genotypes_dc_tag || config.genotypes_dc_id) {
    out.push(config.genotypes_row_col || keyFallback);
  }
  out.push(...Object.values(config.genotype_columns ?? {}));
  return out.filter((c, i) => out.indexOf(c) === i);
}

/** What the section needs to know about the pinned row. */
export interface PinnedRowValues {
  /** Value of `family_row_col` on the row. */
  family: string | null;
  /** Value of the variant key (long genotype table). */
  key: string | null;
  /** Any column of the row, for `genotype_columns`. */
  cell: (column: string) => unknown;
}

interface FamilyData {
  family: PedigreeFamily | null;
  carriers: Map<string, GenotypeClass> | null;
  probandKey: string | null;
}

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: FamilyData };

/**
 * Read the pedigree table and the genotypes of one pinned row, once the section
 * is open. Results are kept by request, so pinning the same row again, or
 * another row of the same family, costs no fetch.
 */
function useFamilyData(
  open: boolean,
  config: FamilyConfig,
  metadata: StoredMetadata,
  row: PinnedRowValues,
): State {
  const cache = useRef(new Map<string, FamilyData>());
  const [state, setState] = useState<State>({ status: 'loading' });
  const longTable = Boolean(config.genotypes_dc_tag || config.genotypes_dc_id);
  const cellKey = JSON.stringify(
    Object.values(config.genotype_columns ?? {}).map((c) => row.cell(c)),
  );
  const requestKey = JSON.stringify([
    config.family_dc_id,
    row.family,
    longTable ? row.key : null,
    longTable ? null : cellKey,
    config.genotypes_missing_as ?? null,
  ]);

  useEffect(() => {
    if (!open) return;
    if (!config.family_dc_id || !config.family_wf_id) {
      setState({
        status: 'error',
        message: 'The family collection is not available in this project.',
      });
      return;
    }
    const cached = cache.current.get(requestKey);
    if (cached) {
      setState({ status: 'ready', data: cached });
      return;
    }
    let cancelled = false;
    const ctrl = new AbortController();
    setState({ status: 'loading' });

    const pedigreeColumns = {
      individual: config.family_individual_col,
      father: config.family_father_col,
      mother: config.family_mother_col,
      sex: config.family_sex_col,
      status: config.family_status_col,
      label: config.family_label_col,
    };
    const wanted = [
      ...Object.values(pedigreeColumns),
      config.family_proband_col,
      config.family_family_col,
    ].filter((c, i, all): c is string => Boolean(c) && all.indexOf(c) === i);
    // The pinned row's own family and variant, never the dashboard's filters.
    const fetchFilters = familyFetchFilters(config, metadata, row);

    const pedigree = fetchAdvancedVizData(
      {
        wfId: config.family_wf_id,
        dcId: config.family_dc_id,
        columns: wanted,
        filters: fetchFilters.pedigree,
        vizKind: 'pedigree',
        roles: {
          individual: pedigreeColumns.individual,
          father: pedigreeColumns.father,
          mother: pedigreeColumns.mother,
          sex: pedigreeColumns.sex,
          status: pedigreeColumns.status,
        },
      },
      ctrl.signal,
    );
    const genotypes: Promise<ColumnarRows | null> =
      longTable && config.genotypes_dc_id && config.genotypes_wf_id && row.key
        ? fetchAdvancedVizData(
            {
              wfId: config.genotypes_wf_id,
              dcId: config.genotypes_dc_id,
              columns: [
                config.genotypes_key_col,
                config.genotypes_individual_col,
                config.genotypes_genotype_col,
              ],
              filters: fetchFilters.genotypes,
              vizKind: 'ranked_table',
            },
            ctrl.signal,
          ).then((res) => res.rows)
        : Promise.resolve(null);

    Promise.all([pedigree, genotypes])
      .then(([ped, long]) => {
        if (cancelled) return;
        const built = buildPedigree(
          ped.rows,
          { ...pedigreeColumns, family: config.family_family_col },
          { maxIndividuals: 60, maxFamilies: 1 },
        );
        const family = built.families[0] ?? null;
        const people = family?.people ?? [];
        const probandKey = findProband(people, config.family_proband_col);
        const missingAs: MissingAs = config.genotypes_missing_as === 'ref' ? 'ref' : 'missing';
        let carriers: Map<string, GenotypeClass> | null = null;
        if (long) {
          carriers = carriersFromLong(
            people,
            long,
            {
              individual: config.genotypes_individual_col,
              genotype: config.genotypes_genotype_col,
            },
            missingAs,
          );
        } else if (config.genotype_columns && Object.keys(config.genotype_columns).length > 0) {
          carriers = carriersFromRow(people, probandKey, config.genotype_columns, row.cell, missingAs);
        }
        const data: FamilyData = { family, carriers, probandKey };
        cache.current.set(requestKey, data);
        setState({ status: 'ready', data });
      })
      .catch((err: unknown) => {
        if (cancelled || isStaleFetch(err)) return;
        setState({ status: 'error', message: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
    // `row.cell` and `config` are read through the request key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, requestKey]);

  return state;
}

interface Props {
  open: boolean;
  onToggle: () => void;
  config: FamilyConfig;
  metadata: StoredMetadata;
  row: PinnedRowValues;
}

/** The collapsible "Family" section of the pinned popover. */
const FamilySection: React.FC<Props> = ({ open, onToggle, config, metadata, row }) => {
  const state = useFamilyData(open, config, metadata, row);
  const body = useMemo(() => {
    if (!open) return null;
    if (state.status === 'loading') {
      return (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 12 }}>
          <Loader size="sm" />
        </div>
      );
    }
    if (state.status === 'error') {
      return (
        <Text size="xs" c="red">
          {state.message}
        </Text>
      );
    }
    const { family, carriers, probandKey } = state.data;
    if (!family || family.people.length === 0) {
      return (
        <Text size="xs" c="dimmed">
          No family found for this row.
        </Text>
      );
    }
    return <FamilyPedigree family={family} carriers={carriers} probandKey={probandKey} />;
  }, [open, state]);

  return (
    <div
      style={{
        marginTop: 10,
        paddingTop: 6,
        borderTop: '1px solid var(--mantine-color-default-border)',
      }}
    >
      <UnstyledButton
        onClick={onToggle}
        aria-expanded={open}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          width: '100%',
          fontSize: 'var(--mantine-font-size-xs)',
          fontWeight: 600,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          color: 'var(--mantine-color-dimmed)',
        }}
      >
        <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />
        Family
      </UnstyledButton>
      {body ? <div style={{ marginTop: 6 }}>{body}</div> : null}
    </div>
  );
};

export default FamilySection;
