import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Anchor,
  Button,
  Group,
  Indicator,
  Popover,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import {
  fetchAllDashboards,
  fetchChangesInbox,
  markDashboardSeen,
  markProjectSeen,
  type InboxItem,
} from 'depictio-react-core';

import { useChangesSinceEnabled } from '../hooks/useChangesSinceEnabled';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { FeedHeader, FeedItem, FeedMarkSeen, FeedScroll, facts, nameList } from '../changes/feed';
import { projectRunsHref } from '../changes/describe';
import {
  useProjectIngestionEvents,
  type IngestionFinishedPayload,
} from '../notifications/projectEvents';

const POLL_MS = 60_000;
const CHIPS_SHOWN = 3;

/** Where a notification leads: a project's Runs tab with the first new run in
 *  focus, or the dashboard (which draws its own marks). */
export function itemHref(item: InboxItem): string {
  return item.scope_kind === 'project'
    ? projectRunsHref(item.scope_id, item.new_run_tags[0])
    : `/dashboard/${encodeURIComponent(item.scope_id)}`;
}

/** The browser's own notifications (the system's notification centre). */
type DesktopPermission = NotificationPermission | 'unsupported';

function desktopPermission(): DesktopPermission {
  return typeof window !== 'undefined' && 'Notification' in window
    ? Notification.permission
    : 'unsupported';
}

/** A system notification when this tab is not in front: the toast already
 *  says it to a reader looking at the page. One per `tag`, whatever the
 *  number of open tabs. */
function showDesktopNotification(title: string, body: string, tag: string, href: string): void {
  if (desktopPermission() !== 'granted') return;
  if (!document.hidden && document.hasFocus()) return;
  try {
    const note = new Notification(title, { body, tag, icon: '/favicon.ico' });
    note.onclick = () => {
      window.focus();
      window.location.href = href;
      note.close();
    };
  } catch {
    // Some browsers only allow notifications from a service worker: the toast stays.
  }
}

/** The inbox as last read in this tab, so the bell paints its count at once
 *  on the next page instead of after the round trips (every tab is a page). */
interface CachedInbox {
  items: InboxItem[];
  server_held: boolean;
  followed: string[];
}

const inboxCacheKey = (userId: string) => `depictio-inbox:${userId}`;

function readCachedInbox(userId: string | null): CachedInbox | null {
  if (!userId) return null;
  try {
    const raw = window.sessionStorage.getItem(inboxCacheKey(userId));
    return raw ? (JSON.parse(raw) as CachedInbox) : null;
  } catch {
    return null;
  }
}

function writeCachedInbox(userId: string | null, inbox: CachedInbox): void {
  if (!userId) return;
  try {
    window.sessionStorage.setItem(inboxCacheKey(userId), JSON.stringify(inbox));
  } catch {
    // storage full or blocked: the next page waits for the inbox, as before
  }
}

/** What an item says, to tell a poll that brought news from one that did not. */
const itemSignature = (item: InboxItem) =>
  [item.new_run_tags.join(','), item.refreshed.join(','), item.dashboard_versions, item.at ?? ''].join('|');

/** A live ingestion toast stands for this long: a poll naming the same project
 *  within it does not toast again. */
const LIVE_COVERS_MS = 5 * 60_000;

