import React from 'react';
import { ActionIcon, Anchor, Badge, Button, Group, Paper, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

export interface SharedViewScope {
  key: string;
  label: string;
  /** Drops just this one filter. The banner replaces the toolbar's chip row
   *  while it is on screen, so it has to carry the same per-filter control. */
  onRemove: () => void;
}

interface SharedViewBannerProps {
  /** What the link narrowed to, one chip per filter value. */
  scope: SharedViewScope[];
  /** How many rows survive the filter, and how many exist in total. */
  shown: number;
  total: number;
  /** "dashboard" / "project" — pluralised here. */
  noun: string;
  /** The same scope on the other listing, when it carries over. */
  crossLink?: { href: string; label: string };
  /** Mantine color for the banner. Each listing passes its own page accent so
   *  the banner reads as part of that page rather than as a stray alert:
   *  Dashboards is the tertiary role, Projects the secondary one. */
  color: string;
  onClearAll: () => void;
}

const plural = (n: number, noun: string) => `${noun}${n === 1 ? '' : 's'}`;

/** Shown when the visitor arrived on a link that already carried filters.
 *
 *  Someone handed this URL to a reviewer to say "look at these and not the
 *  other eighty" — so the page states what it narrowed to and how much it is
 *  hiding, rather than silently presenting a partial listing as if it were
 *  everything. The escape hatch is deliberate: the scope is a starting point,
 *  not a wall. */
const SharedViewBanner: React.FC<SharedViewBannerProps> = ({
  scope,
  shown,
  total,
  noun,
  crossLink,
  color,
  onClearAll,
}) => {
  const hidden = Math.max(total - shown, 0);

  return (
    <Paper
      withBorder
      radius="md"
      p="sm"
      data-testid="shared-view-banner"
      style={{
        borderColor: `var(--mantine-color-${color}-4)`,
        background: `var(--mantine-color-${color}-light)`,
      }}
    >
      <Group justify="space-between" wrap="wrap" gap="sm">
        <Group gap="xs" wrap="wrap" style={{ minWidth: 0 }}>
          <Icon
            icon="mdi:link-variant"
            width={18}
            color={`var(--mantine-color-${color}-7)`}
          />
          <Text size="sm" fw={600}>
            Shared view
          </Text>
          {scope.map((s) => (
            <Badge
              key={s.key}
              variant="filled"
              color={color}
              radius="sm"
              rightSection={
                <ActionIcon
                  size="xs"
                  variant="transparent"
                  color="white"
                  onClick={s.onRemove}
                  aria-label={`Remove filter ${s.label}`}
                >
                  <Icon icon="mdi:close" width={12} />
                </ActionIcon>
              }
              style={{ paddingRight: 4 }}
            >
              {s.label}
            </Badge>
          ))}
          <Text size="sm" c="dimmed">
            {shown} of {total} {plural(total, noun)}
            {hidden > 0 ? `, ${hidden} hidden by this link` : ''}
          </Text>
        </Group>

        <Group gap="sm" wrap="nowrap">
          {crossLink && (
            <Anchor href={crossLink.href} size="sm" fw={500}>
              {crossLink.label} →
            </Anchor>
          )}
          <Button
            variant="subtle"
            color="gray"
            size="compact-sm"
            onClick={onClearAll}
            leftSection={<Icon icon="mdi:close" width={14} />}
          >
            Show everything
          </Button>
        </Group>
      </Group>
    </Paper>
  );
};

export default SharedViewBanner;
