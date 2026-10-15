import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Button,
  Center,
  CopyButton,
  Group,
  Modal,
  PasswordInput,
  Stack,
  Switch,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { adminCreateUser, fetchAuthStatus } from 'depictio-react-core';

import { useListingAccents } from '../lib/useListingAccents';

interface CreateUserModalProps {
  opened: boolean;
  onClose: () => void;
  /** Called once the account exists, so the caller can refresh its list. */
  onCreated: () => void;
}

const MIN_PASSWORD_LENGTH = 8;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
/** No look-alikes (0/O, 1/l/I): the admin reads this out or pastes it in a chat. */
const PASSWORD_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';

function generatePassword(length = 14): string {
  const bytes = new Uint32Array(length);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => PASSWORD_ALPHABET[b % PASSWORD_ALPHABET.length]).join('');
}

/** Admin → Users → Add user. The admin picks the starting password, the person
 *  replaces it at their first sign-in (their profile opens on the password
 *  form until they do). Same chrome as the other create dialogs. */
const CreateUserModal: React.FC<CreateUserModalProps> = ({ opened, onClose, onCreated }) => {
  const accent = useListingAccents('projects');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [mustChange, setMustChange] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [passwordLoginDisabled, setPasswordLoginDisabled] = useState(false);

  useEffect(() => {
    if (!opened) return;
    setEmail('');
    setDisplayName('');
    setPassword(generatePassword());
    setMustChange(true);
    setIsAdmin(false);
    setSubmitting(false);
    setError(null);
    let cancelled = false;
    fetchAuthStatus()
      .then((status) => {
        if (!cancelled) setPasswordLoginDisabled(Boolean(status.password_login_disabled));
      })
      .catch(() => {
        if (!cancelled) setPasswordLoginDisabled(false);
      });
    return () => {
      cancelled = true;
    };
  }, [opened]);

  const trimmedEmail = email.trim();
  const emailValid = EMAIL_PATTERN.test(trimmedEmail);
  const passwordValid = password.length >= MIN_PASSWORD_LENGTH;

  const handleClose = () => {
    if (!submitting) onClose();
  };

  const handleCreate = async () => {
    if (!emailValid || !passwordValid) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await adminCreateUser({
        email: trimmedEmail,
        password,
        display_name: displayName.trim() || undefined,
        is_admin: isAdmin,
        must_change_password: mustChange,
      });
      notifications.show({
        color: 'teal',
        title: 'User created',
        message: `${created.email} can sign in${mustChange ? ' and will be asked to choose a new password' : ''}.`,
        autoClose: 3500,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create the account');
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      centered
      size="md"
      withCloseButton
      closeOnClickOutside={false}
      closeOnEscape={!submitting}
      overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
      title={null}
      padding="lg"
    >
      <Stack gap="md" data-testid="create-user-modal">
        <Center>
          <Group gap="xs">
            <Icon
              icon="mdi:account-plus-outline"
              width={28}
              color={`var(--mantine-color-${accent.secondary}-6)`}
            />
            <Title
              order={2}
              c={accent.secondary}
              style={{ fontFamily: 'Virgil', fontWeight: 400 }}
            >
              New user
            </Title>
          </Group>
        </Center>

        {passwordLoginDisabled && (
          <Alert color="blue" variant="light" icon={<Icon icon="mdi:information-outline" />}>
            Password sign-in is disabled on this instance. This person signs in with single
            sign-on, which finds the account by email; the password below is not used.
          </Alert>
        )}

        <TextInput
          label="Email"
          description="The address they sign in with"
          placeholder="name@example.org"
          value={email}
          onChange={(e) => setEmail(e.currentTarget.value)}
          error={email.length > 0 && !emailValid ? 'Enter a valid email address' : null}
          required
          disabled={submitting}
          autoComplete="off"
          leftSection={<Icon icon="mdi:email-outline" width={16} />}
          data-autofocus
          data-testid="create-user-email"
        />
        <TextInput
          label="Display name (Optional)"
          placeholder="First Last"
          value={displayName}
          onChange={(e) => setDisplayName(e.currentTarget.value)}
          disabled={submitting}
          leftSection={<Icon icon="mdi:account-outline" width={16} />}
          data-testid="create-user-display-name"
        />
        <PasswordInput
          label="Initial password"
          description={`At least ${MIN_PASSWORD_LENGTH} characters. Give it to them yourself.`}
          value={password}
          onChange={(e) => setPassword(e.currentTarget.value)}
          error={
            password.length > 0 && !passwordValid
              ? `Use at least ${MIN_PASSWORD_LENGTH} characters`
              : null
          }
          required
          disabled={submitting}
          autoComplete="new-password"
          leftSection={<Icon icon="mdi:lock-outline" width={16} />}
          rightSectionWidth={64}
          rightSection={
            <Group gap={2} wrap="nowrap">
              <Tooltip label="Generate another" withArrow>
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  size="sm"
                  aria-label="Generate another password"
                  onClick={() => setPassword(generatePassword())}
                  disabled={submitting}
                >
                  <Icon icon="mdi:refresh" width={16} />
                </ActionIcon>
              </Tooltip>
              <CopyButton value={password} timeout={1500}>
                {({ copied, copy }) => (
                  <Tooltip label={copied ? 'Copied' : 'Copy'} withArrow>
                    <ActionIcon
                      variant="subtle"
                      color={copied ? 'teal' : 'gray'}
                      size="sm"
                      aria-label="Copy the password"
                      onClick={copy}
                    >
                      <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={16} />
                    </ActionIcon>
                  </Tooltip>
                )}
              </CopyButton>
            </Group>
          }
          data-testid="create-user-password"
        />
        <Switch
          label="Ask for a new password at first sign-in"
          description="Their profile opens on the password form until they choose their own."
          checked={mustChange}
          onChange={(e) => setMustChange(e.currentTarget.checked)}
          disabled={submitting}
          data-testid="create-user-must-change"
        />
        <Switch
          label="System admin"
          description="Full access to the admin pages."
          checked={isAdmin}
          onChange={(e) => setIsAdmin(e.currentTarget.checked)}
          disabled={submitting}
          data-testid="create-user-is-admin"
        />

        {error && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
            {error}
          </Alert>
        )}

        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            color={accent.secondary}
            leftSection={<Icon icon="mdi:plus" width={16} />}
            onClick={handleCreate}
            loading={submitting}
            disabled={!emailValid || !passwordValid}
            data-testid="create-user-submit"
          >
            Create user
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default CreateUserModal;
