/**
 * The one look of every "what changed" list (#1397): the dashboard's and the
 * project's What's new panels and the notifications bell.
 *
 * A change is a row, not a pile of chips: a tinted icon says what kind of
 * change it is, the title names what changed, one line says how, and a dimmed
 * line says who and when. Names (collections, runs, samples) are words in that
 * line, so a long list wraps like prose instead of like a tag cloud.
 */
import React from 'react';
import {
  ActionIcon,
  Anchor,
  Button,
  Group,
  ScrollArea,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { Z_LAYERS } from 'depictio-react-core';

import { formatDateTimeVerbose, formatRelative } from '../lib/datetime';
import { CHANGE_COLOR } from './palette';
import './feed.css';

/** Kinds of change, each with its icon and its colour from the shared
 *  palette. Thin tabler outline icons on a light tint, in every feed: the
 *  list is read, the icons only sort it. Section headings use the same icon
 *  as the rows under them. */
export const FEED_KIND = {
  data: { icon: 'tabler:database', color: CHANGE_COLOR.data },
  recomputed: { icon: 'tabler:refresh', color: CHANGE_COLOR.data },
  run: { icon: 'tabler:folder-plus', color: CHANGE_COLOR.new },
  emptied: { icon: 'tabler:database-off', color: CHANGE_COLOR.warning },
  failed: { icon: 'tabler:alert-circle', color: CHANGE_COLOR.failed },
  dashboard: { icon: 'tabler:layout-dashboard', color: CHANGE_COLOR.dashboard },
  comment: { icon: 'tabler:message-circle', color: CHANGE_COLOR.comment },
  project: { icon: 'tabler:folder', color: CHANGE_COLOR.new },
} as const;
export type FeedKind = keyof typeof FEED_KIND;

/** "a · b · c", skipping the blanks. */
export const facts = (...parts: Array<string | null | false | undefined>): string =>
  parts.filter(Boolean).join(' · ');

/** Up to `max` names, then "+N". */
export function nameList(names: string[], max = 3): string {
  if (names.length <= max) return names.join(', ');
  return `${names.slice(0, max).join(', ')} +${names.length - max}`;
}

export const When: React.FC<{ at: string | null | undefined }> = ({ at }) => {
  if (!at) return null;
  return (
    <Tooltip label={formatDateTimeVerbose(at)} withArrow openDelay={300} zIndex={Z_LAYERS.tooltip}>
      <span>{formatRelative(at)}</span>
    </Tooltip>
  );
};

export const FeedSection: React.FC<{
  title: string;
  count?: number;
  /** A thin icon before the title. */
  icon?: string;
  testId?: string;
  children: React.ReactNode;
}> = ({ title, count, icon, testId, children }) => (
  <Stack gap={2} data-testid={testId}>
    <Text component="div" className="dc-feed-section" data-testid={testId ? `${testId}-head` : undefined}>
      {icon && <Icon icon={icon} width={13} aria-hidden />}
      {title}
      {count != null && <span className="dc-feed-section__count">{count}</span>}
    </Text>
    {children}
  </Stack>
);

/** A quiet link in the meta line; `onClick` alone makes it a button that
 *  looks like one, so every action in a feed reads the same. */
export interface FeedAction {
  label: string;
  href?: string;
  onClick?: () => void;
  newTab?: boolean;
  testId?: string;
}

export const FeedLink: React.FC<{ action: FeedAction }> = ({ action }) => {
  const common = {
    size: 'xs' as const,
    'data-testid': action.testId,
    onClick: (e: React.MouseEvent) => {
      e.stopPropagation();
      action.onClick?.();
    },
  };
  if (!action.href) {
    return (
      <Anchor component="button" type="button" {...common}>
        {action.label}
      </Anchor>
    );
  }
  return (
    <Anchor href={action.href} {...common} {...(action.newTab ? { target: '_blank', rel: 'noopener' } : {})}>
      {action.label}
    </Anchor>
  );
};

export interface FeedItemProps {
  kind: FeedKind;
  /** The icon's colour when the outcome, not the kind, should set it (a
   *  failed ingestion). */
  color?: string;
  title: React.ReactNode;
  /** How it changed, one line of facts. */
  summary?: React.ReactNode;
  /** A second, quieter line (sample names, an excerpt). */
  detail?: React.ReactNode;
  /** Names (samples, ids) set in the monospace face. */
  detailMono?: boolean;
  detailTestId?: string;
  /** Who, as words; `at` follows it. */
  by?: string[];
  at?: string | null;
  /** A link at the end of the meta line. */
  action?: FeedAction;
  /** Several, after `action`: each a link, or a button styled as one. */
  actions?: FeedAction[];
  href?: string;
  onClick?: () => void;
  /** Icon actions on the right of the title line (non-link items only). */
  aside?: React.ReactNode;
  /** Actions and an opened detail, below the meta line (non-link items only). */
  children?: React.ReactNode;
  [dataAttr: `data-${string}`]: string | number | boolean | undefined;
}

export const FeedItem: React.FC<FeedItemProps> = ({
  kind,
  color: colorOverride,
  title,
  summary,
  detail,
  detailMono = false,
  detailTestId,
  by,
  at,
  action,
  actions,
  href,
  onClick,
  aside,
  children,
  ...data
}) => {
  const links = [...(action ? [action] : []), ...(actions ?? [])];
  const { icon } = FEED_KIND[kind];
  const color = colorOverride ?? FEED_KIND[kind].color;
  const who = by && by.length ? `by ${by.join(', ')}` : null;
  const body = (
    <Group gap="sm" wrap="nowrap" align="flex-start">
      <ThemeIcon variant="light" color={color} radius="xl" size={28} style={{ flexShrink: 0 }}>
        <Icon icon={icon} width={15} aria-hidden />
      </ThemeIcon>
      <Stack gap={1} style={{ minWidth: 0, flex: 1 }}>
        <Group gap={6} wrap="nowrap" justify="space-between" align="flex-start">
          <Text component="div" size="sm" fw={500} lineClamp={1} className="dc-feed-item__title">
            {title}
          </Text>
          {aside && (
            <Group gap={2} wrap="nowrap" style={{ flexShrink: 0 }}>
              {aside}
            </Group>
          )}
        </Group>
        {summary && (
          <Text size="xs" className="dc-feed-item__summary">
            {summary}
          </Text>
        )}
        {detail && (
          <Text
            size="xs"
            c="dimmed"
            lineClamp={2}
            className={detailMono ? 'dc-feed-item__detail--mono' : undefined}
            data-testid={detailTestId}
          >
            {detail}
          </Text>
        )}
        {(who || at || links.length > 0) && (
          <Text size="xs" c="dimmed" className="dc-feed-item__meta">
            {who}
            {who && at && ' · '}
            <When at={at} />
            {links.map((link, i) => (
              <React.Fragment key={link.label}>
                {(i > 0 || who || at) && ' · '}
                <FeedLink action={link} />
              </React.Fragment>
            ))}
          </Text>
        )}
        {children}
      </Stack>
    </Group>
  );
  if (href || onClick) {
    return (
      <UnstyledButton
        {...(href ? { component: 'a' as const, href } : {})}
        onClick={onClick}
        className="dc-feed-item dc-feed-item--interactive"
        {...data}
      >
        {body}
      </UnstyledButton>
    );
  }
  return (
    <div className="dc-feed-item" {...data}>
      {body}
    </div>
  );
};

/** The one "Mark as seen" of every feed. */
export const FeedMarkSeen: React.FC<{
  onClick: () => void;
  loading?: boolean;
  label?: string;
  testId?: string;
}> = ({ onClick, loading, label = 'Mark as seen', testId }) => (
  <Button
    size="compact-sm"
    variant="subtle"
    leftSection={<Icon icon="tabler:checks" width={15} />}
    loading={loading}
    onClick={onClick}
    data-testid={testId}
  >
    {label}
  </Button>
);

/** The scrolling list of a feed. Its inner wrapper is a flex item, which
 *  without `min-width: 0` grows to its longest line: truncation then fails
 *  and the row actions slide out of the panel. */
export const FeedScroll: React.FC<{ mah: number | string; children: React.ReactNode }> = ({ mah, children }) => (
  <ScrollArea.Autosize mah={mah} type="auto" offsetScrollbars className="dc-feed-scroll">
    {children}
  </ScrollArea.Autosize>
);

/** The panel's head: what the list covers, and its one action. */
export const FeedHeader: React.FC<{
  title: string;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
}> = ({ title, subtitle, action }) => (
  <Group justify="space-between" wrap="nowrap" gap="sm" px={4}>
    <Stack gap={0} style={{ minWidth: 0 }}>
      <Text size="sm" fw={600}>
        {title}
      </Text>
      {subtitle && (
        <Text size="xs" c="dimmed" truncate>
          {subtitle}
        </Text>
      )}
    </Stack>
    {action}
  </Group>
);

/** New since the reader's mark: the same quiet dot as an updated tile. */
export const NewDot: React.FC<{ label?: string; testId?: string }> = ({
  label = 'New since your last visit',
  testId,
}) => (
  <Tooltip label={label} withArrow openDelay={300} zIndex={Z_LAYERS.tooltip}>
    <span role="img" aria-label={label} className="dc-feed-new" data-testid={testId} />
  </Tooltip>
);

/** A quiet icon button for a row's action, named by its tooltip. */
export const FeedIconAction: React.FC<{
  icon: string;
  label: string;
  href?: string;
  onClick?: () => void;
  active?: boolean;
  testId?: string;
}> = ({ icon, label, href, onClick, active = false, testId }) => (
  <Tooltip label={label} withArrow openDelay={250} withinPortal zIndex={Z_LAYERS.tooltip}>
    <ActionIcon
      variant={active ? 'light' : 'subtle'}
      color={active ? CHANGE_COLOR.new : 'gray'}
      size="sm"
      radius="md"
      aria-label={label}
      aria-pressed={onClick && !href ? active : undefined}
      {...(href ? { component: 'a' as const, href } : {})}
      onClick={(e: React.MouseEvent) => {
        e.stopPropagation();
        onClick?.();
      }}
      data-testid={testId}
    >
      <Icon icon={icon} width={15} />
    </ActionIcon>
  </Tooltip>
);
