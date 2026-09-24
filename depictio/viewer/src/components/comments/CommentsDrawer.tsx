import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Chip,
  Drawer,
  Group,
  Loader,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
  Textarea,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import {
  componentTypeVisual,
  createCommentThread,
  fetchCommentThreads,
  Z_LAYERS,
} from 'depictio-react-core';
import type {
  CommentThread,
  CommentThreadStatus,
  CommentViewState,
  InteractiveFilter,
  StoredMetadata,
} from 'depictio-react-core';

import { useUiStore } from '../../store/useUiStore';
import type { CurrentUser } from '../../hooks/useCurrentUser';
import { focusComponent } from '../../lib/focusComponent';
import ThreadCard from './ThreadCard';
import { buildViewState, componentLabel, selectionHint } from './viewState';

/** Matches the dashboard header, so the drawer docks below it. */
const DASHBOARD_HEADER_HEIGHT = 50;
const DRAWER_WIDTH = 'min(420px, 92vw)';

type StatusFilter = 'open' | 'resolved' | 'proposed';
const DEFAULT_STATUSES: StatusFilter[] = ['open', 'proposed'];
const TAB_GROUP = '__tab__';

export interface CommentsDrawerProps {
  dashboardId: string;
  metadata: StoredMetadata[];
  filters: InteractiveFilter[];
  onApplyViewState: (viewState: CommentViewState) => void;
  currentUser: CurrentUser | null;
  /** Called after every successful mutation, to refresh the chrome badges. */
  onMutated: () => void;
}

interface ThreadGroup {
  key: string;
  label: string;
  icon: string;
  removed: boolean;
  threads: CommentThread[];
}

/**
 * The comments side panel: one component's threads, or every thread on the
 * tab grouped by component, with a composer that attaches the current view.
 *
 * Docked rather than modal (no overlay, no focus trap) so that clicking a
 * thread can scroll the dashboard behind it to the component it is about.
 */
