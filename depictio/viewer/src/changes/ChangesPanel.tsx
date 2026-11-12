/**
 * The list behind the "Changed since …" pill (#1397): what changed in the data,
 * the dashboard and the discussion, newest context first, with a way to mark it
 * all seen and a choice of when "changed" restarts.
 *
 * Reads the in-memory change set; it requests nothing itself. Dashboard rows go
 * to the editor's History (a reader who can edit) or the read-only preview
 * (everyone else) as plain links: this module imports no version-history UI.
 */
import React from 'react';
import { Anchor, Badge, Button, Divider, Group, ScrollArea, Stack, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useCommentsControl } from 'depictio-react-core';
import type { CommentChange, DashboardChange, DataChange, FailedIngestion } from 'depictio-react-core';

import { formatDateTimeVerbose, formatRelative } from '../lib/datetime';
import { FactBadge, NameChip, StatusBadge } from '../projects/badges';
import { CHECK_STATUS } from '../projects/checkStatus';
import ChangesModeSelect from './ChangesModeSelect';
import { useChangesSince, type ChangesSinceValue } from './ChangesSinceContext';
import {
  changeCounts,
  commentTarget,
  dashboardChangeText,
  dataFacts,
  historyHref,
  sampleSummary,
} from './describe';

const When: React.FC<{ at: string | null }> = ({ at }) => {
  if (!at) return null;
  return (
    <Tooltip label={formatDateTimeVerbose(at)} withArrow>
      <Text component="span" size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
        {formatRelative(at)}
      </Text>
    </Tooltip>
  );
};

const SectionHead: React.FC<{ icon: string; title: string; count: number; testId: string }> = ({
  icon,
  title,
  count,
  testId,
}) => (
  <Group gap={6} data-testid={`${testId}-head`}>
    <Icon icon={icon} width={14} aria-hidden />
    <Text size="xs" fw={600} tt="uppercase" c="dimmed">
      {title}
    </Text>
    <Badge size="xs" variant="default" circle>
      {count}
    </Badge>
  </Group>
);

const by = (people: string[]) => (people.length ? `by ${people.join(', ')}` : null);

const DataRow: React.FC<{ change: DataChange }> = ({ change }) => {
  const facts = dataFacts(change);
  const samples = sampleSummary(change);
  const people = by(change.by);
  return (
    <Stack gap={4} data-testid="changes-data-row" data-dc-id={change.dc_id}>
      <Group gap={6} wrap="wrap">
        <NameChip>{change.data_collection_tag}</NameChip>
        <StatusBadge color={change.kind === 'emptied' ? 'orange' : 'teal'}>
          {change.kind === 'emptied' ? 'emptied' : 'refreshed'}
        </StatusBadge>
        {facts.map((fact) => (
          <FactBadge key={fact}>{fact}</FactBadge>
        ))}
        {change.new_run_tags.map((tag) => (
          <NameChip key={tag} data-testid="changes-run-tag">
            {tag}
          </NameChip>
        ))}
      </Group>
      {samples.shown.length > 0 && (
        <Group gap={4} wrap="wrap" data-testid="changes-samples">
          {samples.shown.map((name) => (
            <NameChip key={name} size="xs" dimmed>
              {name}
            </NameChip>
          ))}
          {samples.more > 0 && (
            <Text size="xs" c="dimmed">
              +{samples.more}
            </Text>
          )}
        </Group>
      )}
      <Group gap={6}>
        {people && (
          <Text size="xs" c="dimmed">
            {people}
          </Text>
        )}
        <When at={change.at} />
      </Group>
    </Stack>
  );
};

const FailedRow: React.FC<{ failure: FailedIngestion }> = ({ failure }) => {
  const outcome = CHECK_STATUS[failure.status === 'failed' ? 'fail' : 'warn'];
  return (
    <Group gap={6} wrap="wrap" data-testid="changes-failed-row">
      <Tooltip label={outcome.label} withArrow>
        <span style={{ display: 'inline-flex', color: `var(--mantine-color-${outcome.color}-6)` }}>
          <Icon icon={outcome.icon} width={14} aria-label={outcome.label} />
        </span>
      </Tooltip>
      <Text size="sm">Ingestion {failure.status}</Text>
      {failure.data_collection_tags.map((tag) => (
        <NameChip key={tag} size="xs">
          {tag}
        </NameChip>
      ))}
      {failure.run_tags.map((tag) => (
        <NameChip key={tag} size="xs" dimmed>
          {tag}
        </NameChip>
      ))}
      <When at={failure.at} />
    </Group>
  );
};

