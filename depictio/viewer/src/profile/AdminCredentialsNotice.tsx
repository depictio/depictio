import React, { useState } from 'react';
import { Affix, Anchor, Notification, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { shouldSuppressWalkthrough } from '../coach/availability';
import { WELCOME_ROUTE } from '../coach/chapters';
import { useCurrentUser } from '../hooks/useCurrentUser';

const DISMISSED_KEY = 'depictio:admin-credentials-notice:dismissed';

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISSED_KEY) === '1';
  } catch {
    return false;
  }
}

function writeDismissed(): void {
  try {
    window.localStorage.setItem(DISMISSED_KEY, '1');
  } catch {
    // Storage blocked: the notice comes back next visit, which is harmless.
  }
}

/**
 * Single-user mode, while the default admin still has the password nobody
 * knows: a dismissible reminder on the dashboards and projects lists to choose
 * an email and a password, which is what signs in if the instance goes public.
 * Gone for good once the credentials are set; dismissed per browser. Follows
 * the coach's gates, so screenshots and the e2e suite never catch it.
 */
const AdminCredentialsNotice: React.FC = () => {
  const { user, isSingleUserMode, isDevMode, walkthroughDisabled, loading } = useCurrentUser();
  const [dismissed, setDismissed] = useState(readDismissed);

  if (
    loading ||
    dismissed ||
    !isSingleUserMode ||
    !user?.is_admin ||
    user.credentials_claimed ||
    !WELCOME_ROUTE.test(window.location.pathname) ||
    shouldSuppressWalkthrough(isDevMode, walkthroughDisabled)
  ) {
    return null;
  }

  return (
    <Affix position={{ bottom: 20, left: 20 }} zIndex={300}>
      <Notification
        icon={<Icon icon="mdi:shield-account-outline" width={18} />}
        title="Set your admin email and password"
        onClose={() => {
          writeDismissed();
          setDismissed(true);
        }}
        closeButtonProps={{ 'aria-label': 'Dismiss' }}
        maw={360}
        withBorder
        data-testid="admin-credentials-notice"
      >
        <Text size="sm">
          This instance signs you in without one. If it is ever switched to public mode, the
          sign-in form will need them.{' '}
          <Anchor href="/profile#password" size="sm">
            Set them now
          </Anchor>
        </Text>
      </Notification>
    </Affix>
  );
};

export default AdminCredentialsNotice;
