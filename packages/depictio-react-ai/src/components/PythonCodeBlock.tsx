import React, { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Code,
  Collapse,
  Group,
  Stack,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

interface Props {
  code: string;
  /** Short label shown next to the Python badge — e.g. "Polars",
   *  "Plotly Express". Helps users tell analyze code apart from figure
   *  code at a glance. */
  flavor?: string;
  /** Start expanded vs collapsed. Defaults to expanded so the user
   *  immediately sees what the LLM produced. */
  defaultOpen?: boolean;
  /** Tweak the visual emphasis. "code" looks like analyze step output;
   *  "figure" pairs with the plot preview. */
  tone?: 'code' | 'figure';
}

/**
 * Shared widget used wherever the AI surface needs to expose the actual
 * Python the user could run to reproduce what the assistant did.
 *
 * Per the user's explainability requirement: every LLM-driven action
 * (analyze step, figure suggestion) renders the equivalent Python here
 * so nothing is hidden behind opaque structured output.
 */
const PythonCodeBlock: React.FC<Props> = ({
  code,
  flavor,
  defaultOpen = true,
  tone = 'code',
}) => {
  const [open, setOpen] = useState(defaultOpen);
  const [copied, setCopied] = useState(false);

  if (!code.trim()) return null;

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard not available — silently no-op
    }
  }

  return (
    <Stack gap={4}>
      <Group gap="xs" align="center">
        <Badge
          size="xs"
          variant="light"
          color={tone === 'figure' ? 'grape' : 'indigo'}
          leftSection={<Icon icon="logos:python" width={10} />}
        >
          Python{flavor ? ` · ${flavor}` : ''}
        </Badge>
        <Tooltip label={copied ? 'Copied' : 'Copy'}>
          <ActionIcon size="xs" variant="subtle" color="gray" onClick={copy}>
            <Icon
              icon={
                copied
                  ? 'material-symbols:check'
                  : 'material-symbols:content-copy-outline'
              }
              width={12}
            />
          </ActionIcon>
        </Tooltip>
        <ActionIcon
          ml="auto"
          size="xs"
          variant="subtle"
          color="gray"
          onClick={() => setOpen((v) => !v)}
        >
          <Icon
            icon={
              open
                ? 'material-symbols:keyboard-arrow-up'
                : 'material-symbols:keyboard-arrow-down'
            }
            width={14}
          />
        </ActionIcon>
      </Group>
      <Collapse in={open}>
        <Code block style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
          {code}
        </Code>
      </Collapse>
    </Stack>
  );
};

export default PythonCodeBlock;
