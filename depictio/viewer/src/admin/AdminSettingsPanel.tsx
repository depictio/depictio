import React, { useCallback, useEffect, useState } from 'react';
import {
  Anchor,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';

import {
  fetchVersionCheckAdmin,
  resetVersionCheckAdmin,
  runVersionCheckAdmin,
  updateVersionCheckAdmin,
} from 'depictio-react-core';
import type { VersionCheckAdmin } from 'depictio-react-core';

import {
  SectionAccordion,
  SettingsSection,
  SwitchField,
  useOpenSections,
} from '../components/settings/SettingsSections';
import { refreshServerInfo } from '../hooks/useServerInfo';
import { formatDateTimeVerbose, formatRelativeTime } from '../lib/datetime';
import { useCurrentUser } from '../hooks/useCurrentUser';

type Action = 'save' | 'reset' | 'check';

/** A read-only fact: label on the left, value on the right. */
const InfoRow: React.FC<{ label: string; testId?: string; children: React.ReactNode }> = ({
  label,
  testId,
  children,
}) => (
  <Group justify="space-between" wrap="nowrap" align="flex-start" data-testid={testId}>
    <Text size="sm" c="dimmed">
      {label}
    </Text>
    <Text size="sm" component="div" ta="right" style={{ wordBreak: 'break-word' }}>
      {children}
    </Text>
  </Group>
);

/**
 * Admin Settings tab: instance-wide settings in collapsible groups, each
 * saved with its own Save / Reset (the layout of the Branding tab). One group
 * for now, "Version check": whether this instance asks GitHub for new Depictio
 * releases, which feeds the update dot in the sidebar.
 *
 * The switch is a draft until Save; "Check now" and "Reset to default" act
 * immediately. Every successful action refreshes the shared server-info
 * store, so the sidebar dot follows without waiting for its own poll.
 */
const AdminSettingsPanel: React.FC = () => {
  const { isPublicMode, isDemoMode } = useCurrentUser();
  // Visible but read-only on a shared demo or public instance, whose
  // administrators must not change settings for every visitor.
  const readOnly = isPublicMode || isDemoMode;
  const readOnlyReason = 'Settings cannot be changed in public or demo mode.';

  const [openSections, setOpenSections] = useOpenSections('depictio-admin-settings-sections', [
    'version-check',
  ]);
  const [state, setState] = useState<VersionCheckAdmin | null>(null);
  const [draft, setDraft] = useState<boolean>(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<Action | null>(null);
  const [error, setError] = useState<string | null>(null);

  const adopt = useCallback((next: VersionCheckAdmin) => {
    setState(next);
    setDraft(next.enabled);
  }, []);

  useEffect(() => {
    fetchVersionCheckAdmin()
      .then(adopt)
      .catch((err) =>
        setError(err instanceof Error ? err.message : 'Failed to load the version check setting.'),
      )
      .finally(() => setLoading(false));
  }, [adopt]);

  const run = async (
    action: Action,
    call: () => Promise<VersionCheckAdmin>,
    success: string,
    failure: string,
  ) => {
    setBusy(action);
    try {
      const next = await call();
      // "Check now" must not snap an unsaved switch back to the saved value.
      if (action === 'check') setState(next);
      else adopt(next);
      // The sidebar's update dot reads the shared server-info store.
      await refreshServerInfo();
      notifications.show({ message: success });
    } catch (err) {
      notifications.show({
        message: err instanceof Error ? err.message : failure,
        color: 'red',
      });
    } finally {
      setBusy(null);
    }
  };

  const handleSave = () =>
    run(
      'save',
      () => updateVersionCheckAdmin(draft),
      draft ? 'Version check turned on.' : 'Version check turned off.',
      'Failed to save the version check setting.',
    );
  const handleReset = () =>
    run(
      'reset',
      resetVersionCheckAdmin,
      'Version check reset to its default.',
      'Failed to reset the version check setting.',
    );
  const handleCheck = () =>
    run('check', runVersionCheckAdmin, 'Version check done.', 'Failed to run the version check.');

  if (loading) {
    return (
      <Center mih={200}>
        <Loader />
      </Center>
    );
  }
  if (!state) {
    return (
      <Text c="red" size="sm" data-testid="admin-settings-error">
        {error ?? 'Failed to load the version check setting.'}
      </Text>
    );
  }

  const locked = state.locked_by_env;
  const unchanged = draft === state.enabled;
  const busyAny = busy !== null;

  // Why the setting cannot be edited at all; Save and Reset add their own.
  const frozenReason = readOnly
    ? readOnlyReason
    : locked
      ? 'Set by DEPICTIO_VERSION_CHECK_ENABLED'
      : null;
  const saveReason = frozenReason ?? (unchanged ? 'Nothing to save.' : null);
  const resetReason =
    frozenReason ??
    (state.override === null ? 'No override to remove: the default already applies.' : null);
  const checkReason = readOnly
    ? readOnlyReason
    : !state.enabled
      ? 'Turn the version check on and save first.'
      : null;

  return (
    <SectionAccordion
      value={openSections}
      onChange={setOpenSections}
      testId="admin-settings-sections"
    >
      <SettingsSection
        value="version-check"
        icon="mdi:update"
        title="Version check"
        subtitle="Notify administrators when a newer Depictio release is published on GitHub"
        testId="admin-settings-version-check"
      >
        <Stack gap="md">
          <Tooltip label={frozenReason} withArrow disabled={frozenReason === null}>
            <div>
              <SwitchField
                label="Check for new versions"
                description="The server asks GitHub for the latest release now and then. Nothing about this instance is sent."
                checked={draft}
                onChange={setDraft}
                disabled={readOnly || locked}
                testId="version-check-switch"
              />
            </div>
          </Tooltip>

          <Stack gap="xs">
            <InfoRow label="Checks every" testId="version-check-interval">
              {state.interval_hours} h
            </InfoRow>
            <InfoRow label="Repository" testId="version-check-repository">
              {state.repository}
            </InfoRow>
            <InfoRow label="Current version" testId="version-check-current">
              {state.current_version}
            </InfoRow>
            <InfoRow label="Latest release" testId="version-check-latest">
              {state.latest_version ? (
                <Group gap="xs" justify="flex-end" wrap="nowrap">
                  {state.update_available && (
                    <Badge size="sm" variant="light" color="green" data-testid="update-available">
                      Update available
                    </Badge>
                  )}
                  {state.release_url ? (
                    <Anchor href={state.release_url} target="_blank" rel="noopener noreferrer">
                      {state.latest_version}
                    </Anchor>
                  ) : (
                    state.latest_version
                  )}
                </Group>
              ) : (
                'Not checked yet'
              )}
            </InfoRow>
            <InfoRow label="Last check" testId="version-check-last">
              {state.checked_at ? (
                <Tooltip label={formatDateTimeVerbose(state.checked_at)} withArrow>
                  <span>{formatRelativeTime(state.checked_at)}</span>
                </Tooltip>
              ) : (
                'Never'
              )}
            </InfoRow>
            {state.last_error && (
              <InfoRow label="Last error" testId="version-check-error">
                <Text component="span" size="sm" c="red">
                  {state.last_error}
                </Text>
              </InfoRow>
            )}
          </Stack>

          <Group justify="space-between">
            <Group gap="xs">
              <Tooltip label={resetReason} withArrow disabled={resetReason === null}>
                <span>
                  <Button
                    variant="subtle"
                    color="red"
                    disabled={resetReason !== null || busyAny}
                    loading={busy === 'reset'}
                    onClick={handleReset}
                    leftSection={<Icon icon="mdi:restore" width={16} />}
                    data-testid="version-check-reset"
                  >
                    Reset to default
                  </Button>
                </span>
              </Tooltip>
              <Tooltip label={checkReason} withArrow disabled={checkReason === null}>
                <span>
                  <Button
                    variant="default"
                    disabled={checkReason !== null || (busyAny && busy !== 'check')}
                    loading={busy === 'check'}
                    onClick={handleCheck}
                    leftSection={<Icon icon="mdi:refresh" width={16} />}
                    data-testid="version-check-run"
                  >
                    Check now
                  </Button>
                </span>
              </Tooltip>
            </Group>
            <Tooltip label={saveReason} withArrow disabled={saveReason === null}>
              <span>
                <Button
                  disabled={saveReason !== null || (busyAny && busy !== 'save')}
                  loading={busy === 'save'}
                  onClick={handleSave}
                  leftSection={<Icon icon="mdi:content-save" width={16} />}
                  data-testid="version-check-save"
                >
                  Save
                </Button>
              </span>
            </Tooltip>
          </Group>
        </Stack>
      </SettingsSection>
    </SectionAccordion>
  );
};

export default AdminSettingsPanel;
