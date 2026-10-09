/**
 * How an ingestion run was started.
 *
 * Worth its own badge because "did a human do this, or did a watcher?" is the
 * first question asked of any unexpected run, and the answer changes what you
 * do next. Runs recorded before triggers existed have no value and read as
 * "manual" — accurate, since nothing else could start one at the time.
 */

import React from 'react';
import { Badge, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

const TRIGGER_META: Record<string, { label: string; color: string; icon: string }> = {
  manual: { label: 'Manual', color: 'gray', icon: 'mdi:account' },
  watch: { label: 'Watch', color: 'grape', icon: 'mdi:eye-outline' },
  schedule: { label: 'Scheduled', color: 'blue', icon: 'mdi:clock-outline' },
  ui: { label: 'UI', color: 'teal', icon: 'mdi:cursor-default-click-outline' },
};

export const TriggerBadge: React.FC<{
  trigger?: string | null;
  reason?: string | null;
  size?: string;
}> = ({ trigger, reason, size = 'xs' }) => {
  const meta = TRIGGER_META[trigger || 'manual'] ?? TRIGGER_META.manual;
  const badge = (
    <Badge
      size={size}
      variant="light"
      color={meta.color}
      leftSection={<Icon icon={meta.icon} width={10} />}
    >
      {meta.label}
    </Badge>
  );
  return reason ? (
    <Tooltip label={reason} withArrow multiline maw={420}>
      {badge}
    </Tooltip>
  ) : (
    badge
  );
};
