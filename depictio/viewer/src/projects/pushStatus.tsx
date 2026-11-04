import React, { useState } from 'react';
import { Badge, Button, Group, Modal, PasswordInput, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { retryPush } from 'depictio-react-core';
import type { MigrationPush } from 'depictio-react-core';

import { useTone } from '../monitoring/useTone';

const PUSH_COLOR: Record<string, string> = {
  building: 'blue',
  uploading: 'blue',
  submitted: 'teal',
  failed: 'red',
};

const REMOTE_COLOR: Record<string, string> = {
  pending: 'yellow',
  importing: 'blue',
  imported: 'green',
  rejected: 'gray',
  failed: 'red',
  expired: 'gray',
  superseded: 'gray',
};

/** A push still moving: building or uploading here, or waiting on / running
 *  the import over there. Callers poll while any push is. */
export function isPushActive(p: MigrationPush): boolean {
  if (p.status === 'building' || p.status === 'uploading') return true;
  return (
    p.status === 'submitted' &&
    (p.remote_status === 'pending' || p.remote_status === 'importing' || !p.remote_status)
  );
}

/** Where the push went: its name, or its URL for an ad-hoc destination. */
export function pushDestinationLabel(p: MigrationPush): string {
  return p.target_name || p.target_url || '—';
}

/** Local status, plus the destination's status once the push is submitted. */
export const PushStatusBadges: React.FC<{ push: MigrationPush }> = ({ push }) => {
  const tone = useTone();
  return (
    <Group gap={6} wrap="nowrap" data-testid="push-badges">
      <Badge variant="light" size="sm" color={tone(PUSH_COLOR[push.status] ?? 'gray')}>
        {push.status}
      </Badge>
      {push.status === 'submitted' && push.remote_status && (
        <Badge variant="outline" size="sm" color={tone(REMOTE_COLOR[push.remote_status] ?? 'gray')}>
          {push.remote_status}
        </Badge>
      )}
    </Group>
  );
};

/** Outcome on the destination, once imported. */
export function pushResultLabel(p: MigrationPush): string | null {
  if (!p.remote_result) return null;
  return `${p.remote_result.locked ? 'Editing locked' : 'Editable'}${
    p.remote_result.made_public ? ', public' : ''
  }`;
}

/** Retry of a failed push. An ad-hoc push asks for the invite code again: the
 *  source never stores it. */
export const RetryPushButton: React.FC<{ push: MigrationPush; onRetried: () => void }> = ({
  push,
  onRetried,
}) => {
  const [asking, setAsking] = useState(false);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const adhoc = push.target_id === 'adhoc';

  if (push.status !== 'failed') return null;

  const run = async () => {
    setBusy(true);
    try {
      await retryPush(push.id, adhoc ? code.trim() : undefined);
      setAsking(false);
      setCode('');
      notifications.show({ message: 'Push started again.' });
      onRetried();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not retry',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button
        size="compact-xs"
        variant="light"
        loading={busy && !adhoc}
        onClick={() => (adhoc ? setAsking(true) : void run())}
        leftSection={<Icon icon="mdi:reload" width={14} />}
        data-testid="push-retry"
      >
        Retry
      </Button>
      <Modal
        opened={asking}
        onClose={() => {
          setAsking(false);
          setCode('');
        }}
        title="Retry the push"
        centered
        size="sm"
      >
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            Enter the invite code for {pushDestinationLabel(push)} again. It is never stored on
            this instance.
          </Text>
          <PasswordInput
            label="Invite code"
            value={code}
            onChange={(e) => setCode(e.currentTarget.value)}
            autoComplete="off"
            data-testid="push-retry-code"
          />
          <Group justify="flex-end">
            <Button variant="subtle" color="gray" onClick={() => setAsking(false)}>
              Cancel
            </Button>
            <Button
              loading={busy}
              disabled={code.trim() === ''}
              onClick={() => void run()}
              data-testid="push-retry-confirm"
            >
              Retry
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};
