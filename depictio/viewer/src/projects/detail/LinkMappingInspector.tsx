import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Code,
  Collapse,
  Group,
  Loader,
  Modal,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
  Tooltip,
  useMantineColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';

import { fetchLinkMappingPreview, useBrandAccents } from 'depictio-react-core';
import type {
  DCLink,
  LinkMappingPreviewResponse,
  LinkMappingPreviewRow,
} from 'depictio-react-core';

// ---------------------------------------------------------------------------
// Mapping inspection (issue #938)
// ---------------------------------------------------------------------------

/** How the source value was matched — not how the resolved names relate to
 *  it. `exact` in particular expands the canonical ID to every MultiQC
 *  variant recorded for it (`S1`, `S1 - First read`, …), so the label names
 *  the *lookup rule* and the tooltip spells out the expansion.
 *
 *  Keys cover both vocabularies the endpoint emits: the sample-matching ones
 *  (`exact` / `variant` / `base` / `source-suffix`) for `sample_mapping`
 *  links, and the resolver's own name for every other resolver. */
const VIA_LABELS: Record<string, { label: string; help: string }> = {
  exact: {
    label: 'Canonical ID',
    help: 'The value is a mapping key. It resolves to the canonical ID plus every MultiQC variant name recorded for it.',
  },
  variant: {
    label: 'Variant name',
    help: 'The value is itself one of the MultiQC variant names. It resolves to that variant only.',
  },
  base: {
    label: 'Shared base ID',
    help: 'The value matches mapping keys once read-pair / lane / replicate suffixes (_R1, _L001, _REP1…) are stripped from the keys. It resolves to every key sharing that base plus their variants.',
  },
  'source-suffix': {
    label: 'Suffix-stripped value',
    help: 'The value matched only after stripping its own read-pair / lane / replicate suffix (_R1, _L001, _REP1…).',
  },
  direct: {
    label: 'Direct',
    help: 'Passed through unchanged and matched against the target field as-is.',
  },
  pattern: {
    label: 'Pattern',
    help: "The value was substituted into the link's pattern template (e.g. {sample}.bam) to build the target name.",
  },
  regex: {
    label: 'Regex',
    help: "The value was used as a regular expression against the target field; it resolves to every target name that matched.",
  },
  wildcard: {
    label: 'Wildcard',
    help: 'The value was glob-matched (* / ?) against the target field; it resolves to every target name that matched.',
  },
  passthrough: {
    label: 'No match',
    help: 'Nothing matched. The value is passed through unchanged, so it only filters the target if that name exists there literally.',
  },
};

/** Every column drag-resizable, sortable and column-menu filterable — the
 *  grid is a debugging surface, so reading long variant lists must not
 *  require leaving it. */
const DEFAULT_COL_DEF: ColDef<LinkMappingPreviewRow> = {
  resizable: true,
  sortable: true,
  filter: true,
};

interface LinkMappingInspectorProps {
  projectId: string;
  linkId: string;
  /** Collapsed-by-default section with a Show/Hide toggle (the edit-modal
   *  layout). When false the grid loads immediately and fills the host —
   *  used by the standalone inspect modal, where the toggle is pure noise. */
  collapsible?: boolean;
}

/**
 * Debug/inspect view for one link's sample ↔ target mapping.
 *
 * Fetches `/links/{project}/{link}/mapping-preview` lazily on expand and
 * renders every distinct source value with its resolution outcome in an AG
 * Grid (quick-filterable, sortable), plus the target-side orphans — so a
 * mismatch is visible from both directions instead of silently matching
 * nothing at render time.
 */
