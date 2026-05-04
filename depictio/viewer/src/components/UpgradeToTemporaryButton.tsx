import React, { useEffect, useState } from 'react';
import { Button, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { fetchAuthStatus } from 'depictio-react-core';
import type { AuthStatusResponse } from 'depictio-react-core';

import UpgradeToTemporaryModal from '../profile/UpgradeToTemporaryModal';

/** "Save my session" affordance for anonymous users on viewer / editor /
 *  dashboards routes. Visible only when the backend reports
 *  ``unauthenticated_mode === true`` AND the current user is anonymous AND
 *  not already temporary. Mirrors the in-Profile button at
 *  ``ProfileApp.tsx:91-92`` so the same workflow is reachable without
 *  navigating away from the dashboard. */
const UpgradeToTemporaryButton: React.FC = () => {
  const [opened, setOpened] = useState(false);
  const [status, setStatus] = useState<AuthStatusResponse | null>(null);
  const [user, setUser] = useState<{ is_anonymous?: boolean; is_temporary?: boolean } | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await fetchAuthStatus();
        if (cancelled) return;
        setStatus(s);
        // Read is_anonymous / is_temporary from the persisted session payload —
        // ``fetchAuthStatus`` only carries the ``user`` object, which doesn't
        // include those flags. The session payload does.
        try {
          const raw = localStorage.getItem('local-store');
          if (raw) {
            const parsed = JSON.parse(raw);
            if (parsed && typeof parsed === 'object') {
              setUser({
                is_anonymous: Boolean(parsed.is_anonymous),
                is_temporary: Boolean(parsed.is_temporary),
              });
            }
          }
        } catch {
          // ignore localStorage parse errors
        }
      } catch {
        // Non-fatal: button just won't render.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const visible =
    status?.unauthenticated_mode === true &&
    user?.is_anonymous === true &&
    user?.is_temporary !== true;

  if (!visible) return null;

  return (
    <>
      <Tooltip label="Create a 24-hour session so your changes persist" withArrow>
        <Button
          leftSection={<Icon icon="mdi:account-arrow-up" width={14} />}
          color="blue"
          variant="light"
          size="xs"
          onClick={() => setOpened(true)}
        >
          Save my session
        </Button>
      </Tooltip>
      <UpgradeToTemporaryModal opened={opened} onClose={() => setOpened(false)} />
    </>
  );
};

export default UpgradeToTemporaryButton;
