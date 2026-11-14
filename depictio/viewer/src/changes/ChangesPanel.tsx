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
  Chip,
  ColorSwatch,
  Divider,
  Group,
  Paper,
  SegmentedControl,
  Select,
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
  newsByRun,
  plural,
  projectRunsHref,
  runFacts,
  sampleSummary,
  type RunNews,
} from './describe';
import {
  FEED_KIND,
  type FeedAction,
  FeedHeader,
  FeedIconAction,
  FeedItem,
  FeedMarkSeen,
  FeedScroll,
  FeedSection,
  facts,
  nameList,
} from './feed';
import { newRowsHref } from './NewRowsPreview';
import { CHANGE_COLOR } from './palette';

const VIEW_HINT: Record<NewsView, string> = {
  off: 'The figures as they are now.',
  overlay: 'Figures colour the new runs and grey the runs you had seen, in one panel; MultiQC fades the samples you had seen.',
  split: 'Figures drawn twice, what is new beside what you had seen (new runs, or new MultiQC samples); cards compare the two.',
  new: 'Only what is new is drawn (the new runs, or the new MultiQC samples); what you had seen is hidden.',
};

/** The hint while one run is followed: it is the new side, every other run
 *  (new or seen) the other. */
function focusHint(view: NewsView, run: string): string {
  if (view === 'new') return `Only ${run} is drawn: every other run is hidden.`;
  if (view === 'split') return `Figures drawn twice: ${run} beside every other run.`;
  return `Figures colour ${run} and grey every other run, in one panel.`;
}

const segment = (icon: string, label: string) => (
  <Group gap={5} wrap="nowrap" justify="center">
    <Icon icon={icon} width={14} height={14} />
    <span>{label}</span>
  </Group>
);

const ALL_RUNS = '__all__';
/** Up to this many new runs, a chip each; beyond, a select to search them. */
const RUN_CHIPS_MAX = 5;
/** Runs listed before the older ones fold away. */
const RUNS_OPEN = 5;

/** Follows one new run: a chip each up to `RUN_CHIPS_MAX` runs, a searchable
 *  select beyond; nothing to choose between with a single run. */
const RunFocus: React.FC<{
  runs: string[];
  focusRun: string | null;
  onPick: (value: string | null) => void;
}> = ({ runs, focusRun, onPick }) => {
  const value = focusRun ?? ALL_RUNS;
  if (runs.length > RUN_CHIPS_MAX) {
    return (
      <Select
        size="xs"
        searchable
        allowDeselect={false}
        leftSection={<Icon icon="tabler:focus-2" width={14} />}
        value={value}
        onChange={onPick}
        data={[
          { value: ALL_RUNS, label: `All ${runs.length} new runs` },
          ...runs.map((run) => ({ value: run, label: run })),
        ]}
        nothingFoundMessage="No such run"
        comboboxProps={{ withinPortal: false }}
        aria-label="Run shown on the dashboard"
        data-testid="changes-run-focus-select"
      />
    );
  }
  if (runs.length <= 1) return null;
  const chips = [
    { value: ALL_RUNS, label: 'All new runs', testId: 'changes-run-focus-all' },
    ...runs.map((run) => ({ value: run, label: run, testId: `changes-run-focus-${run}` })),
  ];
  return (
    <Chip.Group multiple={false} value={value} onChange={onPick}>
      {/* Blue like every "new" mark, whatever the page's primary. */}
      <Group gap={4} data-testid="changes-run-focus">
        {chips.map((chip) => (
          <Chip
            key={chip.value}
            size="xs"
            variant="outline"
            color={CHANGE_COLOR.new}
            value={chip.value}
            data-testid={chip.testId}
          >
            {chip.label}
          </Chip>
        ))}
      </Group>
    </Chip.Group>
  );
};

/**
 * Off | Overlay | Split: how the news shows on the figures and cards. Hiding
 * what was seen is a variant of the overlay (fade the rest, or drop it), so it
 * is a switch under it rather than a fourth choice. With several new runs, a
 * row of chips follows one of them instead of all (epic #1399).
 */
