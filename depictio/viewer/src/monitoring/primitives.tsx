/**
 * Small presentational pieces shared by the monitoring surfaces.
 *
 * Extracted verbatim from AdminMonitoringPanel so the project-scoped panels
 * reuse them instead of growing near-copies.
 */

import React from 'react';
import {
  ActionIcon,
  Box,
  Code,
  CopyButton,
  Group,
  Loader,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { relTime, shortenPath } from './format';

/** Small search box used in each pane header. */
export const SearchInput: React.FC<{ value: string; onChange: (v: string) => void }> = ({
  value,
  onChange,
}) => (
  <TextInput
    size="xs"
    w={180}
    placeholder="Search…"
    leftSection={<Icon icon="mdi:magnify" width={14} />}
    value={value}
    onChange={(e) => onChange(e.currentTarget.value)}
  />
);

/** A single-line, ellipsized path (monospace). The full path shows on hover, and
 *  clicking copies it to the clipboard (the shortened text isn't selectable). */
export const PathTip: React.FC<{ path?: string | null }> = ({ path }) =>
  path ? (
    <CopyButton value={path} timeout={1500}>
      {({ copied, copy }) => (
        <Tooltip
          label={copied ? 'Copied!' : `${path}  (click to copy)`}
          withArrow
          multiline
          maw={560}
        >
          <Code fz="10px" onClick={copy} style={{ whiteSpace: 'nowrap', cursor: 'pointer' }}>
            {shortenPath(path)}
          </Code>
        </Tooltip>
      )}
    </CopyButton>
  ) : (
    <>—</>
  );

/** One metadatum as a stacked label-over-value cell (uppercase caption above the
 *  value). Used in the ingestion detail field grid so values line up in columns
 *  instead of wrapping into an unreadable run-on. */
export const Field: React.FC<{ label: string; children: React.ReactNode }> = ({
  label,
  children,
}) => (
  <Box>
    <Text size="10px" c="dimmed" tt="uppercase" fw={700} lts={0.4}>
      {label}
    </Text>
    {/* A div, not the default <p>: callers pass Code and Badge, which render
        block elements, and a block inside a paragraph is invalid HTML that
        React reports as a nesting error at runtime. */}
    <Text component="div" size="xs" style={{ lineHeight: 1.35 }}>
      {children}
    </Text>
  </Box>
);

/** A long identifier on its own full-width row: caption, then the value in
 *  monospace, ellipsized to the available width and click-to-copy.
 *
 *  Identifiers do not belong in the same grid as PIDs and timestamps — a 60
 *  character agent id in a quarter-width cell is unreadable *and* makes every
 *  short field beside it column-align to nothing. Here it gets the full width,
 *  and the value that matters (the one you paste elsewhere) is one click away. */
export const IdRow: React.FC<{ label: string; value?: string | null }> = ({ label, value }) => (
  <Group gap="xs" wrap="nowrap">
    <Text size="10px" c="dimmed" tt="uppercase" fw={700} lts={0.4} w={78} style={{ flexShrink: 0 }}>
      {label}
    </Text>
    {value ? (
      <CopyButton value={value} timeout={1500}>
        {({ copied, copy }) => (
          <Tooltip
            label={copied ? 'Copied!' : `${value}  (click to copy)`}
            withArrow
            multiline
            maw={560}
          >
            <Code
              fz="10px"
              onClick={copy}
              style={{
                cursor: 'pointer',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                minWidth: 0,
              }}
            >
              {value}
            </Code>
          </Tooltip>
        )}
      </CopyButton>
    ) : (
      <Text size="xs" c="dimmed">
        —
      </Text>
    )}
  </Group>
);

export const TimeText: React.FC<{ iso?: string | null }> = ({ iso }) => (
  <Tooltip label={iso || 'n/a'} disabled={!iso} withArrow>
    <Text component="span" size="xs" c="dimmed">
      {relTime(iso)}
    </Text>
  </Tooltip>
);

/** Small uppercase caption used to title each block in an expanded detail panel. */
export const SectionLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
    {children}
  </Text>
);

/** A titled block: caption above arbitrary content (a CodeHighlight, an Alert…). */
export const DetailBlock: React.FC<{ label: string; children: React.ReactNode }> = ({
  label,
  children,
}) => (
  <Stack gap={2}>
    <SectionLabel>{label}</SectionLabel>
    {children}
  </Stack>
);

/** Shared header: title + auto-refresh toggle + manual refresh + last-updated. */
export const PaneHeader: React.FC<{
  title: string;
  loading: boolean;
  auto: boolean;
  onAuto: (v: boolean) => void;
  onRefresh: () => void;
  extra?: React.ReactNode;
}> = ({ title, loading, auto, onAuto, onRefresh, extra }) => (
  <Group justify="space-between" wrap="nowrap">
    <Group gap="xs">
      <Title order={6}>{title}</Title>
      {loading && <Loader size="xs" />}
    </Group>
    <Group gap="sm" wrap="nowrap">
      {extra}
      <Switch
        size="xs"
        label="Auto"
        checked={auto}
        onChange={(e) => onAuto(e.currentTarget.checked)}
      />
      <Tooltip label="Refresh now" withArrow>
        <ActionIcon variant="subtle" color="gray" onClick={onRefresh} aria-label="Refresh">
          <Icon icon="mdi:refresh" width={16} />
        </ActionIcon>
      </Tooltip>
    </Group>
  </Group>
);
