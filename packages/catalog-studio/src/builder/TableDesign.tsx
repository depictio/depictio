/**
 * Table builder. Replicates depictio's real `TableBuilder` FORM (striped /
 * compact / CSV-export switches + a column-visibility editor writing
 * `cols_json`) — pure Mantine, no backend calls — paired with the client
 * `TablePreviewLocal` (ag-grid) instead of depictio's backend `TablePreview`.
 * The row-selection cross-filter section is intentionally omitted.
 *
 * The catalog `table` render carries only `{ component: table }`, so these
 * display options are authoring-preview only (the ag-grid preview honors them);
 * they are not persisted.
 */
import { useEffect, useMemo } from 'react';
import { Accordion, Alert, Checkbox, ScrollArea, Stack, Switch, Table } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useBuilderStore } from 'depictio-builder/store/useBuilderStore';
import DesignShell from 'depictio-builder/shared/DesignShell';
import type { ParsedFixture } from '../types';
import TablePreviewLocal from './TablePreviewLocal';

type ColCfg = { hide?: boolean; pinned?: 'left' | 'right' | null };

interface TableConfig {
  cols_json?: Record<string, ColCfg>;
  striped?: boolean;
  compact?: boolean;
  export_csv?: boolean;
}

export default function TableDesign({ fixture }: { fixture: ParsedFixture }) {
  const cols = useBuilderStore((s) => s.cols);
  const config = useBuilderStore((s) => s.config) as TableConfig;
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  // Initialize cols_json with all columns visible if not yet populated.
  useEffect(() => {
    if (!config.cols_json && cols.length) {
      const initial: Record<string, ColCfg> = {};
      for (const c of cols) initial[c.name] = { hide: false };
      patchConfig({ cols_json: initial, striped: true, compact: false, export_csv: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cols.length]);

  const colsJson = config.cols_json || {};
  const visibleCount = useMemo(
    () => cols.filter((c) => (colsJson[c.name]?.hide ?? false) !== true).length,
    [cols, colsJson],
  );

  const form = (
    <Stack gap="md">
      <Accordion multiple defaultValue={['display', 'columns']} variant="separated">
        <Accordion.Item value="display">
          <Accordion.Control>Display options</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              <Switch label="Striped rows" checked={config.striped ?? true} onChange={(e) => patchConfig({ striped: e.currentTarget.checked })} />
              <Switch label="Compact rows" checked={config.compact ?? false} onChange={(e) => patchConfig({ compact: e.currentTarget.checked })} />
              <Switch label="CSV export" checked={config.export_csv ?? true} onChange={(e) => patchConfig({ export_csv: e.currentTarget.checked })} />
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="columns">
          <Accordion.Control>
            Columns visibility ({visibleCount}/{cols.length} visible)
          </Accordion.Control>
          <Accordion.Panel>
            <ScrollArea h={280} type="auto" offsetScrollbars>
              <Table withTableBorder withColumnBorders verticalSpacing={4}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={90}>Visible</Table.Th>
                    <Table.Th>Column</Table.Th>
                    <Table.Th>Type</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {cols.map((c) => {
                    const cfg = colsJson[c.name] ?? { hide: false };
                    return (
                      <Table.Tr key={c.name}>
                        <Table.Td>
                          <Checkbox
                            checked={!cfg.hide}
                            onChange={(e) =>
                              patchConfig({ cols_json: { ...colsJson, [c.name]: { ...cfg, hide: !e.currentTarget.checked } } })
                            }
                          />
                        </Table.Td>
                        <Table.Td>{c.name}</Table.Td>
                        <Table.Td>{c.type}</Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      <Alert color="gray" variant="light" icon={<Icon icon="mdi:information-outline" />}>
        Preview only — the catalog entry is a bare <code>{'{ component: table }'}</code>; column
        visibility and display options aren't persisted yet.
      </Alert>
    </Stack>
  );

  return <DesignShell formSlot={form} previewSlot={<TablePreviewLocal fixture={fixture} height={360} respectConfig />} />;
}
