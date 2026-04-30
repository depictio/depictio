import React, { useState } from 'react';
import {
  ActionIcon,
  Alert,
  Code,
  Group,
  Modal,
  Paper,
  Stack,
  Title,
  Tooltip,
} from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import '@mantine/code-highlight/styles.css';
import { Icon } from '@iconify/react';
import yaml from 'js-yaml';

import type { CliAgentConfig } from 'depictio-react-core';

import { brandColors } from '../profile/colors';

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
  const [copied, setCopied] = useState(false);
  const yamlText = config ? yaml.dump(config, { lineWidth: 120 }) : '';

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(yamlText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore clipboard errors — UI shows no toast in the Dash version either
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

            <Paper p="sm" withBorder radius="md" pos="relative">
              <Tooltip label={copied ? 'Copied!' : 'Copy to clipboard'} position="left">
                <ActionIcon
                  variant="light"
                  color={copied ? 'green' : 'gray'}
                  onClick={handleCopy}
                  pos="absolute"
                  top={8}
                  right={8}
                  style={{ zIndex: 1 }}
                  aria-label="Copy YAML"
                >
                  <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={16} />
                </ActionIcon>
              </Tooltip>
              <CodeHighlight code={yamlText} language="yaml" />
            </Paper>
          </>
        )}
      </Stack>
    </Modal>
  );
};

export default DisplayTokenModal;
