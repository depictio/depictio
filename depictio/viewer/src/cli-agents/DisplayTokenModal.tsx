import React, { useState } from 'react';
import { Alert, Button, Code, Group, Modal, Stack, Title } from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import '@mantine/code-highlight/styles.css';
import { Icon } from '@iconify/react';
import yaml from 'js-yaml';

import type { CliAgentConfig } from 'depictio-react-core';

import { brandColors } from '../profile/colors';

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

interface DisplayTokenModalProps {
  opened: boolean;
  onClose: () => void;
  /** YAML-serialisable config returned by /auth/generate_agent_config.
   *  When `null`, the modal renders an "unavailable" alert (matches the Dash
   *  fallback path in `tokens_management.py:725-734`). */
  config: CliAgentConfig | null;
}

/** Mirrors the YAML config display modal in `tokens_management.py:418-429`
 *  + `_create_config_display`. Uses `@mantine/code-highlight` for syntax
 *  highlighting (Dash uses `dmc.CodeHighlight`). */
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
    <Modal opened={opened} onClose={onClose} centered size="lg">
      <Stack gap="md">
        <Group gap="sm">
          <Icon icon="mdi:check-circle" width={28} color={brandColors.green} />
          <Title order={3} c={brandColors.green}>
            Configuration Created Successfully
          </Title>
        </Group>

        {!config ? (
          <Alert
            color="yellow"
            icon={<Icon icon="mdi:alert" width={20} />}
            title="Configuration Generated — CLI Config Unavailable"
          >
            Your token was created but the CLI configuration could not be retrieved.
            Please contact an administrator.
          </Alert>
        ) : (
          <>
            <Alert
              color="yellow"
              icon={<Icon icon="mdi:alert" width={20} />}
              title="Important"
            >
              Please copy the configuration and store it in a safe place, such as{' '}
              <Code>~/.depictio/CLI.yaml</Code>. You will not be able to access this
              configuration again once you close this dialog.
            </Alert>

            <Group justify="space-between" align="center">
              <span /> {/* spacer so the button right-aligns above the code block */}
              <Button
                size="xs"
                variant="light"
                leftSection={
                  <Icon
                    icon={copied ? 'mdi:check' : 'mdi:content-copy'}
                    width={16}
                  />
                }
                color={copied ? 'green' : 'blue'}
                onClick={handleCopy}
              >
                {copied ? 'Copied' : 'Copy YAML'}
              </Button>
            </Group>
            {/* Mantine's built-in copy button uses navigator.clipboard, which
                only works in secure contexts. On http://0.0.0.0:8055 it
                silently fails — disable it via withCopyButton={false} and
                rely on the explicit "Copy YAML" button above which falls
                back to document.execCommand('copy'). */}
            <CodeHighlight code={yamlText} language="yaml" withCopyButton={false} />
          </>
        )}
      </Stack>
    </Modal>
  );
};

export default DisplayTokenModal;
