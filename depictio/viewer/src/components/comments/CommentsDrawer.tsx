import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  Pill,
  ScrollArea,
  Stack,
  Tabs,
  Text,
  Textarea,
  ThemeIcon,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import {
  componentTypeVisual,
  createCommentThread,
  Z_LAYERS,
} from 'depictio-react-core';
import type {
  AnnotationStats,
  CommentThread,
  CommentThreadStatus,
  CommentViewState,
  InteractiveFilter,
  StoredMetadata,
} from 'depictio-react-core';

import { useUiStore } from '../../store/useUiStore';
import type { CommentsView } from '../../store/useUiStore';
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
  /** Every thread of the tab, owned by CommentsProvider (null while loading). */
  threads: CommentThread[] | null;
  /** What the charts measured of each annotation, keyed by thread id. */
  stats: Record<string, AnnotationStats>;
  loadError: string | null;
  /** Reloads the tab's threads (on opening, and from the error's Retry). */
  onReload: () => void | Promise<void>;
  onCreated: (thread: CommentThread) => void;
  onChanged: (thread: CommentThread) => void;
  onDeleted: (threadId: string) => void;
}

const STATUS_CHIPS: { value: StatusFilter; label: string; icon: string; color: string }[] = [
  { value: 'open', label: 'Open', icon: 'mdi:circle-outline', color: 'blue' },
  { value: 'resolved', label: 'Resolved', icon: 'mdi:check-circle-outline', color: 'teal' },
  { value: 'proposed', label: 'Proposed', icon: 'mdi:robot-outline', color: 'violet' },
];

interface ThreadGroup {
  key: string;
  label: string;
  icon: string;
  /** Accent of the component type (gray for the tab and removed components). */
  color: string;
  removed: boolean;
  threads: CommentThread[];
}

/** A group's header in the whole-tab list: clicking a live component's
 *  header narrows the drawer to it. Sticky, so the group stays named while
 *  its threads scroll. */
const GroupHeader: React.FC<{ group: ThreadGroup; onScope: (index: string) => void }> = ({
  group,
  onScope,
}) => {
  const [hovered, setHovered] = useState(false);
  const clickable = group.key !== TAB_GROUP && !group.removed;
  const content = (
    <Group gap="xs" wrap="nowrap" px={6} py={4}>
      <ThemeIcon variant="light" color={group.color} size="sm" radius="sm">
        <Icon icon={group.icon} width={14} />
      </ThemeIcon>
      <Text
        size="sm"
        fw={600}
        truncate
        c={group.removed ? 'dimmed' : undefined}
        style={{ flex: 1, minWidth: 0 }}
      >
        {group.label}
      </Text>
      {group.removed && (
        <Badge size="xs" variant="light" color="gray">
          removed
        </Badge>
      )}
      <Badge size="sm" variant="light" color="gray" circle>
        {group.threads.length}
      </Badge>
      {clickable && (
        <Text c="dimmed" component="span" style={{ display: 'flex', opacity: hovered ? 1 : 0.5 }}>
          <Icon icon="mdi:chevron-right" width={16} />
        </Text>
      )}
    </Group>
  );
  return (
    <Box
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 1,
        background: 'var(--mantine-color-body)',
      }}
      pb={6}
    >
      {clickable ? (
        <UnstyledButton
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          onClick={() => onScope(group.key)}
          aria-label={`Show only ${group.label}`}
          w="100%"
          style={{
            borderRadius: 'var(--mantine-radius-sm)',
            background: hovered ? 'var(--mantine-color-default-hover)' : undefined,
          }}
        >
          {content}
        </UnstyledButton>
      ) : (
        content
      )}
    </Box>
  );
};

const EmptyState: React.FC<{ icon: string; text: string }> = ({ icon, text }) => (
  <Center py="xl">
    <Stack gap="xs" align="center">
      <ThemeIcon variant="light" color="gray" size="xl" radius="xl">
        <Icon icon={icon} width={22} />
      </ThemeIcon>
      <Text size="sm" c="dimmed" ta="center">
        {text}
      </Text>
    </Stack>
  </Center>
);