export const LinkMappingInspector: React.FC<LinkMappingInspectorProps> = ({
  projectId,
  linkId,
  collapsible = true,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  const [expanded, setExpanded] = useState(!collapsible);
  const [data, setData] = useState<LinkMappingPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [unmappedOnly, setUnmappedOnly] = useState(false);

  useEffect(() => {
    if (!expanded || data || loading) return;
    setLoading(true);
    setError(null);
    fetchLinkMappingPreview(projectId, linkId)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [expanded, data, loading, projectId, linkId]);

  const rows = useMemo(() => {
    const all = data?.rows ?? [];
    return unmappedOnly ? all.filter((r) => !r.matched) : all;
  }, [data, unmappedOnly]);

  const colDefs = useMemo<ColDef<LinkMappingPreviewRow>[]>(
    () => [
      {
        headerName: 'Source value',
        field: 'source_value',
        flex: 1,
        minWidth: 160,
        tooltipField: 'source_value',
      },
      {
        headerName: 'Status',
        field: 'matched',
        width: 120,
        cellRenderer: (p: ICellRendererParams<LinkMappingPreviewRow>) =>
          p.value ? (
            <Badge size="sm" variant="light" color="teal" style={{ textTransform: 'none' }}>
              matched
            </Badge>
          ) : (
            <Badge size="sm" variant="light" color="orange" style={{ textTransform: 'none' }}>
              unmapped
            </Badge>
          ),
      },
      {
        headerName: 'Matched via',
        field: 'via',
        width: 180,
        valueFormatter: (p) => VIA_LABELS[p.value as string]?.label ?? String(p.value ?? ''),
        cellRenderer: (p: ICellRendererParams<LinkMappingPreviewRow>) => {
          const via = VIA_LABELS[p.value as string];
          if (!via) return String(p.value ?? '');
          return (
            <Tooltip label={via.help} withArrow multiline w={320} openDelay={200}>
              <Text size="sm" style={{ borderBottom: '1px dotted currentColor' }} span>
                {via.label}
              </Text>
            </Tooltip>
          );
        },
      },
      {
        headerName: 'Resolves to',
        field: 'resolved',
        flex: 2,
        minWidth: 220,
        sortable: false,
        // Variant lists routinely run past one line ("S1", "S1 - First
        // read", …); wrapping beats a clipped single line the user can only
        // read by dragging the column wider.
        wrapText: true,
        autoHeight: true,
        cellStyle: { lineHeight: '20px', paddingTop: 6, paddingBottom: 6 },
        valueFormatter: (p) => (Array.isArray(p.value) ? p.value.join(', ') : ''),
        tooltipValueGetter: (p) => (Array.isArray(p.value) ? p.value.join(', ') : ''),
      },
    ],
    [],
  );

  return (
    <Stack gap="xs">
      <Group justify="space-between" wrap="nowrap">
        <Group gap="xs">
          {collapsible && (
            <>
              <Icon icon="mdi:magnify-scan" width={18} color="var(--mantine-color-teal-6)" />
              <Text size="sm" fw={600}>
                Inspect mapping
              </Text>
            </>
          )}
          {data && (
            <>
              <Tooltip label="Source values that resolve through the link" withArrow>
                <Badge size="sm" variant="light" color="teal" style={{ textTransform: 'none' }}>
                  {data.matched_count} matched
                </Badge>
              </Tooltip>
              <Tooltip label="Source values the link cannot map" withArrow>
                <Badge size="sm" variant="light" color="orange" style={{ textTransform: 'none' }}>
                  {data.unmapped_count} unmapped
                </Badge>
              </Tooltip>
              {data.orphan_targets.length > 0 && (
                <Tooltip
                  label="Target-side samples no source value reaches"
                  withArrow
                >
                  <Badge size="sm" variant="light" color="gray" style={{ textTransform: 'none' }}>
                    {data.orphan_targets.length} orphan targets
                  </Badge>
                </Tooltip>
              )}
            </>
          )}
        </Group>
        {collapsible && (
          <Button
            size="compact-xs"
            variant="subtle"
            color="teal"
            onClick={() => setExpanded((v) => !v)}
            rightSection={
              <Icon icon={expanded ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={14} />
            }
            data-testid="mapping-inspector-toggle"
          >
            {expanded ? 'Hide' : 'Show'}
          </Button>
        )}
      </Group>
      <Collapse in={expanded}>
        <Stack gap="xs">
          {loading && (
            <Group gap="xs">
              <Loader size="xs" />
              <Text size="sm" c="dimmed">
                Resolving every source value through the link…
              </Text>
            </Group>
          )}
          {error && (
            <Alert color="orange" variant="light">
              {error}
            </Alert>
          )}
          {data && (
            <>
              <Group gap="xs" wrap="nowrap">
                <TextInput
                  size="xs"
                  flex={1}
                  placeholder="Search values…"
                  leftSection={<Icon icon="mdi:magnify" width={14} />}
                  value={search}
                  onChange={(e) => setSearch(e.currentTarget.value)}
                />
                <Switch
                  size="xs"
                  label="Unmapped only"
                  checked={unmappedOnly}
                  onChange={(e) => setUnmappedOnly(e.currentTarget.checked)}
                />
              </Group>
              <Box
                className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
                style={{ height: collapsible ? 340 : 520, width: '100%' }}
                data-testid="mapping-inspector-grid"
              >
                <AgGridReact<LinkMappingPreviewRow>
                  rowData={rows}
                  columnDefs={colDefs}
                  defaultColDef={DEFAULT_COL_DEF}
                  headerHeight={34}
                  rowHeight={32}
                  quickFilterText={search}
                  tooltipShowDelay={300}
                  pagination
                  paginationPageSize={25}
                  paginationPageSizeSelector={[25, 50, 100]}
                  overlayNoRowsTemplate={
                    '<span style="color:var(--mantine-color-dimmed);font-size:12px">No source values to inspect.</span>'
                  }
                />
              </Box>
              <Text size="xs" c="dimmed">
                {data.source_values_total} distinct source values in{' '}
                <Code>{data.source_column}</Code>
                {data.truncated ? ` — showing the first ${data.rows.length}` : ''}. Mappings:{' '}
                {data.mappings_source === 'multiqc_live'
                  ? 'fetched live from the MultiQC reports'
                  : data.mappings_source === 'link_config'
                    ? 'frozen on the link'
                    : 'none'}
                {data.case_sensitive ? ' · case-sensitive' : ' · case-insensitive'}.
              </Text>
              {data.orphan_targets.length > 0 && (
                <Text size="xs" c="dimmed">
                  Orphan targets:{' '}
                  {data.orphan_targets.slice(0, 12).map((t) => (
                    <Code key={t} mr={4}>
                      {t}
                    </Code>
                  ))}
                  {data.orphan_targets.length > 12
                    ? `… +${data.orphan_targets.length - 12} more`
                    : ''}
                </Text>
              )}
            </>
          )}
        </Stack>
      </Collapse>
    </Stack>
  );
};

interface LinkMappingModalProps {
  opened: boolean;
  projectId: string;
  /** Link to inspect. Null while the modal is closed. */
  link: DCLink | null;
  /** Display tags for the two endpoints, resolved by the caller. */
  sourceTag: string;
  targetTag: string;
  onClose: () => void;
}

/**
 * Standalone "inspect mapping" modal — the magnifier action on a link row.
 * Same inspector as the edit modal's section, but opened directly so reading
 * a link's mapping doesn't mean entering an edit form.
 */
export const LinkMappingModal: React.FC<LinkMappingModalProps> = ({
  opened,
  projectId,
  link,
  sourceTag,
  targetTag,
  onClose,
}) => {
  const accent = useBrandAccents();
  return (
      // Wide on purpose: the grid carries a source value, a status, the match
      // rule and a full variant list per row, and at Mantine's `xl` (780px) the
      // variant list wrapped to six lines a row.
      <Modal opened={opened} onClose={onClose} title={null} size="90%" centered padding="lg">
      <Stack gap="md" data-testid="link-mapping-modal">
        <Group justify="center" gap="sm">
          <Icon icon="mdi:magnify-scan" width={32} color={`var(--mantine-color-${accent.secondary}-6)`} />
          <Title order={3} c={accent.secondary} m={0}>
            Inspect mapping
          </Title>
        </Group>
        {link && (
          <Group gap="xs" justify="center">
            <Code>
              {sourceTag}.{link.source_column}
            </Code>
            <Icon icon="mdi:arrow-right" width={16} />
            <Code>{targetTag}</Code>
            <Badge size="sm" variant="light">
              {link.link_config?.resolver || 'direct'}
            </Badge>
          </Group>
        )}
        {link && (
          <LinkMappingInspector projectId={projectId} linkId={link.id} collapsible={false} />
        )}
      </Stack>
    </Modal>
  );
};
