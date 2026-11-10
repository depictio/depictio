import React, { type ReactNode } from 'react';
import { Badge, Box, Group, Paper, Stack, Text, Title } from '@mantine/core';
import {
  AlertTriangle,
  CheckCircle2,
  Cloud,
  Flag,
  Folder,
  HelpCircle,
  Info,
  Layers,
  Link as LinkIcon,
  Upload,
  FileText,
} from 'lucide-react';
import type { ProjectSourceKind } from '../layout';

export type FoundStatus = 'ok' | 'differs' | 'warn' | 'info' | null;

export interface FoundRow {
  key: 'pipeline' | 'runs' | 'source' | 'contents' | 'checks' | (string & {});
  label: string;
  value: ReactNode;
  status?: FoundStatus;
  hint?: ReactNode;
}

export interface FoundCardProps {
  title?: string;
  rows: FoundRow[];
  footer?: ReactNode;
  testId?: string;
  /** Inside a section that already frames and titles it. */
  embedded?: boolean;
}

const STATUS: Record<'ok' | 'differs' | 'warn' | 'info', { color: string; Icon: typeof Info }> = {
  ok: { color: 'green', Icon: CheckCircle2 },
  differs: { color: 'orange', Icon: AlertTriangle },
  warn: { color: 'orange', Icon: AlertTriangle },
  info: { color: 'blue', Icon: Info },
};

/** Read-only facts about a project (or one about to be created), one per row. */
export const FoundCard: React.FC<FoundCardProps> = ({
  title = 'What Depictio found',
  rows,
  footer,
  testId = 'found-card',
  embedded = false,
}) => (
  <Paper withBorder={!embedded} radius="md" data-testid={testId} maw={embedded ? undefined : 720}>
    {!embedded && (
      <Box px="md" py="sm">
        <Title order={5}>{title}</Title>
      </Box>
    )}
    {rows.map((row) => {
      const status = row.status ? STATUS[row.status] : null;
      return (
        <Group
          key={row.key}
          align="flex-start"
          wrap="nowrap"
          gap="md"
          px="md"
          py="sm"
          style={{ borderTop: '1px solid var(--mantine-color-default-border)' }}
          data-testid={`${testId}-row-${row.key}`}
        >
          <Text size="sm" c="dimmed" w={90} style={{ flexShrink: 0 }}>
            {row.label}
          </Text>
          <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
            <Box fz="sm">{row.value}</Box>
            {row.hint && status ? (
              <Group gap={6} wrap="nowrap" c={status.color}>
                <status.Icon size={14} aria-hidden />
                <Text size="xs" c={status.color} component="span">
                  {row.hint}
                </Text>
              </Group>
            ) : row.hint ? (
              <Text size="xs" c="dimmed">
                {row.hint}
              </Text>
            ) : null}
          </Stack>
        </Group>
      );
    })}
    {footer && (
      <Box
        px="md"
        py="sm"
        style={{ borderTop: '1px solid var(--mantine-color-default-border)' }}
      >
        {footer}
      </Box>
    )}
  </Paper>
);

/** Run names as chips, with "+N more" past `max`. */
export const RunChips: React.FC<{ names: string[]; max?: number }> = ({ names, max = 3 }) => {
  if (names.length === 0) return null;
  const shown = names.slice(0, max);
  const rest = names.length - shown.length;
  return (
    <Group gap={6} wrap="wrap" data-testid="run-chips">
      {shown.map((n) => (
        <Badge key={n} variant="light" color="gray" radius="sm" tt="none" ff="monospace">
          {n}
        </Badge>
      ))}
      {rest > 0 && (
        <Badge variant="light" color="gray" radius="sm" tt="none" ff="monospace" c="dimmed">
          +{rest} more
        </Badge>
      )}
    </Group>
  );
};

export const SOURCE_ICON: Record<ProjectSourceKind, typeof Info> = {
  upload: Upload,
  url: LinkIcon,
  folder: Folder,
  s3: Cloud,
  run: Flag,
  manifest: FileText,
  mixed: Layers,
  unknown: HelpCircle,
};

export const SOURCE_TEXT: Record<ProjectSourceKind, string> = {
  upload: 'Uploaded',
  url: 'A URL',
  folder: 'A folder',
  s3: 'An S3 bucket',
  run: 'A run folder',
  manifest: 'A manifest',
  mixed: 'Several sources',
  unknown: 'Not recorded',
};

/** Where the data lives: an icon for the kind, then the location (or a label). */
export const SourceValue: React.FC<{
  kind: ProjectSourceKind;
  location?: string | null;
  /** Several folders: each is listed on its own line. */
  locations?: string[];
}> = ({ kind, location, locations }) => {
  const Glyph = SOURCE_ICON[kind] ?? HelpCircle;
  if (locations && locations.length > 1) {
    return (
      <Stack gap={4} data-testid="source-value">
        {locations.map((l) => (
          <Group key={l} gap={8} wrap="nowrap" data-testid="source-folder">
            <Glyph size={14} aria-hidden style={{ flexShrink: 0 }} />
            <Text size="sm" style={{ wordBreak: 'break-all' }}>
              {l}
            </Text>
          </Group>
        ))}
      </Stack>
    );
  }
  return (
    <Group gap={8} wrap="nowrap" data-testid="source-value">
      <Glyph size={14} aria-hidden style={{ flexShrink: 0 }} />
      <Text size="sm" style={{ wordBreak: 'break-all' }}>
        {kind === 'upload' && location ? `${SOURCE_TEXT[kind]}: ${location}` : location || SOURCE_TEXT[kind]}
      </Text>
    </Group>
  );
};

export default FoundCard;