/**
 * The comments side panel: one component's threads, or every thread on the
 * tab grouped by component, with a composer pinned to its foot that attaches
 * the current view. The header says what is listed (a component, or the whole
 * tab); tabs switch between plain comments and figure annotations.
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
  threads,
  stats,
  loadError,
  onReload,
  onCreated,
  onChanged,
  onDeleted,
}) => {
  const opened = useUiStore((s) => s.commentsOpen);
  const scope = useUiStore((s) => s.commentsScope);
  const componentIndex = useUiStore((s) => s.commentsComponentIndex);
  const focusedThreadId = useUiStore((s) => s.focusedThreadId);
  const closeComments = useUiStore((s) => s.closeComments);
  const setScope = useUiStore((s) => s.setCommentsScope);
  const openComments = useUiStore((s) => s.openComments);
  const setFocusedThread = useUiStore((s) => s.setFocusedThread);
  const view = useUiStore((s) => s.commentsView);
  const setView = useUiStore((s) => s.setCommentsView);
  const editingAnnotationId = useUiStore((s) => s.editingAnnotationThreadId);
  const scrollRequest = useUiStore((s) => s.threadScrollRequest);

  const [statuses, setStatuses] = useState<StatusFilter[]>(DEFAULT_STATUSES);
  const [draft, setDraft] = useState('');
  const [posting, setPosting] = useState(false);

  const metaByIndex = useMemo(() => {
    const m = new Map<string, StoredMetadata>();
    metadata.forEach((meta) => m.set(String(meta.index), meta));
    return m;
  }, [metadata]);

  // Every thread of the tab is reloaded on each opening (the provider holds
  // them for the annotation layer too); the component scope and the status
  // chips filter client-side, so switching them is instant.
  useEffect(() => {
    if (opened) void onReload();
  }, [opened, onReload]);

  const effectiveScope = scope === 'component' && componentIndex ? 'component' : 'tab';
  const targetIndex = effectiveScope === 'component' ? componentIndex : null;
  const targetMeta = targetIndex ? metaByIndex.get(targetIndex) : undefined;

  const inScope = useMemo(
    () =>
      (threads ?? []).filter(
        (t) => effectiveScope === 'tab' || t.anchor.component_index === componentIndex,
      ),
    [threads, effectiveScope, componentIndex],
  );

  // Figure annotations and plain comments are listed apart; the view counts
  // follow the scope and the status chips, like the list itself.
  const viewCounts = useMemo(() => {
    const c: Record<CommentsView, number> = { comments: 0, annotations: 0 };
    inScope.forEach((t) => {
      if ((statuses as string[]).includes(t.status)) c[t.annotation ? 'annotations' : 'comments'] += 1;
    });
    return c;
  }, [inScope, statuses]);

  const scoped = useMemo(
    () => inScope.filter((t) => Boolean(t.annotation) === (view === 'annotations')),
    [inScope, view],
  );

  // A thread focused from outside the drawer (an annotation badge on a chart)
  // switches to the view that lists it, once per focus so a later manual
  // switch sticks.
  const handledFocus = useRef<string | null>(null);
  useEffect(() => {
    if (!focusedThreadId) {
      handledFocus.current = null;
      return;
    }
    if (handledFocus.current === focusedThreadId) return;
    const thread = threads?.find((t) => t.id === focusedThreadId);
    if (!thread) return;
    handledFocus.current = focusedThreadId;
    setView(thread.annotation ? 'annotations' : 'comments');
  }, [focusedThreadId, threads, setView]);

  // An annotation opened for editing from a chart must not be hidden by the
  // status chips (a resolved one, say).
  useEffect(() => {
    if (!editingAnnotationId) return;
    const status = threads?.find((t) => t.id === editingAnnotationId)?.status;
    if (status && status !== 'rejected' && !statuses.includes(status as StatusFilter)) {
      setStatuses((prev) => [...prev, status as StatusFilter]);
    }
  }, [editingAnnotationId, threads, statuses]);

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
        return { key, label: 'Whole tab', icon: 'mdi:tab', color: 'gray', removed: false, threads: list };
      }
      const meta = metaByIndex.get(key);
      const fallbackTitle = list.find((t) => t.anchor.component_title)?.anchor.component_title;
      const visual = meta ? componentTypeVisual(meta.component_type) : null;
      return {
        key,
        label: meta ? componentLabel(meta, fallbackTitle) : fallbackTitle || 'Removed component',
        icon: visual ? visual.icon : 'mdi:puzzle-remove-outline',
        color: visual ? visual.color : 'gray',
        removed: !meta,
        threads: list,
      };
    });
  }, [visible, metadata, metaByIndex]);

  const viewState = useMemo(() => buildViewState(filters, targetIndex), [filters, targetIndex]);
  const attachHint = selectionHint(viewState.selection);

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
      onCreated(created);
      setDraft('');
      // Make sure the new thread is not hidden by the status chips.
      setStatuses((prev) =>
        prev.includes(created.status as StatusFilter) || created.status === 'rejected'
          ? prev
          : [...prev, created.status as StatusFilter],
      );
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
      if (idx && !focusComponent(idx, { flashClass: 'depictio-comment-flash', durationMs: 2800 })) {
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

  // A scroll request (an annotation clicked on a chart) is served once its
  // card is rendered: the drawer may still be opening or switching view.
  const scrollRef = useRef<HTMLDivElement>(null);
  const pendingScroll = useRef(0);
  useEffect(() => {
    if (scrollRequest) pendingScroll.current = scrollRequest;
  }, [scrollRequest]);
  useEffect(() => {
    if (!pendingScroll.current || !opened || !focusedThreadId) return;
    const frame = requestAnimationFrame(() => {
      const card = scrollRef.current?.querySelector<HTMLElement>(
        `[data-thread-id="${CSS.escape(focusedThreadId)}"]`,
      );
      if (!card) return;
      pendingScroll.current = 0;
      card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
    return () => cancelAnimationFrame(frame);
  }, [scrollRequest, opened, focusedThreadId, visible, view]);

  const renderThreads = (list: CommentThread[]) =>
    list.map((t) => (
      <ThreadCard
        key={t.id}
        thread={t}
        currentUser={currentUser}
        focused={t.id === focusedThreadId}
        stats={stats[t.id]}
        onFocus={focusThread}
        onChange={onChanged}
        onDeleted={onDeleted}
      />
    ));

  const noun = view === 'annotations' ? 'annotations' : 'comments';

  // How many components the tab's discussion touches, for the scope line.
  const componentsWithThreads = useMemo(
    () =>
      new Set(
        (threads ?? [])
          .filter((t) => t.status !== 'rejected' && t.anchor.component_index)
          .map((t) => t.anchor.component_index),
      ).size,
    [threads],
  );
  // The component the drawer was last narrowed to, offered back from the
  // whole-tab view.
  const lastMeta =
    effectiveScope === 'tab' && componentIndex ? metaByIndex.get(componentIndex) : undefined;
  const targetVisual = targetMeta ? componentTypeVisual(targetMeta.component_type) : null;
  const scopeLabel = targetIndex ? componentLabel(targetMeta, null) : 'the whole tab';

  const scopeLine =
    effectiveScope === 'component' ? (
      <Group gap={6} wrap="nowrap">
        <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
          On
        </Text>
        <Pill
          size="md"
          withRemoveButton
          onRemove={() => setScope('tab')}
          removeButtonProps={{ 'aria-label': 'Show the whole tab' }}
          style={{ minWidth: 0, maxWidth: '100%' }}
          data-testid="comments-scope-pill"
        >
          <Group gap={6} wrap="nowrap" component="span" style={{ minWidth: 0 }}>
            <Icon
              icon={targetVisual?.icon ?? 'mdi:puzzle-remove-outline'}
              width={14}
              style={{ flexShrink: 0, color: targetVisual?.color }}
            />
            <Text span size="xs" fw={500} truncate>
              {componentLabel(targetMeta, null)}
            </Text>
          </Group>
        </Pill>
      </Group>
    ) : (
      <Group gap={6} wrap="nowrap" justify="space-between">
        <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
          <Icon icon="mdi:tab" width={14} style={{ flexShrink: 0 }} />
          <Text size="xs" c="dimmed" truncate>
            Whole tab · {componentsWithThreads} component{componentsWithThreads === 1 ? '' : 's'}{' '}
            with threads
          </Text>
        </Group>
        {lastMeta && (
          <Button
            size="compact-xs"
            variant="subtle"
            color="gray"
            leftSection={<Icon icon="mdi:arrow-left" width={12} />}
            onClick={() => setScope('component')}
            style={{ flexShrink: 1, minWidth: 0 }}
          >
            <Text span size="xs" truncate>
              {componentLabel(lastMeta, null)}
            </Text>
          </Button>
        )}
      </Group>
    );

  const tabLabel = (value: CommentsView, label: string, icon: string) => (
    <Tabs.Tab
      value={value}
      leftSection={<Icon icon={icon} width={16} />}
      rightSection={
        <Badge size="sm" variant="light" circle color={view === value ? undefined : 'gray'}>
          {viewCounts[value]}
        </Badge>
      }
    >
      {label}
    </Tabs.Tab>
  );

  const statusFilter = (
    <Group gap={6} wrap="nowrap">
      <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
        Show
      </Text>
      <Chip.Group multiple value={statuses} onChange={(v) => setStatuses(v as StatusFilter[])}>
        <Group gap={4} wrap="wrap">
          {STATUS_CHIPS.map((c) => {
            const on = statuses.includes(c.value);
            const icon = <Icon icon={c.icon} width={12} />;
            // Checked chips show the status icon in place of Mantine's tick;
            // unchecked ones carry it inline, so every chip has exactly one.
            return (
              <Chip key={c.value} value={c.value} size="xs" variant="light" color={c.color} icon={icon}>
                <Group gap={4} wrap="nowrap" component="span">
                  {!on && icon}
                  <span>{c.label}</span>
                  {statusCounts[c.value] > 0 && (
                    <Text span size="xs" c="dimmed">
                      {statusCounts[c.value]}
                    </Text>
                  )}
                </Group>
              </Chip>
            );
          })}
        </Group>
      </Chip.Group>
    </Group>
  );

  const list = loadError ? (
    <Alert color="red" variant="light" title="Could not load comments">
      <Stack gap="xs">
        <Text size="xs">{loadError}</Text>
        <Button size="compact-xs" variant="light" color="red" onClick={() => void onReload()}>
          Retry
        </Button>
      </Stack>
    </Alert>
  ) : threads === null ? (
    <Center py="xl">
      <Loader size="sm" />
    </Center>
  ) : visible.length === 0 ? (
    scoped.length === 0 ? (
      <EmptyState
        icon={view === 'annotations' ? 'mdi:draw' : 'mdi:comment-outline'}
        text={`No ${noun} on this ${effectiveScope === 'component' ? 'component' : 'tab'} yet.`}
      />
    ) : (
      <EmptyState icon="mdi:filter-off-outline" text={`No ${noun} match these filters.`} />
    )
  ) : effectiveScope === 'component' ? (
    <Stack gap="sm">{renderThreads(visible)}</Stack>
  ) : (
    <Stack gap="md">
      {groups.map((g) => (
        <Box key={g.key}>
          <GroupHeader group={g} onScope={openComments} />
          <Stack gap="sm">{renderThreads(g.threads)}</Stack>
        </Box>
      ))}
    </Stack>
  );

  // Chat pattern: the composer stays at the bottom, the list scrolls above it.
  const footer =
    view === 'comments' ? (
      <Stack gap={6}>
        <Group gap={6} wrap="nowrap">
          <Icon
            icon={targetVisual?.icon ?? 'mdi:tab'}
            width={14}
            style={{ flexShrink: 0, color: targetVisual?.color }}
          />
          <Text size="xs" c="dimmed" truncate>
            Commenting on {scopeLabel}
          </Text>
        </Group>
        <Textarea
          size="sm"
          autosize
          minRows={2}
          maxRows={6}
          placeholder="Write a comment… (Ctrl+Enter to post)"
          value={draft}
          onChange={(e) => setDraft(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void post();
          }}
          maxLength={4000}
          aria-label="New comment"
        />
        <Group justify="space-between" wrap="nowrap" gap="xs">
          <Stack gap={0} style={{ minWidth: 0 }}>
            {attachHint && (
              <Group gap={4} wrap="nowrap">
                <Icon icon="mdi:selection-drag" width={12} style={{ flexShrink: 0 }} />
                <Text size="xs" c="dimmed" truncate>
                  {attachHint} will be attached
                </Text>
              </Group>
            )}
            {filters.length > 0 && (
              <Group gap={4} wrap="nowrap">
                <Icon icon="mdi:filter-outline" width={12} style={{ flexShrink: 0 }} />
                <Text size="xs" c="dimmed" truncate>
                  {filters.length} active filter{filters.length === 1 ? '' : 's'} will be attached
                </Text>
              </Group>
            )}
          </Stack>
          <Button
            size="xs"
            onClick={post}
            loading={posting}
            disabled={!draft.trim()}
            leftSection={<Icon icon="mdi:send" width={14} />}
            style={{ flexShrink: 0 }}
          >
            Post
          </Button>
        </Group>
      </Stack>
    ) : (
      <Group gap={6} wrap="nowrap" align="flex-start">
        <Icon icon="mdi:draw" width={14} style={{ flexShrink: 0, marginTop: 2 }} />
        <Text size="xs" c="dimmed">
          Annotations are created with the Annotate (draw) action on a chart or table.
        </Text>
      </Group>
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
        header: { paddingBottom: 'var(--mantine-spacing-xs)' },
        body: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', paddingTop: 0 },
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
        {scopeLine}

        <Tabs value={view} onChange={(v) => v && setView(v as CommentsView)}>
          <Tabs.List grow aria-label="Show comments or figure annotations">
            {tabLabel('comments', 'Comments', 'mdi:comment-text-outline')}
            {tabLabel('annotations', 'Annotations', 'mdi:draw')}
          </Tabs.List>
        </Tabs>

        {statusFilter}

        <ScrollArea
          style={{ flex: 1, minHeight: 0 }}
          offsetScrollbars
          type="auto"
          viewportRef={scrollRef}
        >
          {list}
        </ScrollArea>

        <Box
          pt="sm"
          style={{ borderTop: '1px solid var(--mantine-color-default-border)', flexShrink: 0 }}
        >
          {footer}
        </Box>
      </Stack>
    </Drawer>
  );
};

export default CommentsDrawer;