const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? '' : 's'}`;

const itemKey = (item: InboxItem) => `${item.scope_kind}:${item.scope_id}`;

/** Moves the reader's mark on that dashboard or project, as its own
 *  "Mark as seen" does: a mark, never a dashboard version. */
function markItemSeen(item: InboxItem): Promise<unknown> {
  return item.scope_kind === 'project'
    ? markProjectSeen(item.scope_id)
    : markDashboardSeen(item.scope_id);
}

const NotificationRow: React.FC<{ item: InboxItem; onDone: (item: InboxItem) => void }> = ({
  item,
  onDone,
}) => {
  const runs = item.new_run_tags;
  return (
    <Group gap={4} wrap="nowrap" align="flex-start">
      <div style={{ flex: 1, minWidth: 0 }}>
        <FeedItem
          kind={item.scope_kind === 'project' ? 'project' : 'dashboard'}
          title={item.title || (item.scope_kind === 'project' ? 'Project' : 'Dashboard')}
          summary={facts(
            runs.length ? `${plural(runs.length, 'new run')}: ${nameList(runs, CHIPS_SHOWN)}` : null,
            item.dashboard_versions > 0 ? plural(item.dashboard_versions, 'dashboard change') : null,
            item.refreshed.length > 0 ? `${nameList(item.refreshed, CHIPS_SHOWN)} refreshed` : null,
          )}
          at={item.at}
          href={itemHref(item)}
          data-testid="notification-item"
          data-scope-kind={item.scope_kind}
          data-scope-id={item.scope_id}
        />
      </div>
      <Tooltip label="Mark as seen" withinPortal>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="sm"
          mt={6}
          aria-label={`Mark ${item.title || item.scope_kind} as seen`}
          data-testid="notification-done"
          onClick={() => onDone(item)}
        >
          <Icon icon="tabler:check" width={16} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );
};

/**
 * The bell of a signed-in reader: what is new in the dashboards and projects
 * they follow (new runs, refreshed collections, dashboard changes), counted on
 * the icon and listed in a popover. Polls the inbox every minute while the tab
 * is visible, and listens for live "ingestion finished" events on the projects
 * involved to show a toast. Renders nothing while the feature is off, for
 * anonymous or temporary readers, and where the server holds no marks.
 */
export interface BellTriggerProps {
  count: number;
  label: string;
  onClick: () => void;
}

interface NotificationsBellProps {
  /** Where the panel opens, from the bell. */
  position?: 'right-end' | 'bottom-end';
  /** A shell's own button (the glass top keys); the default is a Mantine ActionIcon. */
  renderTrigger?: (props: BellTriggerProps) => React.ReactElement;
}

const NotificationsBell: React.FC<NotificationsBellProps> = ({
  position = 'right-end',
  renderTrigger,
}) => {
  const enabledByServer = useChangesSinceEnabled();
  const { user } = useCurrentUser();
  const eligible = enabledByServer && Boolean(user) && !user?.is_temporary;

  const userId = user && !user.is_temporary ? (user.id ?? user.email) : null;
  const [items, setItems] = useState<InboxItem[]>([]);
  const [heldByServer, setHeldByServer] = useState(false);
  const [followed, setFollowed] = useState<string[]>([]);
  const [desktop, setDesktop] = useState<DesktopPermission>(desktopPermission);
  const [opened, setOpened] = useState(false);
  // dashboard id -> project id, for the dashboards the reader follows.
  const [dashboardProject, setDashboardProject] = useState<Record<string, string>>({});
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const dashboardProjectRef = useRef(dashboardProject);
  dashboardProjectRef.current = dashboardProject;
  const announced = useRef(new Set<string>());
  // project id -> when a live toast named it.
  const liveAt = useRef(new Map<string, number>());
  // What the last read said, per item; null until the first read of this page,
  // which is only a baseline: what it holds was there before the page opened.
  const signatures = useRef<Map<string, string> | null>(null);

  const announcePolled = useCallback((item: InboxItem) => {
    const project =
      item.scope_kind === 'project' ? item.scope_id : dashboardProjectRef.current[item.scope_id];
    const live = project ? liveAt.current.get(project) : undefined;
    if (live != null && Date.now() - live < LIVE_COVERS_MS) return;
    const title = `New in ${item.title || (item.scope_kind === 'project' ? 'a project' : 'a dashboard')}`;
    const runs = item.new_run_tags;
    const body = facts(
      runs.length ? `${plural(runs.length, 'new run')}: ${nameList(runs, CHIPS_SHOWN)}` : null,
      item.dashboard_versions > 0 ? plural(item.dashboard_versions, 'dashboard change') : null,
      item.refreshed.length > 0 ? `${nameList(item.refreshed, CHIPS_SHOWN)} refreshed` : null,
    );
    const href = itemHref(item);
    showDesktopNotification(title, body, `inbox-${itemKey(item)}`, href);
    notifications.show({
      id: `inbox-${itemKey(item)}-${itemSignature(item)}`,
      title,
      autoClose: 20_000,
      message: (
        <Stack gap={4} data-testid="inbox-toast">
          {body && (
            <Text size="xs" c="dimmed">
              {body}
            </Text>
          )}
          <Anchor href={href} size="xs" data-testid="inbox-toast-open">
            {item.scope_kind === 'project' ? 'Open project' : 'Open dashboard'}
          </Anchor>
        </Stack>
      ),
    });
  }, []);

  const refresh = useCallback(async () => {
    try {
      const inbox = await fetchChangesInbox();
      const previous = signatures.current;
      const next = new Map(inbox.items.map((i) => [itemKey(i), itemSignature(i)]));
      if (previous) {
        for (const item of inbox.items) {
          if (previous.get(itemKey(item)) !== next.get(itemKey(item))) announcePolled(item);
        }
      }
      signatures.current = next;
      setItems(inbox.items);
      const followedIds = inbox.followed_project_ids ?? [];
      setHeldByServer(inbox.server_held);
      setFollowed(followedIds);
      writeCachedInbox(userId, {
        items: inbox.items,
        server_held: inbox.server_held,
        followed: followedIds,
      });
    } catch {
      // keep what we have; the next tick retries
    }
  }, [announcePolled, userId]);

  // The last page's inbox, until this page's first read replaces it.
  useEffect(() => {
    if (!eligible || signatures.current) return;
    const cached = readCachedInbox(userId);
    if (!cached) return;
    setItems(cached.items);
    setHeldByServer(cached.server_held);
    setFollowed(cached.followed);
  }, [eligible, userId]);

  useEffect(() => {
    if (!eligible) return undefined;
    void refresh();
    const tick = () => {
      if (!document.hidden) void refresh();
    };
    const timer = window.setInterval(tick, POLL_MS);
    document.addEventListener('visibilitychange', tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [eligible, refresh]);

  // The inbox names dashboards, not their projects; one listing resolves them.
  const dashboardIds = items.filter((i) => i.scope_kind === 'dashboard').map((i) => i.scope_id);
  const unresolved = dashboardIds.some((id) => !(id in dashboardProject));
  useEffect(() => {
    if (!eligible || !unresolved) return undefined;
    let cancelled = false;
    fetchAllDashboards()
      .then((all) => {
        if (cancelled) return;
        const map: Record<string, string> = {};
        for (const d of all) if (d.project_id) map[d.dashboard_id] = String(d.project_id);
        setDashboardProject((prev) => ({ ...prev, ...map }));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [eligible, unresolved]);

  const projectIds = useMemo(() => {
    // Every project the reader follows, news or not: right after a visit the
    // inbox is empty, and the next ingestion must still be heard.
    const ids = new Set<string>(followed);
    for (const item of items) {
      if (item.scope_kind === 'project') ids.add(item.scope_id);
      else if (dashboardProject[item.scope_id]) ids.add(dashboardProject[item.scope_id]);
    }
    return [...ids];
  }, [items, dashboardProject, followed]);

  const onFinished = useCallback(
    (event: IngestionFinishedPayload) => {
      if (announced.current.has(event.run_id)) return;
      announced.current.add(event.run_id);
      const name = event.project_name || 'a project';
      const labels = event.run_tags.length > 0 ? event.run_tags : event.collections;
      const marked = itemsRef.current.find(
        (i) =>
          i.scope_kind === 'dashboard' &&
          dashboardProjectRef.current[i.scope_id] === event.project_id,
      );
      liveAt.current.set(event.project_id, Date.now());
      const href = projectRunsHref(event.project_id, event.run_tags[0]);
      showDesktopNotification(
        `New data in ${name}`,
        labels.length > 0 ? nameList(labels, CHIPS_SHOWN) : 'An ingestion finished.',
        `ingestion-${event.run_id}`,
        href,
      );
      notifications.show({
        id: `ingestion-${event.run_id}`,
        title: `New data in ${name}`,
        autoClose: 20_000,
        message: (
          <Stack gap="xs" data-testid="ingestion-toast">
            {labels.length > 0 && (
              <Text size="xs" c="dimmed">
                {nameList(labels, CHIPS_SHOWN)}
              </Text>
            )}
            <Group gap="xs">
              <Anchor href={href} size="xs" data-testid="ingestion-toast-open-project">
                Open project
              </Anchor>
              {marked && (
                <Anchor
                  href={`/dashboard/${encodeURIComponent(marked.scope_id)}`}
                  size="xs"
                  data-testid="ingestion-toast-open-dashboard"
                >
                  Open dashboard
                </Anchor>
              )}
            </Group>
          </Stack>
        ),
      });
      void refresh();
    },
    [refresh],
  );

  useProjectIngestionEvents(projectIds, onFinished, eligible && heldByServer);

  // Done, one item or all: the row leaves at once, the inbox is then re-read
  // (a failed write brings it back).
  const markSeen = useCallback(
    async (done: InboxItem[]) => {
      const keys = new Set(done.map(itemKey));
      setItems((prev) => prev.filter((i) => !keys.has(itemKey(i))));
      const results = await Promise.allSettled(done.map(markItemSeen));
      const failed = done.filter((_, i) => {
        const r = results[i];
        return (
          r.status === 'rejected' ||
          (r.value as { persisted?: boolean } | undefined)?.persisted === false
        );
      });
      if (failed.length > 0) {
        // Back in the list, whatever the re-read below does: they are not marked.
        setItems((prev) => {
          const shown = new Set(prev.map(itemKey));
          return [...prev, ...failed.filter((i) => !shown.has(itemKey(i)))];
        });
        notifications.show({
          color: 'red',
          title: 'Could not mark as seen',
          message: failed.map((i) => i.title || i.scope_kind).join(', '),
        });
        console.error('Mark as seen failed', results);
      }
      void refresh();
    },
    [refresh],
  );

  if (!eligible || !heldByServer) return null;

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position={position}
      width={340}
      shadow="md"
      withArrow
    >
      <Popover.Target>
        {(() => {
          const label = items.length > 0 ? `Notifications, ${items.length} new` : 'Notifications';
          const onClick = () => {
            setOpened((o) => !o);
            void refresh();
          };
          if (renderTrigger) {
            return (
              <Indicator
                label={<span data-testid="notifications-count">{items.length}</span>}
                size={16}
                disabled={items.length === 0}
                offset={4}
              >
                {renderTrigger({ count: items.length, label, onClick })}
              </Indicator>
            );
          }
          return (
            <Indicator
              label={<span data-testid="notifications-count">{items.length}</span>}
              size={16}
              disabled={items.length === 0}
              offset={4}
            >
              <ActionIcon
                variant="subtle"
                color="gray"
                size="lg"
                aria-label={label}
                data-testid="notifications-bell"
                onClick={onClick}
              >
                <Icon icon="mdi:bell-outline" width={22} />
              </ActionIcon>
            </Indicator>
          );
        })()}
      </Popover.Target>
      <Popover.Dropdown data-testid="notifications-panel" p="xs">
        <Stack pt={4} pb={6}>
          <FeedHeader
            title="Since your last visit"
            action={
              items.length > 0 && (
                <FeedMarkSeen
                  label="Mark all as seen"
                  onClick={() => void markSeen(items)}
                  testId="notifications-done-all"
                />
              )
            }
          />
        </Stack>
        {desktop === 'default' && (
          <Button
            size="compact-xs"
            variant="light"
            mx={8}
            mb={6}
            leftSection={<Icon icon="tabler:bell-ringing" width={14} />}
            data-testid="notifications-enable-desktop"
            onClick={() => {
              void Notification.requestPermission().then(setDesktop);
            }}
          >
            Enable desktop alerts
          </Button>
        )}
        {desktop === 'denied' && (
          <Text size="xs" c="dimmed" px={8} pb={6}>
            Desktop alerts are blocked for this site in the browser settings.
          </Text>
        )}
        {items.length === 0 ? (
          <Text size="sm" c="dimmed" px="xs" py="sm">
            Nothing new.
          </Text>
        ) : (
          <FeedScroll mah={360}>
            <Stack gap={2}>
              {items.map((item) => (
                <NotificationRow
                  key={itemKey(item)}
                  item={item}
                  onDone={(i) => void markSeen([i])}
                />
              ))}
            </Stack>
          </FeedScroll>
        )}
      </Popover.Dropdown>
    </Popover>
  );
};

export default NotificationsBell;
