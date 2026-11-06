import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Anchor, Button, CloseButton, Drawer, Group, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { listMigrationRequests } from 'depictio-react-core';
import type { MigrationRequestSummary } from 'depictio-react-core';

import { canSeeMigrations } from '../admin/access';
import { REQUEST_DRAWER_STYLES, RequestDetail } from '../admin/MigrationRequestDetail';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { useMigrationUi } from '../hooks/useMigrationUi';
import { formatDateTime } from '../lib/datetime';

const POLL_MS = 30_000;
const RECENT_DAYS = 7;
const MAX_ROWS = 3;
const DISMISSED_KEY = 'depictio-migration-banner-dismissed';

function readDismissed(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(DISMISSED_KEY) ?? '[]');
    return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

function writeDismissed(ids: string[]): void {
  try {
    localStorage.setItem(DISMISSED_KEY, JSON.stringify(ids.slice(-200)));
  } catch {
    /* storage unavailable: the banner just comes back */
  }
}

/** API timestamps are naive UTC: no offset on the wire. */
function ageDays(iso: string | undefined): number {
  if (!iso) return Infinity;
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isFinite(t) ? (Date.now() - t) / 86_400_000 : Infinity;
}

const sourceLabel = (r: MigrationRequestSummary) =>
  r.source_url || r.source_instance || r.source_name;

/**
 * Projects page, admins only: what other instances have sent here. Requests
 * that wait for a decision (or failed) stay until dealt with; an import that
 * went through shows for a week unless dismissed. A row opens the same request
 * sheet as Admin > Migrations, so approving needs no trip to the admin pages.
 * Absent while the instance hides migration or when there is nothing to say.
 */
export const MigrationRequestsBanner: React.FC = () => {
  const migrationUi = useMigrationUi();
  const { user, isPublicMode, isDemoMode, isSingleUserMode } = useCurrentUser();
  const allowed =
    migrationUi &&
    Boolean(user?.is_admin) &&
    canSeeMigrations({ user, isPublicMode, isDemoMode, isSingleUserMode });

  const [requests, setRequests] = useState<MigrationRequestSummary[]>([]);
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRequests(await listMigrationRequests());
    } catch {
      // Not an admin after all, or an older backend: nothing to show.
      setRequests([]);
    }
  }, []);

  useEffect(() => {
    if (!allowed) return undefined;
    void load();
    const t = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(t);
  }, [allowed, load]);

  const { waiting, failed, imported } = useMemo(
    () => ({
      waiting: requests.filter((r) => r.status === 'pending' || r.status === 'importing'),
      failed: requests.filter((r) => r.status === 'failed' && !dismissed.includes(r.id)),
      imported: requests.filter(
        (r) =>
          r.status === 'imported' &&
          !dismissed.includes(r.id) &&
          ageDays(r.updated_at) <= RECENT_DAYS,
      ),
    }),
    [requests, dismissed],
  );

  const dismiss = (id: string) => {
    const next = [...dismissed, id];
    setDismissed(next);
    writeDismissed(next);
  };

  if (!allowed || waiting.length + failed.length + imported.length === 0) return null;

  // Every row reserves the same slots, so the buttons line up whether or not a
  // row can be dismissed.
  const row = (r: MigrationRequestSummary, color: string, dismissable: boolean) => (
    <Group key={r.id} justify="space-between" wrap="nowrap" gap="md" data-testid="migration-banner-row">
      <Text size="sm" style={{ minWidth: 0 }} truncate>
        <b>{r.project_name}</b>
        <Text component="span" c="dimmed" size="sm">
          {' '}
          from {sourceLabel(r)} · {formatDateTime(r.updated_at)}
        </Text>
      </Text>
      <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
        <Button
          size="sm"
          radius="md"
          color={color}
          variant="light"
          fw={600}
          miw={116}
          // The glass theme paints light buttons from --gl-accent-soft / -fg:
          // pin them to the colour of the banner this button sits in.
          style={
            {
              '--button-bg': `var(--mantine-color-${color}-light)`,
              '--button-hover': `var(--mantine-color-${color}-light-hover)`,
              '--button-color': `var(--mantine-color-${color}-light-color)`,
              '--gl-accent-soft': `var(--mantine-color-${color}-light)`,
              '--gl-accent-fg': `var(--mantine-color-${color}-light-color)`,
            } as React.CSSProperties
          }
          leftSection={
            <Icon
              icon={r.status === 'pending' ? 'mdi:clipboard-check-outline' : 'mdi:text-box-search-outline'}
              width={17}
            />
          }
          onClick={() => setSelected(r.id)}
        >
          {r.status === 'pending' ? 'Review' : 'Details'}
        </Button>
        <div style={{ width: 28, display: 'flex', justifyContent: 'center' }}>
          {dismissable && (
            <CloseButton size="md" c={color} aria-label="Dismiss" onClick={() => dismiss(r.id)} />
          )}
        </div>
      </Group>
    </Group>
  );

  const block = (
    items: MigrationRequestSummary[],
    props: { color: string; icon: string; title: string; testId: string; dismissable: boolean },
  ) =>
    items.length === 0 ? null : (
      <Alert
        color={props.color}
        variant="light"
        icon={<Icon icon={props.icon} width={18} />}
        title={props.title}
        data-testid={props.testId}
      >
        <Stack gap={6}>
          {items.slice(0, MAX_ROWS).map((r) => row(r, props.color, props.dismissable))}
          {items.length > MAX_ROWS && (
            <Anchor href="/admin/migrations" size="xs">
              and {items.length - MAX_ROWS} more in Admin &gt; Migrations
            </Anchor>
          )}
        </Stack>
      </Alert>
    );

  return (
    <Stack gap="xs" mb="md" data-testid="migration-banner">
      {block(waiting, {
        color: 'yellow',
        icon: 'mdi:inbox-arrow-down',
        title:
          waiting.length === 1
            ? 'A project sent to this instance needs a decision'
            : `${waiting.length} projects sent to this instance need a decision`,
        testId: 'migration-banner-waiting',
        dismissable: false,
      })}
      {block(failed, {
        color: 'red',
        icon: 'mdi:alert-circle-outline',
        title: 'An import failed',
        testId: 'migration-banner-failed',
        dismissable: true,
      })}
      {block(imported, {
        color: 'teal',
        icon: 'mdi:check-circle-outline',
        title: imported.length === 1 ? 'A project was received' : 'Projects were received',
        testId: 'migration-banner-imported',
        dismissable: true,
      })}
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
            onChanged={() => void load()}
          />
        )}
      </Drawer>
    </Stack>
  );
};
