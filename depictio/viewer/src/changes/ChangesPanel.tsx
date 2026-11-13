/**
 * The list behind the header's "What's new" button (#1397): what changed in
 * the data, the dashboard and the discussion, with a way to mark it all seen
 * and a choice of when "changed" restarts.
 *
 * Reads the in-memory change set; it requests nothing itself. Dashboard rows go
 * to the editor's History (a reader who can edit) or the read-only preview
 * (everyone else) as plain links: this module imports no version-history UI.
 */
import React from 'react';
import {
  Button,
  ColorSwatch,
  Divider,
  Group,
  ScrollArea,
  SegmentedControl,
  Stack,
  Switch,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useCommentsControl } from 'depictio-react-core';
import type { CommentChange, DashboardChange, DataChange, FailedIngestion } from 'depictio-react-core';

import ChangesModeSelect from './ChangesModeSelect';
import { useChangesSince, type ChangesSinceValue } from './ChangesSinceContext';
import type { NewsView } from './newsSplit';
import {
  changeCounts,
  commentTarget,
  dashboardChangeText,
  dataFacts,
  historyHref,
  sampleSummary,
} from './describe';
import { FeedHeader, FeedItem, FeedSection, facts, nameList } from './feed';
import { newRowsHref } from './NewRowsPreview';

const VIEW_HINT: Record<NewsView, string> = {
  off: 'The figures as they are now.',
  overlay: 'Each changed figure marks what is new; what was already there fades.',
  split: 'Figures drawn twice, what is new beside what you had seen (new runs, or new MultiQC samples); cards compare the two.',
  new: 'Only what is new is drawn (the new runs, or the new MultiQC samples); what you had seen is hidden.',
};

const segment = (icon: string, label: string) => (
  <Group gap={5} wrap="nowrap" justify="center">
    <Icon icon={icon} width={14} height={14} />
    <span>{label}</span>
  </Group>
);

/**
 * Off | Overlay | Split: how the news shows on the figures and cards. Hiding
 * what was seen is a variant of the overlay (fade the rest, or drop it), so it
 * is a switch under it rather than a fourth choice.
 */
const NewsViewControl: React.FC<{ ctx: ChangesSinceValue }> = ({ ctx }) => {
  const overlayish = ctx.view === 'overlay' || ctx.view === 'new';
  return (
    <Stack gap={6} px={4}>
      <Text size="xs" c="dimmed">
        Show on the dashboard
      </Text>
      <SegmentedControl
        size="xs"
        fullWidth
        value={overlayish ? 'overlay' : ctx.view}
        onChange={(v) => ctx.setView(v as NewsView)}
        data={[
          { value: 'off', label: segment('tabler:eye-off', 'Off') },
          {
            value: 'overlay',
            label: segment('tabler:highlight', 'Overlay'),
            disabled: ctx.highlightable === 0 && !ctx.splitAvailable,
          },
          {
            value: 'split',
            label: segment('tabler:layout-columns', 'Split'),
            disabled: !ctx.splitAvailable,
          },
        ]}
        aria-label="Show what is new on the dashboard"
        data-testid="changes-view"
      />
      {overlayish && (
        <Switch
          size="xs"
          label="Hide what you had seen"
          checked={ctx.view === 'new'}
          disabled={!ctx.splitAvailable}
          onChange={(e) => ctx.setView(e.currentTarget.checked ? 'new' : 'overlay')}
          data-testid="changes-hide-seen"
        />
      )}
      <Text size="xs" c="dimmed">
        {VIEW_HINT[ctx.view]}
        {!ctx.splitAvailable &&
          ctx.view !== 'off' &&
          ' Split and hiding need something new beside something seen: a new run, or new MultiQC samples. Data rewritten in place shows in Before | Now.'}
      </Text>
      {ctx.splitGroups && (
        <Group gap="md" data-testid="changes-split-legend">
          {ctx.splitGroups.map((g) => (
            <Group key={g.name} gap={6} wrap="nowrap">
              <ColorSwatch color={g.color} size={10} withShadow={false} />
              <Text size="xs">{g.name}</Text>
            </Group>
          ))}
        </Group>
      )}
    </Stack>
  );
};

/** "1 new run" becomes "1 new run: run_c": the names are what a reader looks for. */
function dataSummary(change: DataChange): string {
  const runs = change.new_run_tags;
  return facts(
    change.kind === 'emptied' ? 'Emptied' : 'Refreshed',
    ...dataFacts(change).map((fact) => (runs.length && /new runs?$/.test(fact) ? `${fact}: ${nameList(runs)}` : fact)),
  );
}

/** A Delta collection that gained runs: its new rows can be shown. */
const showsNewRows = (change: DataChange) =>
  change.kind === 'refreshed' && change.dc_type !== 'multiqc' && change.new_run_tags.length > 0;

