import React from 'react';
import { Alert, Button, Group, SegmentedControl, Select, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { TableMergeMode, TableMergeReport } from 'depictio-react-core';

const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? '' : 's'}`;

/** What applying would do, in one sentence for the chosen mode. */
function summary(report: TableMergeReport, fileName: string): string {
  const matched = `matched on ${report.key} (${report.matched_rows} of ${report.table_rows} rows)`;
  if (report.mode === 'replace') {
    return `The ${plural(report.table_rows, 'row')} of this table become the ${plural(report.file_rows, 'row')} of ${fileName}.`;
  }
  if (report.mode === 'fill_missing') {
    return `${plural(report.filled_cells, 'empty cell')} filled from ${fileName}, ${matched}.`;
  }
  return `${plural(report.new_columns.length, 'column')} added from ${fileName}, ${matched}: ${report.new_columns.join(', ')}.`;
}

/** Notes on what the file leaves out or overrides, shown under the summary. */
function notes(report: TableMergeReport): string[] {
  const lines: string[] = [];
  if (report.mode === 'fill_missing' && report.conflicts > 0) {
    lines.push(`${plural(report.conflicts, 'value')} differ from the file; the table's are kept.`);
  }
  if (report.mode === 'add_columns' && report.ignored_columns.length > 0) {
    lines.push(`Already in the table, left as they are: ${report.ignored_columns.join(', ')}.`);
  }
  if (report.mode !== 'replace' && report.unmatched_file_rows > 0) {
    lines.push(
      `${plural(report.unmatched_file_rows, 'row')} of the file match no row of the table and are left out, e.g. ${report.unmatched_file_sample.join(', ')}.`,
    );
  }
  return lines;
}

/**
 * The choices for a file dropped on a table, above a grid showing the result.
 * Nothing is written before Apply.
 */
const TableMergePanel: React.FC<{
  report: TableMergeReport;
  fileName: string;
  busy: boolean;
  applying: boolean;
  onMode: (mode: TableMergeMode) => void;
  onKey: (key: string) => void;
  onApply: () => void;
  onCancel: () => void;
}> = ({ report, fileName, busy, applying, onMode, onKey, onApply, onCancel }) => {
  const removed = report.mode === 'replace' ? report.removed_columns : [];
  return (
    <Stack gap="xs" data-testid="table-merge-panel">
      <Group justify="space-between" gap="sm" wrap="wrap">
        <Group gap="sm" wrap="wrap">
          <SegmentedControl
            size="xs"
            value={report.mode}
            onChange={(value) => onMode(value as TableMergeMode)}
            disabled={busy || applying}
            data={[
              { value: 'add_columns', label: 'Add columns' },
              { value: 'fill_missing', label: 'Fill missing' },
              { value: 'replace', label: 'Replace' },
            ]}
            data-testid="table-merge-mode"
          />
          {report.mode !== 'replace' && report.key_candidates.length > 0 && (
            <Select
              size="xs"
              w={240}
              aria-label="Column that links the file to the table"
              value={report.key}
              allowDeselect={false}
              disabled={busy || applying}
              onChange={(value) => value && onKey(value)}
              data={report.key_candidates.map((c) => ({
                value: c.column,
                label: `Match on ${c.column} (${c.matched_rows} rows)`,
              }))}
              data-testid="table-merge-key"
            />
          )}
        </Group>
        <Group gap="xs">
          <Button
            size="xs"
            variant="subtle"
            onClick={onCancel}
            disabled={applying}
            data-testid="table-merge-cancel"
          >
            Cancel
          </Button>
          <Button
            size="xs"
            onClick={onApply}
            loading={applying}
            disabled={busy || !report.can_apply}
            leftSection={<Icon icon="mdi:check" width={16} />}
            data-testid="table-merge-apply"
          >
            Apply
          </Button>
        </Group>
      </Group>

      <Text size="sm" data-testid="table-merge-summary">
        {report.can_apply ? summary(report, fileName) : report.reason}
      </Text>
      {report.can_apply &&
        notes(report).map((line) => (
          <Text key={line} size="xs" c="dimmed">
            {line}
          </Text>
        ))}

      {removed.length > 0 && (
        <Alert color="orange" variant="light" py={6}>
          <Text size="sm">
            Not in the file, so removed: {removed.join(', ')}. Dashboards using these columns will
            stop working.
          </Text>
        </Alert>
      )}
      {report.warnings.length > 0 && (
        <Alert color="yellow" variant="light" py={6}>
          <Text size="sm">Values that do not fit their column were skipped:</Text>
          {report.warnings.map((warning) => (
            <Text key={warning} size="xs">
              {warning}
            </Text>
          ))}
        </Alert>
      )}
    </Stack>
  );
};

export default TableMergePanel;
