import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Button,
  Group,
  Indicator,
  Popover,
  ScrollArea,
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
import { FeedItem, facts, nameList } from '../changes/feed';
import {
  useProjectIngestionEvents,
  type IngestionFinishedPayload,
} from '../notifications/projectEvents';

const POLL_MS = 60_000;
const CHIPS_SHOWN = 3;

/** Where a notification leads: a project's Runs tab with the first new run in
 *  focus, or the dashboard (which draws its own marks). */
export function projectRunsHref(projectId: string, runTag?: string): string {
  const base = `/projects/${encodeURIComponent(projectId)}`;
  return runTag ? `${base}?tab=runs&run=${encodeURIComponent(runTag)}` : base;
}

export function itemHref(item: InboxItem): string {
  return item.scope_kind === 'project'
    ? projectRunsHref(item.scope_id, item.new_run_tags[0])
    : `/dashboard/${encodeURIComponent(item.scope_id)}`;
}

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

  const [items, setItems] = useState<InboxItem[]>([]);
  const [heldByServer, setHeldByServer] = useState(false);
  const [opened, setOpened] = useState(false);
  // dashboard id -> project id, for the dashboards the reader follows.
  const [dashboardProject, setDashboardProject] = useState<Record<string, string>>({});
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const dashboardProjectRef = useRef(dashboardProject);
  dashboardProjectRef.current = dashboardProject;
  const announced = useRef(new Set<string>());

  const refresh = useCallback(async () => {
    try {
      const inbox = await fetchChangesInbox();
      setItems(inbox.items);
      setHeldByServer(inbox.server_held);
    } catch {
      // keep what we have; the next tick retries
    }
  }, []);

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
    const ids = new Set<string>();
    for (const item of items) {
      if (item.scope_kind === 'project') ids.add(item.scope_id);
      else if (dashboardProject[item.scope_id]) ids.add(dashboardProject[item.scope_id]);
    }
    return [...ids];
  }, [items, dashboardProject]);

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
              <Button
                component="a"
                size="compact-xs"
                variant="light"
                href={projectRunsHref(event.project_id, event.run_tags[0])}
                data-testid="ingestion-toast-open-project"
              >
                Open project
              </Button>
              {marked && (
                <Button
                  component="a"
                  size="compact-xs"
                  variant="subtle"
                  href={`/dashboard/${encodeURIComponent(marked.scope_id)}`}
                  data-testid="ingestion-toast-open-dashboard"
                >
                  Open dashboard
                </Button>
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
      await Promise.allSettled(done.map(markItemSeen));
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
        <Group justify="space-between" wrap="nowrap" px={8} pt={4} pb={6}>
          <Text size="sm" fw={600}>
            Since your last visit
          </Text>
          {items.length > 0 && (
            <Button
              size="compact-xs"
              variant="subtle"
              leftSection={<Icon icon="tabler:checks" width={14} />}
              data-testid="notifications-done-all"
              onClick={() => void markSeen(items)}
            >
              Mark all as seen
            </Button>
          )}
        </Group>
        {items.length === 0 ? (
          <Text size="sm" c="dimmed" px="xs" py="sm">
            Nothing new.
          </Text>
        ) : (
          <ScrollArea.Autosize mah={360} type="auto" offsetScrollbars>
            <Stack gap={2}>
              {items.map((item) => (
                <NotificationRow
                  key={itemKey(item)}
                  item={item}
                  onDone={(i) => void markSeen([i])}
                />
              ))}
            </Stack>
          </ScrollArea.Autosize>
        )}
      </Popover.Dropdown>
    </Popover>
  );
};

export default NotificationsBell;