const NewsViewControl: React.FC<{ ctx: ChangesSinceValue; runOrder: string[] }> = ({ ctx, runOrder }) => {
  const overlayish = ctx.view === 'overlay' || ctx.view === 'new';
  // Newest first, as the list below: the runs the panel dates, then any other.
  const runs = [...runOrder.filter((r) => ctx.newRuns.includes(r)), ...ctx.newRuns.filter((r) => !runOrder.includes(r))];
  const pickRun = (v: string | null) => (!v || v === ALL_RUNS ? ctx.setFocusRun(null) : ctx.showRun(v));
  return (
    <Paper withBorder radius="md" p="xs" className="dc-news-card" data-testid="changes-view-card">
      <Stack gap={8}>
        <Text component="div" className="dc-feed-section" p={0}>
          <Icon icon="tabler:eye" width={13} aria-hidden />
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
        <RunFocus runs={runs} focusRun={ctx.focusRun} onPick={pickRun} />
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
          {ctx.focusRun && ctx.view !== 'off' ? focusHint(ctx.view, ctx.focusRun) : VIEW_HINT[ctx.view]}
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
    </Paper>
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

/** "View new rows" and "Open in project", as icons, for a collection that
 *  gained runs. */
const RowActions: React.FC<{
  change: DataChange;
  projectId: string | null;
  onViewRows?: (change: DataChange) => void;
}> = ({ change, projectId, onViewRows }) => {
  if (!showsNewRows(change)) return null;
  return (
    <>
      {onViewRows && (
        <FeedIconAction
          icon="tabler:table"
          label="View new rows"
          onClick={() => onViewRows(change)}
          testId="changes-view-rows"
        />
      )}
      {projectId && (
        <FeedIconAction
          icon="tabler:external-link"
          label="Open in project"
          href={newRowsHref(projectId, change.dc_id, change.new_run_tags)}
          testId="changes-open-in-project"
        />
      )}
    </>
  );
};

const samplesText = (change: DataChange): string | undefined => {
  const samples = sampleSummary(change);
  return samples.shown.length > 0
    ? `${samples.shown.join(', ')}${samples.more > 0 ? ` +${samples.more}` : ''}`
    : undefined;
};

const DataRow: React.FC<{
  change: DataChange;
  projectId: string | null;
  onViewRows?: (change: DataChange) => void;
}> = ({ change, projectId, onViewRows }) => (
  <FeedItem
    kind={change.kind === 'emptied' ? 'emptied' : 'data'}
    title={change.data_collection_tag}
    summary={dataSummary(change)}
    detail={samplesText(change)}
    detailMono
    detailTestId="changes-samples"
    by={change.by}
    at={change.at}
    aside={<RowActions change={change} projectId={projectId} onViewRows={onViewRows} />}
    data-testid="changes-data-row"
    data-dc-id={change.dc_id}
  />
);

/** One collection under its heading (a run, or "recomputed over every run"),
 *  which is not repeated on the line. */
const CollectionLine: React.FC<{
  change: DataChange;
  /** Under a run: its new rows are that run's alone. */
  run?: string;
  projectId: string | null;
  onViewRows?: (change: DataChange) => void;
}> = ({ change, run, projectId, onViewRows }) => {
  const own = dataFacts(change).filter((f) => !/new runs?$/.test(f) && !f.startsWith('recomputed:'));
  // Rewritten with as many rows (a recomputation): still a change, say which.
  if (own.length === 0 && change.kind === 'refreshed') own.push('same rows, new values');
  const forRun = run && change.new_run_tags.includes(run) ? { ...change, new_run_tags: [run] } : change;
  const samples = samplesText(change);
  return (
    <Group
      gap={6}
      wrap="nowrap"
      justify="space-between"
      align="center"
      className="dc-feed-sub"
      data-testid="changes-data-row"
      data-dc-id={change.dc_id}
    >
      {/* Name, then its facts, then its samples: the lines of a feed row,
       *  the actions beside them rather than on the first line. */}
      <Stack gap={1} style={{ minWidth: 0, flex: 1 }}>
        <Text size="xs" fw={500} truncate>
          {change.data_collection_tag}
        </Text>
        {own.length > 0 && (
          <Text size="xs" c="dimmed">
            {facts(...own)}
          </Text>
        )}
        {samples && (
          <Text size="xs" c="dimmed" lineClamp={2} className="dc-feed-item__detail--mono" data-testid="changes-samples">
            {samples}
          </Text>
        )}
      </Stack>
      <Group gap={2} wrap="nowrap" style={{ flexShrink: 0 }}>
        <RowActions change={forRun} projectId={projectId} onViewRows={onViewRows} />
      </Group>
    </Group>
  );
};

/** Collections listed under a run before the rest fold away. */
const RUN_LINES_OPEN = 3;

/** The "Show N collections" / "Hide collections" link of a folding row, or
 *  nothing when every collection is already shown. */
function collectionsToggle(
  count: number,
  open: boolean,
  setOpen: React.Dispatch<React.SetStateAction<boolean>>,
  testId: string,
): FeedAction[] | undefined {
  if (count <= RUN_LINES_OPEN) return undefined;
  return [
    {
      label: open ? 'Hide collections' : `Show ${count} collections`,
      onClick: () => setOpen((v) => !v),
      testId,
    },
  ];
}

/** One new run and what it brought, the way runs arrive (epic #1399). */
const RunRow: React.FC<{
  news: RunNews;
  ctx: ChangesSinceValue;
  onViewRows?: (change: DataChange) => void;
}> = ({ news, ctx, onViewRows }) => {
  const { projectId } = ctx;
  const lines = news.collections;
  const [open, setOpen] = React.useState(lines.length <= RUN_LINES_OPEN);
  const shown = ctx.focusRun === news.run && ctx.view !== 'off';
  const canShow = ctx.highlightable > 0 || ctx.splitAvailable;
  return (
    <FeedItem
      kind="run"
      title={news.run}
      summary={runFacts(news).join(' · ') || 'New run'}
      by={news.by}
      at={news.at}
      aside={
        <>
          {canShow && (
            <FeedIconAction
              icon={shown ? 'tabler:focus-centered' : 'tabler:focus-2'}
              label={shown ? 'Show every new run again' : 'Show only this run on the dashboard'}
              onClick={() => ctx.showRun(news.run)}
              active={shown}
              testId="changes-run-show"
            />
          )}
          {projectId && (
            <FeedIconAction
              icon="tabler:external-link"
              label="Open the run in its project"
              href={projectRunsHref(projectId, news.run)}
              testId="changes-run-open"
            />
          )}
        </>
      }
      actions={collectionsToggle(lines.length, open, setOpen, 'changes-run-toggle')}
      data-testid="changes-run-row"
      data-run-tag={news.run}
      data-focused={shown}
    >
      {open && (
        <Stack gap={2} mt={6}>
          {lines.map((change) => (
            <CollectionLine
              key={change.dc_id}
              change={change}
              run={news.run}
              projectId={projectId}
              onViewRows={onViewRows}
            />
          ))}
        </Stack>
      )}
    </FeedItem>
  );
};

/** The recipes recomputed over every run, once: their rows mix the runs'
 *  samples, so they belong to no run in particular. */
const RecomputedRow: React.FC<{
  changes: DataChange[];
  ctx: ChangesSinceValue;
  onViewRows?: (change: DataChange) => void;
}> = ({ changes, ctx, onViewRows }) => {
  const [open, setOpen] = React.useState(changes.length <= RUN_LINES_OPEN);
  const at = changes.map((c) => c.at).filter(Boolean).sort().pop() ?? null;
  return (
    <FeedItem
      kind="recomputed"
      title="Recomputed over every run"
      summary={plural(changes.length, 'collection')}
      detail="They mix samples, so each new run recomputes them: rows of the runs you had seen changed too."
      at={at}
      actions={collectionsToggle(changes.length, open, setOpen, 'changes-recomputed-toggle')}
      data-testid="changes-recomputed-row"
    >
      {open && (
        <Stack gap={2} mt={6}>
          {changes.map((change) => (
            <CollectionLine key={change.dc_id} change={change} projectId={ctx.projectId} onViewRows={onViewRows} />
          ))}
        </Stack>
      )}
    </FeedItem>
  );
};

/** The new runs, newest first; past `RUNS_OPEN` the older ones fold away,
 *  except the one in focus, which stays in sight. */
const RunList: React.FC<{
  runs: RunNews[];
  ctx: ChangesSinceValue;
  onViewRows?: (change: DataChange) => void;
}> = ({ runs, ctx, onViewRows }) => {
  const [all, setAll] = React.useState(false);
  const visible = all ? runs : runs.filter((r, i) => i < RUNS_OPEN || r.run === ctx.focusRun);
  const foldedCount = runs.length - visible.length;
  return (
    <>
      {visible.map((r) => (
        <RunRow key={r.run} news={r} ctx={ctx} onViewRows={onViewRows} />
      ))}
      {(all || foldedCount > 0) && (
        <Button
          size="compact-xs"
          variant="subtle"
          color="gray"
          leftSection={<Icon icon={all ? 'tabler:chevron-up' : 'tabler:chevron-down'} width={13} />}
          onClick={() => setAll((v) => !v)}
          style={{ alignSelf: 'flex-start' }}
          data-testid="changes-older-runs"
        >
          {all ? 'Show fewer runs' : plural(foldedCount, 'older run')}
        </Button>
      )}
    </>
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
  const news = newsByRun(cs.data);
  const close = onClose ?? (() => {});

  return (
    <Stack gap="xs" data-testid="changes-panel" style={{ minWidth: 0 }}>
      <FeedHeader
        title={readOnly ? 'Changes' : "What's new"}
        subtitle={subtitle}
        action={
          !readOnly && (
            <FeedMarkSeen
              loading={ctx.seenBusy}
              onClick={() => {
                void ctx.markAllSeen().then(close);
              }}
              testId="changes-mark-seen"
            />
          )
        }
      />
      {(ctx.highlightable > 0 || ctx.splitAvailable) && (
        <NewsViewControl ctx={ctx} runOrder={news.runs.map((r) => r.run)} />
      )}
      <FeedScroll mah="min(60vh, 520px)">
        <Stack gap="sm">
          {counts.data > 0 && (
            <FeedSection title="Data" icon={FEED_KIND.data.icon} count={counts.data} testId="changes-section-data">
              {cs.failed_ingestions.map((f) => (
                <FailedRow key={f.run_id} failure={f} />
              ))}
              <RunList runs={news.runs} ctx={ctx} onViewRows={onViewRows} />
              {news.recomputed.length > 0 && (
                <RecomputedRow changes={news.recomputed} ctx={ctx} onViewRows={onViewRows} />
              )}
              {news.other.map((d) => (
                <DataRow key={d.dc_id} change={d} projectId={ctx.projectId} onViewRows={onViewRows} />
              ))}
            </FeedSection>
          )}
          {counts.dashboard > 0 && (
            <FeedSection
              title="Dashboard"
              icon={FEED_KIND.dashboard.icon}
              count={counts.dashboard}
              testId="changes-section-dashboard"
            >
              {cs.dashboard.map((c, i) => (
                <DashboardRow key={`${c.version_id}-${c.key ?? c.tab_id}-${i}`} change={c} ctx={ctx} />
              ))}
            </FeedSection>
          )}
          {counts.comments > 0 && (
            <FeedSection
              title="Comments"
              icon={FEED_KIND.comment.icon}
              count={counts.comments}
              testId="changes-section-comments"
            >
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
      </FeedScroll>

      {!readOnly && (
        <>
          <Divider />
          <Stack gap={6} px={4}>
            <Text component="div" className="dc-feed-section" p={0}>
              <Icon icon="tabler:clock" width={13} aria-hidden />
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
