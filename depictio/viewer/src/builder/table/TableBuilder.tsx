/**
 * Table builder. Mirrors design_table() in
 * depictio/dash/modules/table_component/frontend.py — the Dash version has no
 * form fields and renders the table directly. Here we expose only minimal
 * display options plus an optional column-visibility editor, both tucked into
 * collapsible sections so the live preview is the focal point.
 *
 * cols_json shape mirrors AG Grid column configs validated by
 * depictio/models/validation/ag_grid.py.
 */
import React, { useEffect, useMemo } from 'react';
import {
  Accordion,
  Checkbox,
  ScrollArea,
  Stack,
  Switch,
  Table,
} from '@mantine/core';
import { useBuilderStore } from '../store/useBuilderStore';
import CrossFilterSection from '../shared/CrossFilterSection';
import DesignShell from '../shared/DesignShell';
import TablePreview from './TablePreview';

type ColCfg = { hide?: boolean; pinned?: 'left' | 'right' | null };

const TableBuilder: React.FC = () => {
  const cols = useBuilderStore((s) => s.cols);
  const config = useBuilderStore((s) => s.config) as {
    cols_json?: Record<string, ColCfg>;
    striped?: boolean;
    compact?: boolean;
    export_csv?: boolean;
    row_selection_enabled?: boolean;
    row_selection_column?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  // Initialize cols_json with all visible by default if not yet populated.
  useEffect(() => {
    if (!config.cols_json && cols.length) {
      const initial: Record<string, ColCfg> = {};
      for (const c of cols) initial[c.name] = { hide: false };
      patchConfig({
        cols_json: initial,
        striped: true,
        compact: false,
        export_csv: true,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cols.length]);

  const colsJson = config.cols_json || {};
  const visibleCount = useMemo(
    () =>
      cols.filter((c) => (colsJson[c.name]?.hide ?? false) !== true).length,
    [cols, colsJson],
  );

  const form = (
    <Stack gap="md">
      <Accordion multiple defaultValue={['display']} variant="separated">
        <Accordion.Item value="display">
          <Accordion.Control>Display options</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              <Switch
                label="Striped rows"
                checked={config.striped ?? true}
                onChange={(e) =>
                  patchConfig({ striped: e.currentTarget.checked })
                }
              />
              <Switch
                label="Compact rows"
                checked={config.compact ?? false}
                onChange={(e) =>
                  patchConfig({ compact: e.currentTarget.checked })
                }
              />
              <Switch
                label="CSV export"
                checked={config.export_csv ?? true}
                onChange={(e) =>
                  patchConfig({ export_csv: e.currentTarget.checked })
                }
              />
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>

        <CrossFilterSection
          enabled={Boolean(config.row_selection_enabled)}
          onEnabledChange={(checked) =>
            patchConfig({ row_selection_enabled: checked })
          }
          column={config.row_selection_column}
          onColumnChange={(name) =>
            patchConfig({ row_selection_column: name })
          }
          columnLabel="Row column"
          columnDescription="Column to extract from selected rows"
        />

        <Accordion.Item value="columns">
          <Accordion.Control>
            Columns visibility ({visibleCount}/{cols.length} visible)
          </Accordion.Control>
          <Accordion.Panel>
            <ScrollArea h={320} type="auto" offsetScrollbars>
              <Table withTableBorder withColumnBorders verticalSpacing={4}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={120}>Visible</Table.Th>
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
                            onChange={(e) => {
                              const next = {
                                ...colsJson,
                                [c.name]: {
                                  ...cfg,
                                  hide: !e.currentTarget.checked,
                                },
                              };
                              patchConfig({ cols_json: next });
                            }}
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
    </Stack>
  );

  return <DesignShell formSlot={form} previewSlot={<TablePreview />} />;
};

export default TableBuilder;
