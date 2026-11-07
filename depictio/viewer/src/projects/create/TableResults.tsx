/**
 * The last step of the data flows: one row per table being created and what
 * became of it. The project exists as soon as this step shows, so it always
 * offers a way into it, whatever failed.
 */
import React from 'react';
import { Alert, Button, Group, Loader, Paper, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

export interface TableResultRow {
  key: string;
  label: string;
  status: 'pending' | 'created' | 'failed';
  error?: string | null;
}

interface TableResultsProps {
  projectName: string;
  rows: TableResultRow[];
  /** A failure that stopped the whole step (the project could not be created,
   *  or the folder could not be read). */
  error: string | null;
  /** The project exists: open it. Null while it is not known yet. */
  onOpen: (() => void) | null;
  working: boolean;
}

export const TableResults: React.FC<TableResultsProps> = ({
  projectName,
  rows,
  error,
  onOpen,
  working,
}) => {
  const failed = rows.filter((r) => r.status === 'failed').length;
  return (
    <Stack gap="md" pt="md" data-testid="create-results">
      <Paper withBorder radius="md" p="md">
        <Stack gap="xs">
          <Text fw={600}>
            {working
              ? `Creating "${projectName}"...`
              : failed > 0 || error
                ? `"${projectName}" was created with problems`
                : `"${projectName}" is ready`}
          </Text>
          {rows.map((row) => (
            <Group
              key={row.key}
              gap="xs"
              wrap="nowrap"
              align="flex-start"
              data-testid={`create-result-${row.key}`}
              data-status={row.status}
            >
              {row.status === 'pending' ? (
                <Loader size={14} mt={3} />
              ) : (
                <ThemeIcon
                  variant="light"
                  size="sm"
                  radius="xl"
                  color={row.status === 'created' ? 'green' : 'red'}
                >
                  <Icon
                    icon={row.status === 'created' ? 'mdi:check' : 'mdi:alert-circle'}
                    width={12}
                  />
                </ThemeIcon>
              )}
              <Stack gap={0} style={{ minWidth: 0 }}>
                <Text size="sm" ff="monospace" style={{ wordBreak: 'break-all' }}>
                  {row.label}
                </Text>
                {row.error && (
                  <Text size="xs" c="red">
                    {row.error}
                  </Text>
                )}
              </Stack>
            </Group>
          ))}
        </Stack>
      </Paper>
      {error && (
        <Alert
          color="red"
          variant="light"
          icon={<Icon icon="mdi:alert-circle-outline" width={16} />}
          data-testid="create-results-error"
        >
          {error}
        </Alert>
      )}
      {!working && onOpen && (
        <Group justify="flex-end">
          <Button onClick={onOpen} data-testid="create-results-open-project">
            Open project
          </Button>
        </Group>
      )}
    </Stack>
  );
};