const DataRow: React.FC<{
  change: DataChange;
  projectId: string | null;
  onViewRows?: (change: DataChange) => void;
}> = ({ change, projectId, onViewRows }) => {
  const samples = sampleSummary(change);
  const withRows = showsNewRows(change);
  return (
    <FeedItem
      kind={change.kind === 'emptied' ? 'emptied' : 'data'}
      title={change.data_collection_tag}
      summary={dataSummary(change)}
      detail={
        samples.shown.length > 0
          ? `${samples.shown.join(', ')}${samples.more > 0 ? ` +${samples.more}` : ''}`
          : undefined
      }
      detailMono
      detailTestId="changes-samples"
      by={change.by}
      at={change.at}
      data-testid="changes-data-row"
      data-dc-id={change.dc_id}
    >
      {withRows && (
        <Group gap="xs" mt={4}>
          {onViewRows && (
            <Button
              size="compact-xs"
              variant="light"
              leftSection={<Icon icon="tabler:table" width={13} />}
              onClick={() => onViewRows(change)}
              data-testid="changes-view-rows"
            >
              View new rows
            </Button>
          )}
          {projectId && (
            <Button
              size="compact-xs"
              variant="subtle"
              component="a"
              href={newRowsHref(projectId, change.dc_id, change.new_run_tags)}
              leftSection={<Icon icon="tabler:external-link" width={13} />}
              data-testid="changes-open-in-project"
            >
              Open in project
            </Button>
          )}
        </Group>
      )}
    </FeedItem>
  );
};

const FailedRow: React.FC<{ failure: FailedIngestion }> = ({ failure }) => (
  <FeedItem
    kind="failed"
    title={`Ingestion ${failure.status}`}
    summary={facts(
      failure.data_collection_tags.length ? nameList(failure.data_collection_tags) : null,
      failure.run_tags.length ? `run ${nameList(failure.run_tags)}` : null,
    )}
    at={failure.at}
    data-testid="changes-failed-row"
  />
);

const DashboardRow: React.FC<{ change: DashboardChange; ctx: ChangesSinceValue }> = ({ change, ctx }) => {
  const href = historyHref(change, ctx.tabId, ctx.canEdit);
  return (
    <FeedItem
      kind="dashboard"
      title={dashboardChangeText(change)}
      by={change.authors}
      at={change.at}
      action={
        href
          ? { label: 'Open in History', href, newTab: !ctx.canEdit, testId: 'changes-open-history' }
          : undefined
      }
      data-testid="changes-dashboard-row"
    />
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
  const verb = comment.kind === 'reply' ? 'replied' : 'commented';
  return (
    <FeedItem
      kind="comment"
      title={`${comment.author ?? 'Someone'} ${verb}${comment.component_title ? ` on ${comment.component_title}` : ''}`}
      detail={comment.excerpt || undefined}
      at={comment.at}
      onClick={open}
      data-testid="changes-comment-row"
    />
  );
};

const ChangesPanel: React.FC<{
  onClose?: () => void;
  subtitle?: React.ReactNode;
  /** Opens a collection's new rows; held by the caller, outside the popover. */
  onViewRows?: (change: DataChange) => void;
}> = ({
  onClose,
  subtitle,
  onViewRows,
}) => {
  const ctx = useChangesSince();
  if (!ctx) return null;
  const { changeSet: cs, readOnly } = ctx;
  const counts = changeCounts(cs);
  const close = onClose ?? (() => {});

  return (
    <Stack gap="xs" data-testid="changes-panel" style={{ minWidth: 0 }}>
      <FeedHeader
        title={readOnly ? 'Changes' : "What's new"}
        subtitle={subtitle}
        action={
          !readOnly && (
            <Button
              size="compact-sm"
              variant="subtle"
              leftSection={<Icon icon="mdi:check-all" width={15} />}
              loading={ctx.seenBusy}
              onClick={() => {
                void ctx.markAllSeen().then(close);
              }}
              data-testid="changes-mark-seen"
            >
              Mark as seen
            </Button>
          )
        }
      />
      {(ctx.highlightable > 0 || ctx.splitAvailable) && <NewsViewControl ctx={ctx} />}
      <Divider />
      <ScrollArea.Autosize mah="min(60vh, 520px)" type="auto" offsetScrollbars>
        <Stack gap="sm">
          {counts.data > 0 && (
            <FeedSection title="Data" count={counts.data} testId="changes-section-data">
              {cs.failed_ingestions.map((f) => (
                <FailedRow key={f.run_id} failure={f} />
              ))}
              {cs.data.map((d) => (
                <DataRow key={d.dc_id} change={d} projectId={ctx.projectId} onViewRows={onViewRows} />
              ))}
            </FeedSection>
          )}
          {counts.dashboard > 0 && (
            <FeedSection title="Dashboard" count={counts.dashboard} testId="changes-section-dashboard">
              {cs.dashboard.map((c, i) => (
                <DashboardRow key={`${c.version_id}-${c.key ?? c.tab_id}-${i}`} change={c} ctx={ctx} />
              ))}
            </FeedSection>
          )}
          {counts.comments > 0 && (
            <FeedSection title="Comments" count={counts.comments} testId="changes-section-comments">
              {cs.comments.map((c, i) => (
                <CommentRow key={`${c.thread_id}-${c.at}-${i}`} comment={c} ctx={ctx} onDone={close} />
              ))}
            </FeedSection>
          )}
          {cs.approximate && (
            <Text size="xs" c="dimmed" px={8} data-testid="changes-approximate">
              Approximate: the version you last saw is gone, so this compares with the closest one
              left.
            </Text>
          )}
        </Stack>
      </ScrollArea.Autosize>

      {!readOnly && (
        <>
          <Divider />
          <Stack gap={6} px={4}>
            <Text size="xs" c="dimmed">
              Show changes
            </Text>
            <ChangesModeSelect value={ctx.mode} onChange={ctx.setMode} />
          </Stack>
        </>
      )}
    </Stack>
  );
};

export default ChangesPanel;
