import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Code,
  Group,
  Modal,
  ScrollArea,
  Stack,
  Text,
  ThemeIcon,
} from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import '@mantine/code-highlight/styles.css';
import { Icon } from '@iconify/react';
import yaml from 'js-yaml';

import type { CliAgentConfig } from 'depictio-react-core';

import { SectionHeader } from '../components/settings/SettingsSections';

/** Where the CLI looks for its configuration when no `--server` is given. */
const DEFAULT_CONFIG_PATH = '~/.depictio/CLI.yaml';

/** Copy text to clipboard with a fallback for non-secure contexts.
 *  navigator.clipboard requires a secure origin (HTTPS or localhost). When
 *  the SPA is served over an IP like 0.0.0.0:8055 the API is unavailable
 *  and Mantine's built-in copy button silently fails — this fallback uses
 *  the legacy execCommand path so the button works regardless of origin. */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

function downloadText(text: string, filename: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/x-yaml' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** "laptop · valid until 2027-10-12", from the token the config carries. */
function summaryOf(config: CliAgentConfig): string | undefined {
  const user = config.user as { token?: { name?: unknown; expire_datetime?: unknown } } | undefined;
  const name = typeof user?.token?.name === 'string' ? user.token.name : null;
  const expires =
    typeof user?.token?.expire_datetime === 'string' ? user.token.expire_datetime.slice(0, 10) : null;
  const parts = [name, expires && `valid until ${expires}`].filter(Boolean);
  return parts.length ? parts.join(' · ') : undefined;
}

/** A bordered, rounded frame around a code block. */
const CodeFrame: React.FC<{ children: React.ReactNode; 'data-testid'?: string }> = ({
  children,
  ...rest
}) => (
  <Box
    bd="1px solid var(--mantine-color-default-border)"
    style={{ borderRadius: 'var(--mantine-radius-md)', overflow: 'hidden' }}
    {...rest}
  >
    {children}
  </Box>
);

const Step: React.FC<{
  n: number;
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}> = ({ n, title, description, actions, children }) => (
  <Stack gap="xs">
    <Group justify="space-between" wrap="nowrap" align="center">
      <Group gap="sm" wrap="nowrap">
        <ThemeIcon variant="light" radius="xl" size={26} fz="xs" fw={700}>
          {n}
        </ThemeIcon>
        <Stack gap={0}>
          <Text size="sm" fw={600}>
            {title}
          </Text>
          {description && (
            <Text size="xs" c="dimmed">
              {description}
            </Text>
          )}
        </Stack>
      </Group>
      {actions}
    </Group>
    {/* Under the title, past the number. */}
    <Box pl={38}>{children}</Box>
  </Stack>
);

interface DisplayTokenModalProps {
  opened: boolean;
  onClose: () => void;
  /** YAML-serialisable config returned by /auth/generate_agent_config.
   *  When `null`, the modal renders an "unavailable" alert. */
  config: CliAgentConfig | null;
}

/** Shows a new CLI configuration, once: save it, then check the connection. */
const DisplayTokenModal: React.FC<DisplayTokenModalProps> = ({ opened, onClose, config }) => {
  const yamlText = config ? yaml.dump(config, { lineWidth: 120 }) : '';
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const ok = await copyText(yamlText);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      centered
      size="lg"
      title={
        <SectionHeader
          icon="mdi:check-circle-outline"
          color="green"
          title="Configuration created"
          subtitle={config ? summaryOf(config) : undefined}
        />
      }
    >
      <Stack gap="lg">
        {!config ? (
          <Alert
            color="yellow"
            variant="light"
            icon={<Icon icon="mdi:alert" width={18} />}
            title="CLI configuration unavailable"
          >
            Your token was created but the CLI configuration could not be retrieved.
            Please contact an administrator.
          </Alert>
        ) : (
          <>
            <Alert color="yellow" variant="light" icon={<Icon icon="mdi:eye-off-outline" width={18} />}>
              Shown only once. It signs the CLI in as you: keep it private.
            </Alert>

            <Step
              n={1}
              title="Save it"
              description={
                <>
                  As <Code>{DEFAULT_CONFIG_PATH}</Code>, the CLI&apos;s default
                </>
              }
              actions={
                <Group gap="xs" wrap="nowrap">
                  <Button
                    size="xs"
                    variant="default"
                    leftSection={<Icon icon="mdi:download" width={16} />}
                    onClick={() => downloadText(yamlText, 'CLI.yaml')}
                  >
                    Download
                  </Button>
                  <Button
                    size="xs"
                    variant="default"
                    leftSection={
                      <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={16} />
                    }
                    onClick={handleCopy}
                  >
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                </Group>
              }
            >
              {/* Mantine's built-in copy button uses navigator.clipboard, which
                  only works in secure contexts: the Copy button above falls back
                  to document.execCommand('copy'). */}
              <CodeFrame data-testid="agent-config-yaml">
                <ScrollArea.Autosize mah={220} type="auto">
                  <CodeHighlight code={yamlText} language="yaml" withCopyButton={false} />
                </ScrollArea.Autosize>
              </CodeFrame>
            </Step>

            <Step n={2} title="Check the connection" description="From the machine you saved it on">
              <CodeFrame>
                <CodeHighlight code="depictio config check" language="bash" withCopyButton={false} />
              </CodeFrame>
            </Step>
          </>
        )}

        <Group justify="flex-end">
          <Button onClick={onClose} data-testid="cli-config-done-btn">
            Done
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default DisplayTokenModal;
