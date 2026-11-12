/**
 * "N new since your last visit" in the project page's header (#1397): hidden
 * on a first visit and when nothing happened, otherwise a pill that opens what
 * did: new runs, refreshed collections, failed ingestions and dashboards other
 * people changed, with "Mark as seen" to move the reader's mark to now.
 */
import React, { useState } from 'react';
import {
  Anchor,
  Badge,
  Button,
  Divider,
  Group,
  Popover,
  ScrollArea,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DataChange } from 'depictio-react-core';

import { absTime, compactCount } from '../../monitoring/format';
import { NameChip } from '../badges';
import { CHECK_STATUS } from '../checkStatus';
import type { ProjectChanges } from './useProjectChanges';

const Section: React.FC<{ icon: string; title: string; children: React.ReactNode; testId: string }> = ({
  icon,
  title,
  children,
  testId,
}) => (
  <Stack gap={6} data-testid={testId}>
    <Group gap={6} wrap="nowrap">
      <Icon icon={icon} width={14} style={{ opacity: 0.6 }} />
      <Text size="xs" c="dimmed" fw={600} tt="uppercase">
        {title}
      </Text>
    </Group>
    <Stack gap={6}>{children}</Stack>
  </Stack>
);

/** What a refreshed collection gained, in the words a reader looks for. */
export function dataChangeFacts(d: DataChange): string[] {
  if (d.kind === 'emptied') return ['emptied'];
  const facts: string[] = [];
  if (d.rows_added) facts.push(`+${compactCount(d.rows_added)} rows`);
  if (d.new_sample_count) {
    facts.push(`${compactCount(d.new_sample_count)} new sample${d.new_sample_count === 1 ? '' : 's'}`);
  } else if (d.reports_added) {
    facts.push(`${d.reports_added} new report${d.reports_added === 1 ? '' : 's'}`);
  }
  if (d.reports_refreshed) facts.push(`${d.reports_refreshed} report${d.reports_refreshed === 1 ? '' : 's'} refreshed`);
  return facts.length ? facts : ['refreshed'];
}

