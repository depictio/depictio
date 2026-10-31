/**
 * The genome trace on screen (see `genomeDebug.ts`): the latest events first,
 * with the time since the previous one, so a sequence like "brush, Escape,
 * browser moves" reads top to bottom. Renders nothing unless the trace is on.
 */
import { useState, useSyncExternalStore } from 'react';
import { ActionIcon, Code, Group, Paper, ScrollArea, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  clearGenomeTrace,
  genomeDebugEnabled,
  genomeTrace,
  subscribeGenomeTrace,
} from './genomeDebug';

function short(detail: unknown): string {
  if (detail === undefined) return '';
  const text = typeof detail === 'string' ? detail : JSON.stringify(detail);
  return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}

export default function GenomeDebugPanel() {
  const events = useSyncExternalStore(subscribeGenomeTrace, genomeTrace, genomeTrace);
  const [open, setOpen] = useState(true);
  if (!genomeDebugEnabled()) return null;
  const rows = [...events].reverse().slice(0, 60);
  const copy = () => {
    void navigator.clipboard?.writeText(JSON.stringify(events, null, 1));
  };
  return (
    <Paper
      withBorder
      shadow="md"
      p={6}
      radius="md"
      data-testid="genome-debug-panel"
      style={{
        position: 'fixed',
        left: 12,
        bottom: 12,
        zIndex: 400,
        width: open ? 560 : 'auto',
        maxWidth: 'calc(100vw - 24px)',
      }}
    >
      <Group gap={6} justify="space-between" wrap="nowrap">
        <Text size="xs" fw={700}>
          Genome trace · {events.length}
        </Text>
        <Group gap={2} wrap="nowrap">
          <Tooltip label="Copy the trace as JSON">
            <ActionIcon size="sm" variant="subtle" onClick={copy} aria-label="Copy the trace">
              <Icon icon="tabler:copy" width={14} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label="Clear">
            <ActionIcon size="sm" variant="subtle" onClick={clearGenomeTrace} aria-label="Clear the trace">
              <Icon icon="tabler:trash" width={14} />
            </ActionIcon>
          </Tooltip>
          <ActionIcon
            size="sm"
            variant="subtle"
            onClick={() => setOpen((o) => !o)}
            aria-label={open ? 'Fold the trace' : 'Unfold the trace'}
          >
            <Icon icon={open ? 'tabler:chevron-down' : 'tabler:chevron-up'} width={14} />
          </ActionIcon>
        </Group>
      </Group>
      {open ? (
        <ScrollArea.Autosize mah={260} mt={4} type="auto">
          {rows.length === 0 ? (
            <Text size="xs" c="dimmed">
              Brush, type a locus, press Escape or move the browser: each step shows here.
            </Text>
          ) : (
            rows.map((e, i) => {
              const prev = rows[i + 1];
              const gap = prev ? e.t - prev.t : 0;
              return (
                <Text key={`${e.t}-${i}`} size="xs" style={{ lineHeight: 1.35 }}>
                  <Text span c="dimmed" ff="monospace" size="xs">
                    {gap ? `+${gap}ms`.padStart(8) : '        '}
                  </Text>{' '}
                  <Text span fw={600} size="xs">
                    {e.tile}
                  </Text>{' '}
                  {e.event} {e.detail !== undefined ? <Code fz={10}>{short(e.detail)}</Code> : null}
                </Text>
              );
            })
          )}
        </ScrollArea.Autosize>
      ) : null}
    </Paper>
  );
}
