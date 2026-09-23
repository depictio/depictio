import React, { useEffect, useMemo, useState } from 'react';
import {
  Anchor,
  Badge,
  Card,
  Group,
  NumberInput,
  ScrollArea,
  Select,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';

import {
  AdvancedVizKind,
  fetchAdvancedVizData,
  fetchSpecs,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { formatFieldValue, NULL_DISPLAY, recordLinks } from './record_card/recordFields';
import { buildRecordSections } from './record_card/recordSections';
import { distinguishingColumns, rowLabel } from './record_card/recordRows';
import { readRecordSelection, type RecordSelectionSource } from './record_card/recordSelection';
import {
  defaultRecordFilter,
  recordEcho,
  resolveRecordTarget,
  targetMatch,
} from './record_card/recordDefault';
import { usePersistedVizControl } from './usePersistedVizControl';
import { demandForPx } from './contentDemand';

/** One `label / value` line inside a card, at `size="xs"` with `gap={2}`. */
const FIELD_LINE_PX = 20;
/** One section heading above its fields. */
const SECTION_TITLE_PX = 20;
/** A card's heading block (title plus the id line under it) and its padding. */
const CARD_HEADING_PX = 66;
/** `Stack gap="xs"` between two cards. */
const CARD_GAP_PX = 10;

/** Mirrors `RecordCardConfig` in
 *  depictio/models/components/advanced_viz/configs.py. Every key read here has
 *  a field there, and `test_advanced_viz_config_alignment` enforces it. */
interface RecordCardConfig {
  id_col: string;
  title_col?: string | null;
  sections?: Record<string, string[]> | null;
  link_templates?: Record<string, string> | null;
  selection_source?: RecordSelectionSource;
  max_fields?: number;
  default_record?: string | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: RecordCardConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const RECORD_CARD_VIZ_KIND: AdvancedVizKind = 'record_card';

/** The empty state, worded as an instruction because that is what it is: the
 *  card is inert until another tile says which record it is about. */
const NO_SELECTION_MESSAGE = 'Select a row in a linked tile';

/** Height of the row picker shown when one record spans several rows. */
const ROW_PICKER_PX = 56;

/** Rows fetched at most. A selection normally narrows the frame to a few rows
 *  server-side, but a pick that reaches this collection through a link the
 *  project does not declare narrows nothing, and the card must not pull a
 *  whole collection across to show five of its rows. */
const MAX_FETCHED_ROWS = 200;

/** One column of the bound collection, as `/deltatables/specs` describes it. */
interface ColumnSpec {
  name?: string;
  type?: string;
  description?: string | null;
}

const unique = (values: (string | null | undefined)[]): string[] =>
  Array.from(new Set(values.filter((v): v is string => Boolean(v))));

/**
 * One row of a collection, read as labelled fields rather than as a mark.
 *
 * The detail half of a master/detail dashboard: a scatter, a table or a genome
 * view emits a selection and this tile shows the record behind the picked
 * point. The columns a reader wants once they have chosen a sample (run
 * identifiers, QC verdicts, a link out to the report) are text, and a chart of
 * one row is a worse way to read them.
 *
 * It emits no filter of its own, ever. A detail panel that narrowed the
 * dashboard would narrow the very tile the reader picks from, and the pick
 * could never be widened again.
 */
const RecordCardRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const config = (metadata.config || {}) as RecordCardConfig;
  const idCol = config.id_col || 'id';
  const titleCol = config.title_col || null;

  const [maxFields, setMaxFields] = usePersistedVizControl<number>(metadata, 'max_fields', 40);

  // What the reader picked elsewhere. Everything below is downstream of it:
  // with no selection and no `default_record` the card never fetches, so an
  // unpicked dashboard pays nothing for having the tile on it.
  const selection = useMemo(
    () =>
      readRecordSelection(filters, {
        dcId: metadata.dc_id,
        selectionSource: config.selection_source,
      }),
    [filters, metadata.dc_id, config.selection_source],
  );

  // The selection when there is one, else the configured default record. A
  // real pick always wins; clearing it brings the default back.
  const target = useMemo(
    () => resolveRecordTarget(selection, { idCol, defaultRecord: config.default_record }),
    [selection, idCol, config.default_record],
  );
  const match = useMemo(() => targetMatch(target), [target]);
  const defaultValue = target?.kind === 'default' ? target.value : null;

  // The collection's own columns and their descriptions, which is what lets an
  // unconfigured card show every field and group them with no per-dashboard
  // layout. Precomputed at ingest, so this is a lookup rather than a scan.
  const [columnSpecs, setColumnSpecs] = useState<ColumnSpec[]>([]);
  useEffect(() => {
    if (!metadata.dc_id) return;
    let cancelled = false;
    fetchSpecs(metadata.dc_id)
      .then((specs) => {
        if (!cancelled) setColumnSpecs(Array.isArray(specs) ? (specs as ColumnSpec[]) : []);
      })
      // A collection with no aggregation yet has no specs. The card still
      // works from the columns its config names, so this is not an error.
      .catch(() => {
        if (!cancelled) setColumnSpecs([]);
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id]);

  const descriptions = useMemo(() => {
    const out: Record<string, string> = {};
    for (const spec of columnSpecs) {
      if (spec.name && spec.description) out[spec.name] = spec.description;
    }
    return out;
  }, [columnSpecs]);

  const linkColumns = useMemo(
    () => Object.keys(config.link_templates ?? {}),
    [config.link_templates],
  );

  const fieldColumns = useMemo(() => {
    if (config.sections) return unique(Object.values(config.sections).flat());
    return unique(columnSpecs.map((spec) => spec.name));
  }, [config.sections, columnSpecs]);

  const requiredCols = useMemo(
    () =>
      unique([
        idCol,
        titleCol,
        // Only when the pick names rows of this collection: the value match
        // below needs the column, and a linked pick has none to match on.
        match?.ownCollection ? match.column : null,
        ...linkColumns,
        ...fieldColumns,
      ]),
    [idCol, titleCol, match, linkColumns, fieldColumns],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const hasSelection = Boolean(selection);
  const hasTarget = Boolean(target);
  useEffect(() => {
    if (!hasTarget) {
      setRows(null);
      setLoading(false);
      setError(null);
      return;
    }
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Record card: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns: requiredCols,
      // Passed through untouched: the card emits nothing, so there is no own
      // selection to strip, and the pick it follows IS one of these filters.
      // The default record adds an equality filter on the id column, sent with
      // this fetch only.
      filters:
        defaultValue != null
          ? [
              ...filters,
              defaultRecordFilter(metadata.index, metadata.dc_id, idCol, defaultValue),
            ]
          : filters,
      limitRows: MAX_FETCHED_ROWS,
      vizKind: RECORD_CARD_VIZ_KIND,
      roles: { id: idCol },
    })
      .then((res) => {
        if (!cancelled) setRows(res.rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    metadata.wf_id,
    metadata.dc_id,
    idCol,
    JSON.stringify(requiredCols),
    JSON.stringify(filters),
    hasTarget,
    defaultValue,
    refreshTick,
  ]);

  // Rows as records, narrowed once more against the picked values when the
  // pick names a column of this collection. The server has normally applied
  // that filter already; it drops one it cannot resolve against this schema,
  // and showing row 0 of an unfiltered frame would read as the record the
  // reader picked.
  const records = useMemo(() => {
    if (!rows) return null;
    const columns = Object.keys(rows);
    const length = columns.reduce((n, col) => Math.max(n, (rows[col] ?? []).length), 0);
    const pickedColumn =
      match?.ownCollection && match.column && columns.includes(match.column)
        ? match.column
        : null;
    const picked = pickedColumn ? new Set(match?.values ?? []) : null;
    const out: Record<string, unknown>[] = [];
    for (let i = 0; i < length; i += 1) {
      const row: Record<string, unknown> = {};
      for (const col of columns) row[col] = (rows[col] ?? [])[i] ?? null;
      if (picked && pickedColumn && !picked.has(String(row[pickedColumn] ?? ''))) continue;
      out.push(row);
    }
    return out;
  }, [rows, match]);

  const layout = useMemo(
    () =>
      buildRecordSections({
        columns: fieldColumns.length ? fieldColumns : requiredCols,
        sections: config.sections,
        descriptions,
        headingColumns: unique([idCol, titleCol]),
        maxFields,
      }),
    [fieldColumns, requiredCols, config.sections, descriptions, idCol, titleCol, maxFields],
  );

  // One card at a time. A record that spans several rows (a gene at every
  // clustering resolution) gets a picker over the columns that tell its rows
  // apart; the pick is reader state, so it starts over with each new record.
  const rowCount = records?.length ?? 0;
  const [rowIndex, setRowIndex] = useState(0);
  const recordKey = `${match?.column ?? ''}:${(match?.values ?? []).join('|')}`;
  useEffect(() => {
    setRowIndex(0);
  }, [recordKey]);
  const labelColumns = useMemo(
    () =>
      records
        ? distinguishingColumns(
            records,
            layout.sections.flatMap((section) => section.columns),
          )
        : [],
    [records, layout.sections],
  );
  const rowOptions = useMemo(
    () =>
      (records ?? []).map((row, i) => ({
        value: String(i),
        label: rowLabel(row, labelColumns, i),
      })),
    [records, labelColumns],
  );
  const current = records?.[Math.min(rowIndex, Math.max(rowCount - 1, 0))] ?? null;
  const shown = current ? [current] : [];

  // Fields and section headings are the card's height. Nothing here is a plot
  // that stretches: a card that does not fit scrolls inside the tile, which is
  // the thing the demand exists to avoid.
  const sectionCount = layout.sections.length;
  const fieldCount = layout.sections.reduce((n, section) => n + section.columns.length, 0);
  const contentDemand = useMemo(
    () =>
      shown.length
        ? demandForPx(
            (rowCount > 1 ? ROW_PICKER_PX : 0) +
              CARD_HEADING_PX +
              sectionCount * SECTION_TITLE_PX +
              fieldCount * FIELD_LINE_PX +
              CARD_GAP_PX,
          )
        : undefined,
    [shown.length, rowCount, sectionCount, fieldCount],
  );
  const echo = recordEcho(target, records ? records.length : null);

  const emptyMessage = !hasTarget
    ? NO_SELECTION_MESSAGE
    : records && records.length === 0
      ? hasSelection
        ? 'The selected record is not in this collection'
        : `Default record ${defaultValue} is not in this collection`
      : undefined;

  // A card has no encoding tier: the record is whatever the linked tile
  // selected. One compact control, so it reads the same in the popover and in
  // the header strip the frame promotes it into.
  const controls = (
    <NumberInput
      size="xs"
      w={150}
      label="Fields per card"
      value={maxFields}
      onChange={(v) => setMaxFields(Math.max(1, Number(v) || 40))}
      min={1}
      max={200}
    />
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Record'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      echo={echo}
      controls={controls}
      contentDemand={contentDemand}
      loading={loading}
      error={error}
      emptyMessage={emptyMessage}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      <ScrollArea h="100%" type="auto" offsetScrollbars>
        <Stack gap="xs">
          {rowCount > 1 ? (
            <Select
              size="xs"
              label={`${rowCount} rows for this record${
                labelColumns.length ? `, by ${labelColumns.join(' / ')}` : ''
              }`}
              value={String(Math.min(rowIndex, rowCount - 1))}
              onChange={(v) => setRowIndex(v == null ? 0 : Number(v))}
              data={rowOptions}
              allowDeselect={false}
              searchable={rowCount > 8}
              comboboxProps={{ withinPortal: true }}
            />
          ) : null}
          {shown.map((row, i) => {
            const links = recordLinks(row, config.link_templates);
            const heading = formatFieldValue(titleCol ? row[titleCol] : row[idCol]);
            return (
              <Card key={`${String(row[idCol] ?? i)}-${i}`} withBorder padding="xs" radius="sm">
                <Stack gap={6}>
                  <div>
                    <Text fw={600} size="sm" lineClamp={2}>
                      {heading}
                    </Text>
                    {titleCol ? (
                      <Text size="xs" c="dimmed" lineClamp={1}>
                        {`${idCol}: ${formatFieldValue(row[idCol])}`}
                      </Text>
                    ) : null}
                  </div>

                  {links.length ? (
                    <Group gap={6}>
                      {links.map((link) => (
                        <Tooltip key={link.column} label={link.value} withArrow>
                          <Badge
                            variant="light"
                            size="sm"
                            radius="sm"
                            style={{ textTransform: 'none' }}
                          >
                            <Anchor
                              href={link.href}
                              target="_blank"
                              rel="noreferrer noopener"
                              size="xs"
                              underline="never"
                              c="inherit"
                            >
                              {link.column}
                            </Anchor>
                          </Badge>
                        </Tooltip>
                      ))}
                    </Group>
                  ) : null}

                  {layout.sections.map((section) => (
                    <Stack key={section.title} gap={2}>
                      <Text size="xs" fw={500} c="dimmed" tt="uppercase">
                        {section.title}
                      </Text>
                      {section.columns.map((column) => {
                        const value = formatFieldValue(row[column]);
                        return (
                          <Group
                            key={column}
                            gap={8}
                            justify="space-between"
                            align="flex-start"
                            wrap="nowrap"
                          >
                            <Tooltip
                              label={descriptions[column] || column}
                              withArrow
                              multiline
                              w={240}
                            >
                              <Text size="xs" c="dimmed" lineClamp={1}>
                                {column}
                              </Text>
                            </Tooltip>
                            <Text
                              size="xs"
                              fw={500}
                              ta="right"
                              // A missing value is dimmed, so a card of real
                              // values does not read as a card of dashes.
                              c={value === NULL_DISPLAY ? 'dimmed' : undefined}
                              style={{ wordBreak: 'break-word' }}
                            >
                              {value}
                            </Text>
                          </Group>
                        );
                      })}
                    </Stack>
                  ))}

                  {layout.truncated > 0 ? (
                    <Text size="xs" c="dimmed">
                      {`${layout.truncated} more field(s) not shown`}
                    </Text>
                  ) : null}
                </Stack>
              </Card>
            );
          })}

        </Stack>
      </ScrollArea>
    </AdvancedVizFrame>
  );
};

export default RecordCardRenderer;
