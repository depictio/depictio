/**
 * The Versions part's demo: the history of one component, drawn like the
 * editor's History, and the bar a preview puts above it. The component is one
 * of the dashboard's own figures (its title), the versions are made up.
 *
 * Nothing is read or written: the rows are fixed, Preview shows the bar and
 * Restore says what it would have asked. The kind icons are the real list's
 * (`kindMeta`).
 */
import React, { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Group,
  Paper,
  Skeleton,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { ComponentRenderer } from 'depictio-react-core';

import ComponentVersionModal from '../../versions/ComponentVersionModal';
import { kindMeta } from '../../versions/format';
import { useVersionHistory } from '../../versions/useVersionHistory';
import { GuideSandbox } from '../GuideSandbox';
import { pickedSource, useFamilyPick } from '../useGuideSources';
import type { GuideFamily } from '../useGuideSources';

const NO_FILTERS: never[] = [];

/** Any figure will do: the demo only borrows its name. */
const anyFigureRank = (m: { component_type?: unknown }) => (m.component_type === 'figure' ? 0 : null);

interface Row {
  seq: number;
  kind: string;
  when: string;
  label?: string;
  pinned?: boolean;
}

const ROWS: Row[] = [
  { seq: 4, kind: 'auto', when: '2 hours ago' },
  { seq: 3, kind: 'explicit', when: 'yesterday', label: 'Before the new filters', pinned: true },
  { seq: 2, kind: 'auto', when: '3 days ago' },
  { seq: 1, kind: 'import', when: 'last week' },
];

/** The made-up list, for a dashboard that has no saved version to look at. */
const IllustrativeHistory: React.FC<{ title: string }> = ({ title }) => {
  const [previewing, setPreviewing] = useState<Row | null>(null);
  const [asked, setAsked] = useState<Row | null>(null);

  return (
    <Stack gap="xs" data-testid="guide-versions-demo">
      {previewing && (
        <Paper withBorder radius="md" p="xs" className="depictio-guide-note" aria-live="polite">
          <Group justify="space-between" wrap="wrap" gap="xs">
            <Group gap="xs" wrap="nowrap">
              <Icon icon="mdi:history" width={16} style={{ flexShrink: 0 }} />
              <Text size="sm">
                <Text span inherit fw={600}>
                  Viewing {title} as of {previewing.label ?? `v${previewing.seq}`}
                </Text>{' '}
                · saved {previewing.when}
              </Text>
            </Group>
            <Button size="compact-xs" variant="default" onClick={() => setPreviewing(null)}>
              Back to the current version
            </Button>
          </Group>
        </Paper>
      )}
      <Group gap={6} wrap="nowrap">
        <Icon icon="mdi:history" width={16} style={{ flexShrink: 0 }} />
        <Text size="sm" fw={600} truncate>
          History of {title}
        </Text>
      </Group>
      <Box
        role="list"
        style={{
          border: '1px solid var(--mantine-color-default-border)',
          borderRadius: 'var(--mantine-radius-md)',
          background: 'var(--mantine-color-body)',
        }}
      >
        {ROWS.map((row, i) => {
          const meta = kindMeta(row.kind);
          const current = i === 0;
          return (
            <Group
              key={row.seq}
              role="listitem"
              gap="xs"
              wrap="nowrap"
              px="xs"
              py={6}
              style={
                i > 0 ? { borderTop: '1px solid var(--mantine-color-default-border)' } : undefined
              }
              aria-current={current ? 'true' : undefined}
            >
              <ThemeIcon
                variant="light"
                color={row.pinned ? 'yellow' : meta.color}
                size={22}
                radius="xl"
                role="img"
                aria-label={row.pinned ? 'Bookmarked' : meta.label}
              >
                <Icon icon={row.pinned ? 'mdi:bookmark' : meta.icon} width={12} aria-hidden />
              </ThemeIcon>
              <Group gap={6} wrap="wrap" style={{ flex: 1, minWidth: 0, rowGap: 2 }}>
                <Text size="sm" fw={row.label ? 600 : 500} truncate>
                  {row.label ?? `v${row.seq}`}
                </Text>
                {current && (
                  <Badge size="xs" variant="filled" color="teal">
                    Current
                  </Badge>
                )}
                {row.pinned && (
                  <Badge size="xs" variant="light" color="yellow">
                    Bookmarked
                  </Badge>
                )}
              </Group>
              <Text size="xs" c="dimmed" style={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
                {row.when}
              </Text>
              <Group gap={2} wrap="nowrap" style={{ flexShrink: 0 }}>
                <Tooltip label="Preview, read only" withArrow>
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    size="md"
                    aria-label={`Preview ${row.label ?? `v${row.seq}`}`}
                    data-guide-version-preview
                    onClick={() => {
                      setAsked(null);
                      setPreviewing(current ? null : row);
                    }}
                  >
                    <Icon icon="mdi:eye-outline" width={16} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label={current ? 'This is the current state' : 'Restore'} withArrow>
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    size="md"
                    aria-label={`Restore ${row.label ?? `v${row.seq}`}`}
                    aria-disabled={current || undefined}
                    data-disabled={current || undefined}
                    onClick={() => !current && setAsked(row)}
                  >
                    <Icon icon="mdi:backup-restore" width={16} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            </Group>
          );
        })}
      </Box>
      {asked && (
        <Text size="xs" c="dimmed" aria-live="polite">
          Restoring {asked.label ?? `v${asked.seq}`} would ask you to confirm first, then bring back
          this component alone and add a Restored entry to the list. From the Guide, nothing is changed.
        </Text>
      )}
    </Stack>
  );
};

/**
 * The real thing where there is something to look at: one of the dashboard's
 * own components and its history, the same modal the editor's tile menu opens
 * (`ComponentVersionModal`), read only. Listing and previewing versions needs
 * no more than viewing the dashboard; only Restore writes, and it is off here.
 * A dashboard with no saved version yet gets the made-up list instead.
 */
export const VersionsDemo: React.FC<{ family: GuideFamily }> = ({ family }) => {
  const source = pickedSource(family, useFamilyPick(family, anyFigureRank));
  const history = useVersionHistory(family.currentId, true);
  const [opened, setOpened] = useState(false);
  const title = String(source?.metadata?.title ?? '') || 'This figure';

  if (source === undefined || (history.loading && history.versions.length === 0)) {
    return <Skeleton h={200} radius="md" />;
  }
  if (!source || history.versions.length === 0) return <IllustrativeHistory title={title} />;

  const count = history.total || history.versions.length;
  return (
    <Stack gap="xs" data-testid="guide-versions-demo">
      <Box className="depictio-guide-demo-tile" h={280} style={{ maxWidth: 560 }}>
        <div className="depictio-guide-demo-cell">
          <GuideSandbox metadata={[source.metadata]}>
            <ComponentRenderer
              metadata={source.metadata}
              dashboardId={source.dashboardId}
              filters={NO_FILTERS}
            />
          </GuideSandbox>
        </div>
      </Box>
      <Group gap="sm" wrap="wrap">
        <Button
          size="compact-sm"
          variant="light"
          leftSection={<Icon icon="mdi:history" width={14} />}
          onClick={() => setOpened(true)}
          data-guide-version-preview
        >
          History of this figure
        </Button>
        <Text size="xs" c="dimmed">
          {count === 1 ? '1 saved version' : `${count} saved versions`} of this dashboard. Open the
          history, pick an older version and switch Compare on to see it beside the current one.
          Nothing can be restored from the Guide.
        </Text>
      </Group>
      <ComponentVersionModal
        opened={opened}
        onClose={() => setOpened(false)}
        metadata={source.metadata}
        dashboardId={source.dashboardId}
        versions={history.versions}
        loadingVersions={history.loading}
        canRestore={false}
      />
    </Stack>
  );
};