const CommentsDrawer: React.FC<CommentsDrawerProps> = ({
  dashboardId,
  metadata,
  filters,
  onApplyViewState,
  currentUser,
  onMutated,
}) => {
  const opened = useUiStore((s) => s.commentsOpen);
  const scope = useUiStore((s) => s.commentsScope);
  const componentIndex = useUiStore((s) => s.commentsComponentIndex);
  const focusedThreadId = useUiStore((s) => s.focusedThreadId);
  const closeComments = useUiStore((s) => s.closeComments);
  const setScope = useUiStore((s) => s.setCommentsScope);
  const openComments = useUiStore((s) => s.openComments);
  const setFocusedThread = useUiStore((s) => s.setFocusedThread);

  const [threads, setThreads] = useState<CommentThread[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [statuses, setStatuses] = useState<StatusFilter[]>(DEFAULT_STATUSES);
  const [draft, setDraft] = useState('');
  const [posting, setPosting] = useState(false);

  const metaByIndex = useMemo(() => {
    const m = new Map<string, StoredMetadata>();
    metadata.forEach((meta) => m.set(String(meta.index), meta));
    return m;
  }, [metadata]);

  // Every thread of the tab is loaded once per opening; the component scope
  // and the status chips filter client-side, so switching them is instant.
  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setThreads(await fetchCommentThreads(dashboardId, { scope: 'tab' }));
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  }, [dashboardId]);

  useEffect(() => {
    setThreads(null);
  }, [dashboardId]);

  useEffect(() => {
    if (opened) void load();
  }, [opened, load]);

  const effectiveScope = scope === 'component' && componentIndex ? 'component' : 'tab';
  const targetIndex = effectiveScope === 'component' ? componentIndex : null;
  const targetMeta = targetIndex ? metaByIndex.get(targetIndex) : undefined;

  const scoped = useMemo(
    () =>
      (threads ?? []).filter(
        (t) => effectiveScope === 'tab' || t.anchor.component_index === componentIndex,
      ),
    [threads, effectiveScope, componentIndex],
  );

  const statusCounts = useMemo(() => {
    const c: Record<CommentThreadStatus, number> = { open: 0, resolved: 0, proposed: 0, rejected: 0 };
    scoped.forEach((t) => {
      c[t.status] += 1;
    });
    return c;
  }, [scoped]);

  const visible = useMemo(
    () => scoped.filter((t) => (statuses as string[]).includes(t.status)),
    [scoped, statuses],
  );

  const groups = useMemo<ThreadGroup[]>(() => {
    const byKey = new Map<string, CommentThread[]>();
    visible.forEach((t) => {
      const key = t.anchor.component_index ?? TAB_GROUP;
      const list = byKey.get(key);
      if (list) list.push(t);
      else byKey.set(key, [t]);
    });
    const order = metadata.map((m) => String(m.index));
    const keys = [...byKey.keys()].sort((a, b) => {
      if (a === TAB_GROUP) return -1;
      if (b === TAB_GROUP) return 1;
      const ia = order.indexOf(a);
      const ib = order.indexOf(b);
      return (ia < 0 ? Infinity : ia) - (ib < 0 ? Infinity : ib);
    });
    return keys.map((key) => {
      const list = byKey.get(key) ?? [];
      if (key === TAB_GROUP) {
        return { key, label: 'Tab', icon: 'mdi:tab', removed: false, threads: list };
      }
      const meta = metaByIndex.get(key);
      const fallbackTitle = list.find((t) => t.anchor.component_title)?.anchor.component_title;
      return {
        key,
        label: meta
          ? componentLabel(meta, fallbackTitle)
          : fallbackTitle
            ? `${fallbackTitle} (removed)`
            : 'Removed component',
        icon: meta ? componentTypeVisual(meta.component_type).icon : 'mdi:puzzle-remove-outline',
        removed: !meta,
        threads: list,
      };
    });
  }, [visible, metadata, metaByIndex]);

  const viewState = useMemo(() => buildViewState(filters, targetIndex), [filters, targetIndex]);
  const attachHint = selectionHint(viewState.selection);

  const replaceThread = useCallback(
    (next: CommentThread) => {
      setThreads((prev) => (prev ?? []).map((t) => (t.id === next.id ? next : t)));
      onMutated();
    },
    [onMutated],
  );

  const removeThread = useCallback(
    (id: string) => {
      setThreads((prev) => (prev ?? []).filter((t) => t.id !== id));
      onMutated();
    },
    [onMutated],
  );

  const post = async () => {
    const body = draft.trim();
    if (!body) return;
    setPosting(true);
    try {
      const created = await createCommentThread({
        anchor: {
          dashboard_id: dashboardId,
          component_index: targetIndex,
          component_title: targetMeta ? componentLabel(targetMeta) : null,
          view_state: viewState,
        },
        body,
      });
      setThreads((prev) => [created, ...(prev ?? [])]);
      setDraft('');
      // Make sure the new thread is not hidden by the status chips.
      setStatuses((prev) =>
        prev.includes(created.status as StatusFilter) || created.status === 'rejected'
          ? prev
          : [...prev, created.status as StatusFilter],
      );
      onMutated();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not post comment',
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setPosting(false);
    }
  };

  const focusThread = useCallback(
    (thread: CommentThread) => {
      setFocusedThread(thread.id);
      if (thread.anchor.view_state) onApplyViewState(thread.anchor.view_state);
      const idx = thread.anchor.component_index;
      if (idx && !focusComponent(idx, { flashClass: 'depictio-comment-flash', durationMs: 1800 })) {
        notifications.show({
          color: 'gray',
          message: thread.staleness?.component_missing
            ? 'This component has been removed from the dashboard.'
            : 'This component is not shown on the page right now.',
          autoClose: 2500,
        });
      }
    },
    [onApplyViewState, setFocusedThread],
  );

  const renderThreads = (list: CommentThread[]) =>
    list.map((t) => (
      <ThreadCard
        key={t.id}
        thread={t}
        currentUser={currentUser}
        focused={t.id === focusedThreadId}
        onFocus={focusThread}
        onChange={replaceThread}
        onDeleted={removeThread}
      />
    ));

  const chip = (value: StatusFilter, label: string) => (
    <Chip value={value} size="xs" variant="light">
      {label}
      {statusCounts[value] ? ` (${statusCounts[value]})` : ''}
    </Chip>
  );

  return (
    <Drawer
      opened={opened}
      onClose={closeComments}
      position="right"
      size={DRAWER_WIDTH}
      padding="md"
      zIndex={Z_LAYERS.overlay}
      withOverlay={false}
      trapFocus={false}
      lockScroll={false}
      closeOnClickOutside={false}
      shadow="xl"
      styles={{
        inner: { top: DASHBOARD_HEADER_HEIGHT },
        content: { display: 'flex', flexDirection: 'column' },
        body: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
      }}
      title={
        <Group gap="xs">
          <Icon icon="mdi:comment-text-multiple-outline" width={20} height={20} />
          <Text fw={600} size="md">
            Comments
          </Text>
        </Group>
      }
      data-testid="comments-drawer"
    >
      <Stack gap="sm" style={{ flex: 1, minHeight: 0 }}>
        <SegmentedControl
          fullWidth
          size="xs"
          value={effectiveScope}
          onChange={(v) => setScope(v as 'component' | 'tab')}
          data={[
            { label: 'This component', value: 'component', disabled: !componentIndex },
            { label: 'Whole tab', value: 'tab' },
          ]}
        />

        <Stack gap={6}>
          <Group gap={6} wrap="nowrap">
            <Icon
              icon={targetMeta ? componentTypeVisual(targetMeta.component_type).icon : 'mdi:tab'}
              width={14}
            />
            <Text size="xs" c="dimmed" truncate>
              {targetIndex
                ? `New comment on ${componentLabel(targetMeta, null)}`
                : 'New comment on the whole tab'}
            </Text>
          </Group>
          <Textarea
            size="sm"
            autosize
            minRows={2}
            maxRows={8}
            placeholder="Write a comment…"
            value={draft}
            onChange={(e) => setDraft(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void post();
            }}
            maxLength={4000}
            aria-label="New comment"
          />
          <Group justify="space-between" wrap="nowrap" gap="xs">
            <Stack gap={0}>
              {attachHint && (
                <Text size="xs" c="dimmed">
                  {attachHint} will be attached
                </Text>
              )}
              {filters.length > 0 && (
                <Text size="xs" c="dimmed">
                  {filters.length} active filter{filters.length === 1 ? '' : 's'} will be attached
                </Text>
              )}
            </Stack>
            <Button
              size="xs"
              onClick={post}
              loading={posting}
              disabled={!draft.trim()}
              leftSection={<Icon icon="mdi:send" width={14} />}
            >
              Post
            </Button>
          </Group>
        </Stack>

        <Chip.Group
          multiple
          value={statuses}
          onChange={(v) => setStatuses(v as StatusFilter[])}
        >
          <Group gap={6}>
            {chip('open', 'Open')}
            {chip('resolved', 'Resolved')}
            {chip('proposed', 'Proposed')}
          </Group>
        </Chip.Group>

        <ScrollArea style={{ flex: 1, minHeight: 0 }} offsetScrollbars type="auto">
          {loadError ? (
            <Alert color="red" variant="light" title="Could not load comments">
              <Stack gap="xs">
                <Text size="xs">{loadError}</Text>
                <Button size="compact-xs" variant="light" color="red" onClick={() => void load()}>
                  Retry
                </Button>
              </Stack>
            </Alert>
          ) : threads === null ? (
            <Center py="xl">
              <Loader size="sm" />
            </Center>
          ) : visible.length === 0 ? (
            <Text size="sm" c="dimmed" ta="center" py="xl">
              {scoped.length === 0
                ? effectiveScope === 'component'
                  ? 'No comments on this component yet.'
                  : 'No comments on this tab yet.'
                : 'No comments match these filters.'}
            </Text>
          ) : effectiveScope === 'component' ? (
            <Stack gap="sm">{renderThreads(visible)}</Stack>
          ) : (
            <Stack gap="md">
              {groups.map((g) => (
                <Box key={g.key}>
                  <Group justify="space-between" mb={6} wrap="nowrap">
                    {g.key !== TAB_GROUP && !g.removed ? (
                      <UnstyledButton
                        onClick={() => openComments(g.key)}
                        aria-label={`Show only ${g.label}`}
                        style={{ minWidth: 0 }}
                      >
                        <Group gap={6} wrap="nowrap">
                          <Icon icon={g.icon} width={14} />
                          <Text size="sm" fw={600} truncate>
                            {g.label}
                          </Text>
                        </Group>
                      </UnstyledButton>
                    ) : (
                      <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                        <Icon icon={g.icon} width={14} />
                        <Text size="sm" fw={600} c={g.removed ? 'dimmed' : undefined} truncate>
                          {g.label}
                        </Text>
                      </Group>
                    )}
                    <Badge size="xs" variant="light" color="gray">
                      {g.threads.length}
                    </Badge>
                  </Group>
                  <Stack gap="sm">{renderThreads(g.threads)}</Stack>
                </Box>
              ))}
            </Stack>
          )}
        </ScrollArea>
      </Stack>
    </Drawer>
  );
};

export default CommentsDrawer;
