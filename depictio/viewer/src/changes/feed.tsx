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
import { Anchor, Group, Stack, Text, ThemeIcon, Tooltip, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { formatDateTimeVerbose, formatRelative } from '../lib/datetime';
import './feed.css';

/** Kinds of change, each with its icon and theme colour. */
export const FEED_KIND = {
  data: { icon: 'mdi:database-refresh-outline', color: 'teal' },
  run: { icon: 'mdi:folder-play-outline', color: 'blue' },
  emptied: { icon: 'mdi:database-remove-outline', color: 'orange' },
  failed: { icon: 'mdi:alert-circle-outline', color: 'red' },
  dashboard: { icon: 'mdi:view-dashboard-edit-outline', color: 'violet' },
  comment: { icon: 'mdi:comment-text-outline', color: 'grape' },
  project: { icon: 'mdi:jira', color: 'blue' },
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
    <Tooltip label={formatDateTimeVerbose(at)} withArrow openDelay={300}>
      <span>{formatRelative(at)}</span>
    </Tooltip>
  );
};

export const FeedSection: React.FC<{
  title: string;
  count?: number;
  testId?: string;
  children: React.ReactNode;
}> = ({ title, count, testId, children }) => (
  <Stack gap={2} data-testid={testId}>
    <Text className="dc-feed-section" data-testid={testId ? `${testId}-head` : undefined}>
      {title}
      {count != null && <span className="dc-feed-section__count">{count}</span>}
    </Text>
    {children}
  </Stack>
);

export interface FeedItemProps {
  kind: FeedKind;
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
  action?: { label: string; href: string; newTab?: boolean; testId?: string };
  href?: string;
  onClick?: () => void;
  [dataAttr: `data-${string}`]: string | number | boolean | undefined;
}

export const FeedItem: React.FC<FeedItemProps> = ({
  kind,
  title,
  summary,
  detail,
  detailMono = false,
  detailTestId,
  by,
  at,
  action,
  href,
  onClick,
  ...data
}) => {
  const { icon, color } = FEED_KIND[kind];
  const who = by && by.length ? `by ${by.join(', ')}` : null;
  const body = (
    <Group gap="sm" wrap="nowrap" align="flex-start">
      <ThemeIcon variant="light" color={color} radius="md" size={30} style={{ flexShrink: 0 }}>
        <Icon icon={icon} width={17} aria-hidden />
      </ThemeIcon>
      <Stack gap={1} style={{ minWidth: 0, flex: 1 }}>
        <Text size="sm" fw={500} lineClamp={1} className="dc-feed-item__title">
          {title}
        </Text>
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
        {(who || at || action) && (
          <Text size="xs" c="dimmed" className="dc-feed-item__meta">
            {who}
            {who && at && ' · '}
            <When at={at} />
            {action && (
              <>
                {(who || at) && ' · '}
                <Anchor
                  href={action.href}
                  size="xs"
                  onClick={(e) => e.stopPropagation()}
                  data-testid={action.testId}
                  {...(action.newTab ? { target: '_blank', rel: 'noopener' } : {})}
                >
                  {action.label}
                </Anchor>
              </>
            )}
          </Text>
        )}
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
  <Tooltip label={label} withArrow openDelay={300}>
    <span role="img" aria-label={label} className="dc-feed-new" data-testid={testId} />
  </Tooltip>
);