const DashboardRow: React.FC<{ change: DashboardChange; ctx: ChangesSinceValue }> = ({ change, ctx }) => {
  const href = historyHref(change, ctx.tabId, ctx.canEdit);
  const people = by(change.authors);
  return (
    <Stack gap={2} data-testid="changes-dashboard-row">
      <Text size="sm">{dashboardChangeText(change)}</Text>
      <Group gap={6} wrap="wrap">
        {people && (
          <Text size="xs" c="dimmed">
            {people}
          </Text>
        )}
        <When at={change.at} />
        {href && (
          <Anchor
            href={href}
            size="xs"
            data-testid="changes-open-history"
            {...(ctx.canEdit ? {} : { target: '_blank', rel: 'noopener' })}
          >
            Open in History
          </Anchor>
        )}
      </Group>
    </Stack>
  );
};

const scrollToComponent = (index: string) => {
  const el = document.querySelector(`[data-component-index="${CSS.escape(index)}"]`);
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
};

const CommentRow: React.FC<{ comment: CommentChange; ctx: ChangesSinceValue; onDone: () => void }> = ({
  comment,
  ctx,
  onDone,
}) => {
  const comments = useCommentsControl();
  const { sameTab, tabHref } = commentTarget(comment, ctx.tabId);
  const open = () => {
    if (!sameTab && tabHref) {
      window.location.assign(tabHref);
      return;
    }
    onDone();
    if (comments) comments.openDrawer(comment.component_index);
    else if (comment.component_index) scrollToComponent(comment.component_index);
  };
  return (
    <UnstyledButton onClick={open} data-testid="changes-comment-row" style={{ textAlign: 'left' }}>
      <Stack gap={2}>
        <Group gap={6} wrap="wrap">
          <Text size="sm" fw={500}>
            {comment.author ?? 'Someone'}
          </Text>
          <Text size="xs" c="dimmed">
            {comment.kind === 'reply' ? 'replied' : 'commented'}
            {comment.component_title ? ` on ${comment.component_title}` : ''}
          </Text>
          <When at={comment.at} />
        </Group>
        {comment.excerpt && (
          <Text size="xs" c="dimmed" lineClamp={2}>
            {comment.excerpt}
          </Text>
        )}
      </Stack>
    </UnstyledButton>
  );
};

const ChangesPanel: React.FC<{ onClose?: () => void }> = ({ onClose }) => {
  const ctx = useChangesSince();
  if (!ctx) return null;
  const { changeSet: cs, readOnly } = ctx;
  const counts = changeCounts(cs);
  const close = onClose ?? (() => {});

  return (
    <Stack gap="sm" data-testid="changes-panel" style={{ minWidth: 0 }}>
      <ScrollArea.Autosize mah="min(60vh, 520px)" type="auto" offsetScrollbars>
        <Stack gap="md" pr={4}>
          {counts.data > 0 && (
            <Stack gap="xs" data-testid="changes-section-data">
              <SectionHead icon="mdi:database-outline" title="Data" count={counts.data} testId="changes-section-data" />
              {cs.failed_ingestions.map((f) => (
                <FailedRow key={f.run_id} failure={f} />
              ))}
              {cs.data.map((d) => (
                <DataRow key={d.dc_id} change={d} />
              ))}
            </Stack>
          )}
          {counts.dashboard > 0 && (
            <Stack gap="xs" data-testid="changes-section-dashboard">
              <SectionHead
                icon="mdi:view-dashboard-outline"
                title="Dashboard"
                count={counts.dashboard}
                testId="changes-section-dashboard"
              />
              {cs.dashboard.map((c, i) => (
                <DashboardRow key={`${c.version_id}-${c.key ?? c.tab_id}-${i}`} change={c} ctx={ctx} />
              ))}
            </Stack>
          )}
          {counts.comments > 0 && (
            <Stack gap="xs" data-testid="changes-section-comments">
              <SectionHead
                icon="mdi:comment-text-outline"
                title="Comments"
                count={counts.comments}
                testId="changes-section-comments"
              />
              {cs.comments.map((c, i) => (
                <CommentRow key={`${c.thread_id}-${c.at}-${i}`} comment={c} ctx={ctx} onDone={close} />
              ))}
            </Stack>
          )}
          {cs.approximate && (
            <Text size="xs" c="dimmed" data-testid="changes-approximate">
              Approximate: the version you last saw is gone, so this compares with the closest one
              left.
            </Text>
          )}
        </Stack>
      </ScrollArea.Autosize>

      {!readOnly && (
        <>
          <Divider />
          <Stack gap="xs">
            <Group justify="space-between" gap="xs" wrap="nowrap">
              <Text size="xs" c="dimmed">
                {ctx.mode === 'sticky'
                  ? 'Marks stay until you mark them seen.'
                  : 'Marks clear at your next visit.'}
              </Text>
              <Button
                size="compact-sm"
                variant="light"
                leftSection={<Icon icon="mdi:check-all" width={14} />}
                loading={ctx.seenBusy}
                onClick={() => {
                  void ctx.markAllSeen().then(close);
                }}
                data-testid="changes-mark-seen"
              >
                Mark as seen
              </Button>
            </Group>
            <ChangesModeSelect value={ctx.mode} onChange={ctx.setMode} />
          </Stack>
        </>
      )}
    </Stack>
  );
};

export default ChangesPanel;
