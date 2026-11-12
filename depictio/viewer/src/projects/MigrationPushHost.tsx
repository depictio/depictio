import React, { useCallback, useEffect, useState } from 'react';
import { Drawer } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { useMonitoringEvents } from 'depictio-react-core';
import type { MigrationLiveEvent } from 'depictio-react-core';

import { canSeeMigrations } from '../admin/access';
import { REQUEST_DRAWER_STYLES, RequestDetail } from '../admin/MigrationRequestDetail';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { useMigrationUi } from '../hooks/useMigrationUi';

/** The window event the host re-emits, so a list on the page can reload without
 *  opening a second socket of its own. */
const PUSH_EVENT = 'depictio:migration-push';

/** Runs `onPush` whenever an inbound migration request appears or changes
 *  status. Needs `MigrationPushHost` mounted (it is, at the app root). */
export function useMigrationPush(onPush: () => void): void {
  useEffect(() => {
    const listener = () => onPush();
    window.addEventListener(PUSH_EVENT, listener);
    return () => window.removeEventListener(PUSH_EVENT, listener);
  }, [onPush]);
}

/** What each pushed status says. The icons and colours are the Projects banners'. */
const TOASTS: Record<string, { title: string; icon: string; color: string; action: string }> = {
  pending: {
    title: 'A project needs a decision',
    icon: 'mdi:inbox-arrow-down',
    color: 'yellow',
    action: 'click to review',
  },
  imported: {
    title: 'A project was received',
    icon: 'mdi:check-circle-outline',
    color: 'green',
    action: 'click for details',
  },
  failed: {
    title: 'An import failed',
    icon: 'mdi:alert-circle-outline',
    color: 'red',
    action: 'click for details',
  },
};

/**
 * App-root host for the live push of received projects, admins only. It owns the
 * one socket, raises the toast wherever the admin is (Dashboards, Admin, the
 * editor...), and opens the request in a sheet when the toast is clicked, so no
 * trip to another page is needed. Pages that list requests reload through
 * `useMigrationPush`. Absent while the instance hides migration.
 */
export const MigrationPushHost: React.FC = () => {
  const migrationUi = useMigrationUi();
  const { user, isPublicMode, isDemoMode, isSingleUserMode } = useCurrentUser();
  const allowed =
    migrationUi &&
    Boolean(user?.is_admin) &&
    canSeeMigrations({ user, isPublicMode, isDemoMode, isSingleUserMode });

  const [selected, setSelected] = useState<string | null>(null);

  const onMigrationEvent = useCallback((event: MigrationLiveEvent) => {
    window.dispatchEvent(new CustomEvent(PUSH_EVENT, { detail: event.payload }));
    const { request_id: id, status, project_name: name, source } = event.payload ?? {};
    const toast = status ? TOASTS[status] : undefined;
    if (!id || !toast) return;
    const toastId = `migration-${id}-${status}`;
    notifications.show({
      id: toastId,
      color: toast.color,
      icon: <Icon icon={toast.icon} width={18} />,
      title: toast.title,
      message: `${name ?? 'A project'}${source ? ` from ${source}` : ''} · ${toast.action}`,
      style: { cursor: 'pointer' },
      onClick: () => {
        notifications.hide(toastId);
        setSelected(id);
      },
    });
  }, []);

  useMonitoringEvents({ enabled: allowed, onMigrationEvent });

  if (!allowed) return null;
  return (
    <Drawer
      opened={selected !== null}
      onClose={() => setSelected(null)}
      position="right"
      size="lg"
      title="Migration request"
      styles={REQUEST_DRAWER_STYLES}
    >
      {selected && (
        <RequestDetail
          requestId={selected}
          onClose={() => setSelected(null)}
          // An approval or a rejection from the sheet: lists on the page reload.
          onChanged={() => window.dispatchEvent(new CustomEvent(PUSH_EVENT))}
        />
      )}
    </Drawer>
  );
};
