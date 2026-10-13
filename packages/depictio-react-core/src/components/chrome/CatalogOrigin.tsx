import React from 'react';
import { ActionIcon, Anchor, Box, Code, Group, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { CatalogSource } from '../../api';
import { catalogToolUrl } from '../../catalogLinks';

/**
 * Where a catalog-added component came from: tool, output, description and the
 * copyable `use:` reference.
 *
 * Its own component because two surfaces show it — the metadata inspector's
 * body and the chrome's catalog button — and they must not drift.
 */
const CatalogOrigin: React.FC<{ source: CatalogSource; framed?: boolean }> = ({
  source,
  framed = true,
}) => {
  const [copied, setCopied] = React.useState(false);
  const toolUrl = catalogToolUrl(source.toolId);

  const copyUse = async () => {
    if (!source.use) return;
    try {
      await navigator.clipboard.writeText(`use: ${source.use}`);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard denied */
    }
  };

  return (
    <Box
      style={
        framed
          ? {
              border: '1px solid var(--mantine-color-violet-2)',
              background: 'var(--mantine-color-violet-0)',
              borderRadius: 8,
              padding: 8,
            }
          : undefined
      }
    >
      <Group gap={6} mb={6} wrap="nowrap">
        <Icon icon="mdi:hammer" width={13} color="var(--mantine-color-violet-6)" />
        <Text size="xs" fw={700} c="violet" tt="uppercase">
          From the tools catalog
        </Text>
      </Group>
      <Stack gap={3}>
        {source.toolName && (
          <Row label="Tool">
            {source.toolName}
            {source.toolId ? ` (${source.toolId})` : ''}
          </Row>
        )}
        {source.outputId && (
          <Row label="Output" mono>
            {source.outputId}
          </Row>
        )}
        {source.description && <Row label="Description">{source.description}</Row>}
        {source.use && (
          <Group gap={6} wrap="nowrap" align="center">
            <Text size="xs" c="dimmed" w={78} style={{ flexShrink: 0 }}>
              Reference
            </Text>
            <Code fz={11}>use: {source.use}</Code>
            <Tooltip label={copied ? 'Copied!' : 'Copy snippet'} withArrow>
              <ActionIcon
                variant="subtle"
                color="violet"
                size="xs"
                onClick={copyUse}
                aria-label="Copy use snippet"
              >
                <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={13} />
              </ActionIcon>
            </Tooltip>
          </Group>
        )}
        {/* The catalog entry itself. Everything above says what the tool is; this
            is the only way from a tile on a dashboard to the definition that put
            it there — the module YAML, its recipe and its fixture. */}
        {toolUrl && (
          <Group gap={8} wrap="nowrap" align="flex-start">
            <Text size="xs" c="dimmed" w={78} style={{ flexShrink: 0 }}>
              Definition
            </Text>
            <Anchor href={toolUrl} target="_blank" rel="noreferrer" size="xs" title={toolUrl}>
              <Group gap={4} wrap="nowrap" component="span" display="inline-flex">
                <Icon icon="mdi:github" width={13} />
                <Text span>depictio/catalog/{source.toolId}</Text>
                <Icon icon="mdi:open-in-new" width={11} />
              </Group>
            </Anchor>
          </Group>
        )}
      </Stack>
    </Box>
  );
};

const Row: React.FC<{ label: string; children: React.ReactNode; mono?: boolean }> = ({
  label,
  children,
  mono,
}) => (
  <Group gap={8} wrap="nowrap" align="flex-start">
    <Text size="xs" c="dimmed" w={78} style={{ flexShrink: 0 }}>
      {label}
    </Text>
    {mono ? (
      <Code fz={11} style={{ wordBreak: 'break-all' }}>
        {children}
      </Code>
    ) : (
      <Text size="xs" style={{ lineHeight: 1.4, wordBreak: 'break-word' }}>
        {children}
      </Text>
    )}
  </Group>
);

export default CatalogOrigin;