export const ProjectChangesPill: React.FC<{
  projectId: string;
  changes: ProjectChanges;
  /** Open the Runs tab on one run. */
  onShowRuns?: (run: string) => void;
  /** Open the ingestion history. */
  onShowHistory?: () => void;
}> = ({ projectId, changes, onShowRuns, onShowHistory }) => {
  const [opened, setOpened] = useState(false);
  const [saving, setSaving] = useState(false);
  const cs = changes.changeSet;
  if (!changes.enabled || !cs || changes.count === 0) return null;

  const mark = async () => {
    setSaving(true);
    try {
      await changes.markSeen();
      setOpened(false);
    } catch {
      // The pill stays; the reader can try again.
    } finally {
      setSaving(false);
    }
  };

  return (
    <Popover opened={opened} onChange={setOpened} width={460} position="bottom-end" shadow="md" withArrow>
      <Popover.Target>
        <Badge
          component="button"
          type="button"
          variant="light"
          color="blue"
          radius="sm"
          tt="none"
          fw={600}
          style={{ cursor: 'pointer' }}
          leftSection={<Icon icon="mdi:update" width={14} />}
          onClick={() => setOpened((o) => !o)}
          aria-label={`${changes.count} changes since your last visit`}
          title={cs.since ? `Since ${absTime(cs.since)}` : undefined}
          data-testid="project-changes-pill"
        >
          {changes.count} new since your last visit
        </Badge>
      </Popover.Target>
      <Popover.Dropdown data-testid="project-changes-panel">
        <Stack gap="sm">
          <Group justify="space-between" wrap="nowrap">
            <Text size="sm" fw={600}>
              Changed since {absTime(cs.since)}
            </Text>
            <Button
              size="compact-xs"
              variant="light"
              loading={saving}
              onClick={mark}
              leftSection={<Icon icon="mdi:check-all" width={14} />}
              data-testid="project-changes-mark-seen"
            >
              Mark as seen
            </Button>
          </Group>
          <ScrollArea.Autosize mah={420} type="auto" offsetScrollbars>
            <Stack gap="md">
              {cs.new_runs.length > 0 && (
                <Section icon="mdi:folder-play-outline" title="New runs" testId="project-changes-runs">
                  {cs.new_runs.map((r) => (
                    <Group key={`${r.workflow_id}-${r.run_tag}`} gap={8} wrap="nowrap" justify="space-between">
                      <Anchor
                        component="button"
                        type="button"
                        onClick={() => {
                          setOpened(false);
                          onShowRuns?.(r.run_tag);
                        }}
                        data-testid={`project-changes-run-${r.run_tag}`}
                      >
                        <NameChip size="sm" style={{ cursor: 'pointer' }}>
                          {r.run_tag}
                        </NameChip>
                      </Anchor>
                      {r.registered && (
                        <Text size="xs" c="dimmed">
                          {absTime(r.registered)}
                        </Text>
                      )}
                    </Group>
                  ))}
                </Section>
              )}
              {cs.data.length > 0 && (
                <Section icon="mdi:database-refresh-outline" title="Refreshed collections" testId="project-changes-data">
                  {cs.data.map((d) => (
                    <Group key={d.dc_id} gap={8} wrap="wrap">
                      <Anchor href={`/projects/${projectId}?table=${d.dc_id}`} size="sm" fw={500}>
                        {d.data_collection_tag}
                      </Anchor>
                      <Text size="sm" c={d.kind === 'emptied' ? 'red' : 'dimmed'}>
                        {dataChangeFacts(d).join(' · ')}
                      </Text>
                      {d.new_run_tags.slice(0, 3).map((t) => (
                        <NameChip key={t} size="xs" dimmed>
                          {t}
                        </NameChip>
                      ))}
                      {d.new_run_tags.length > 3 && (
                        <Text size="xs" c="dimmed">
                          +{d.new_run_tags.length - 3}
                        </Text>
                      )}
                    </Group>
                  ))}
                </Section>
              )}
              {cs.failed_ingestions.length > 0 && (
                <Section icon="mdi:alert-circle-outline" title="Failed ingestions" testId="project-changes-failed">
                  {cs.failed_ingestions.map((f) => {
                    const fail = CHECK_STATUS.fail;
                    return (
                      <Group key={f.run_id} gap={8} wrap="wrap">
                        <Icon icon={fail.icon} width={16} color={`var(--mantine-color-${fail.color}-6)`} />
                        <Anchor
                          component="button"
                          type="button"
                          size="sm"
                          onClick={() => {
                            setOpened(false);
                            onShowHistory?.();
                          }}
                        >
                          Ingestion {f.status}
                        </Anchor>
                        {f.run_tags.slice(0, 3).map((t) => (
                          <NameChip key={t} size="xs" dimmed>
                            {t}
                          </NameChip>
                        ))}
                        {f.at && (
                          <Text size="xs" c="dimmed">
                            {absTime(f.at)}
                          </Text>
                        )}
                      </Group>
                    );
                  })}
                </Section>
              )}
              {cs.dashboards.length > 0 && (
                <Section icon="mdi:view-dashboard-outline" title="Dashboards changed" testId="project-changes-dashboards">
                  {cs.dashboards.map((d) => (
                    <Group key={d.family_id} gap={8} wrap="wrap">
                      <Anchor href={`/dashboard/${d.family_id}`} size="sm" fw={500}>
                        {d.title || 'Untitled dashboard'}
                      </Anchor>
                      <Text size="sm" c="dimmed">
                        {d.versions} version{d.versions === 1 ? '' : 's'}
                        {d.authors.length ? ` · by ${d.authors.join(', ')}` : ''}
                      </Text>
                    </Group>
                  ))}
                </Section>
              )}
            </Stack>
          </ScrollArea.Autosize>
          <Divider />
          <Text size="xs" c="dimmed">
            Marking as seen moves your mark to now; nothing is deleted.
          </Text>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
};

export default ProjectChangesPill;
