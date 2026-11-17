/**
 * "What's new" in the project page's header actions (#1397): hidden on a first
 * visit and when nothing happened, otherwise a button that opens what did: new
 * runs, refreshed collections, failed ingestions and dashboards other people
 * changed, with "Mark as seen" to move the reader's mark to now. The list is
 * the same feed as the dashboard's (`changes/feed.tsx`).
 */
import React, { useState } from 'react';
import { Button, Divider, Indicator, Popover, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DataChange } from 'depictio-react-core';

import { rowsFact } from '../../changes/describe';
import {
  FEED_KIND,
  FeedHeader,
  FeedItem,
  FeedMarkSeen,
  FeedScroll,
  FeedSection,
  facts,
  nameList,
} from '../../changes/feed';
import { formatRelativeTime } from '../../lib/datetime';
import { compactCount } from '../../monitoring/format';
import type { ProjectChanges } from './useProjectChanges';

/** What a refreshed collection gained, in the words a reader looks for. */
export function dataChangeFacts(d: DataChange): string[] {
  if (d.kind === 'emptied') return ['emptied'];
  const facts: string[] = [];
  const rows = rowsFact(d, compactCount);
  if (rows) facts.push(rows);
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
  /** Match the header's other buttons ("default" on glass pages). */
  variant?: 'default' | 'light';
}> = ({ projectId, changes, onShowRuns, onShowHistory, variant = 'default' }) => {
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
      // The button stays; the reader can try again.
    } finally {
      setSaving(false);
    }
  };
  const go = (fn?: () => void) => () => {
    setOpened(false);
    fn?.();
  };

  return (
    <Popover opened={opened} onChange={setOpened} width={420} position="bottom-end" shadow="md" radius="md">
      <Popover.Target>
        {/* The count rides on the corner like the bell's, not inside the label. */}
        <Indicator label={changes.count} size={16} offset={4}>
          <Button
            variant={variant}
            leftSection={<Icon icon="mdi:update" width={17} />}
            onClick={() => setOpened((o) => !o)}
            aria-label={`${changes.count} changes since your last visit`}
            data-testid="project-changes-pill"
          >
            What&apos;s new
          </Button>
        </Indicator>
      </Popover.Target>
      <Popover.Dropdown p="sm" data-testid="project-changes-panel">
        <Stack gap="xs">
          <FeedHeader
            title="What's new"
            subtitle={cs.since ? `Changed since ${formatRelativeTime(cs.since)}` : undefined}
            action={<FeedMarkSeen loading={saving} onClick={mark} testId="project-changes-mark-seen" />}
          />
          <FeedScroll mah={440}>
            <Stack gap="sm">
              {cs.new_runs.length > 0 && (
                <FeedSection title="New runs" icon={FEED_KIND.run.icon} count={cs.new_runs.length} testId="project-changes-runs">
                  {/* Newest first, like the dashboard's What's new. */}
                  {[...cs.new_runs]
                    .sort((a, b) => String(b.registered ?? '').localeCompare(String(a.registered ?? '')))
                    .map((r) => (
                    <FeedItem
                      key={`${r.workflow_id}-${r.run_tag}`}
                      kind="run"
                      title={r.run_tag}
                      summary="New run folder"
                      at={r.registered}
                      onClick={go(() => onShowRuns?.(r.run_tag))}
                      data-testid={`project-changes-run-${r.run_tag}`}
                    />
                  ))}
                </FeedSection>
              )}
              {cs.data.length > 0 && (
                <FeedSection title="Refreshed collections" icon={FEED_KIND.data.icon} count={cs.data.length} testId="project-changes-data">
                  {cs.data.map((d) => (
                    <FeedItem
                      key={d.dc_id}
                      kind={d.kind === 'emptied' ? 'emptied' : 'data'}
                      title={d.data_collection_tag}
                      summary={facts(
                        ...dataChangeFacts(d),
                        d.new_run_tags.length ? `from ${nameList(d.new_run_tags)}` : null,
                      )}
                      by={d.by}
                      at={d.at}
                      href={`/projects/${projectId}?table=${d.dc_id}`}
                    />
                  ))}
                </FeedSection>
              )}
              {cs.failed_ingestions.length > 0 && (
                <FeedSection title="Failed ingestions" icon={FEED_KIND.failed.icon} count={cs.failed_ingestions.length} testId="project-changes-failed">
                  {cs.failed_ingestions.map((f) => (
                    <FeedItem
                      key={f.run_id}
                      kind="failed"
                      title={`Ingestion ${f.status}`}
                      summary={facts(
                        f.data_collection_tags.length ? nameList(f.data_collection_tags) : null,
                        f.run_tags.length ? `run ${nameList(f.run_tags)}` : null,
                      )}
                      at={f.at}
                      onClick={go(onShowHistory)}
                    />
                  ))}
                </FeedSection>
              )}
              {cs.dashboards.length > 0 && (
                <FeedSection title="Dashboards changed" icon={FEED_KIND.dashboard.icon} count={cs.dashboards.length} testId="project-changes-dashboards">
                  {cs.dashboards.map((d) => (
                    <FeedItem
                      key={d.family_id}
                      kind="dashboard"
                      title={d.title || 'Untitled dashboard'}
                      summary={`${d.versions} new version${d.versions === 1 ? '' : 's'}`}
                      by={d.authors}
                      href={`/dashboard/${d.family_id}`}
                    />
                  ))}
                </FeedSection>
              )}
            </Stack>
          </FeedScroll>
          <Divider />
          <Text size="xs" c="dimmed" px={4}>
            Marking as seen moves your mark to now; nothing is deleted.
          </Text>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
};

export default ProjectChangesPill;
