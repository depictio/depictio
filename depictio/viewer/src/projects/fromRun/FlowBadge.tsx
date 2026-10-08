/**
 * The one status badge of the "From a run folder" flow.
 *
 * Every status the flow shows (a run folder in the browser, a detected
 * choice, how a template matches the run, whether a data collection is
 * ready) is this badge: same variant, same size, an icon beside the label so
 * nothing rests on colour alone, and the colour a Mantine palette name.
 */
import React from 'react';
import { Badge, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { Z_LAYERS } from 'depictio-react-core';
import type { RunTemplateMatch } from 'depictio-react-core';

export type FlowStatus =
  | 'ready'
  | 'not-found'
  | 'no-files'
  | 'optional'
  | 'skipped'
  | 'run-folder'
  | 'detected'
  | 'exact'
  | 'closest'
  | 'other-version'
  | 'other-pipeline'
  | 'no-template'
  | 'latest'
  | 'matches-run'
  | 'closest-to-run';

const FLOW_STATUS: Record<FlowStatus, { color: string; icon: string; label: string }> = {
  ready: { color: 'green', icon: 'mdi:check-circle', label: 'Ready' },
  'not-found': { color: 'red', icon: 'mdi:file-remove-outline', label: 'Not found' },
  'no-files': { color: 'orange', icon: 'mdi:folder-alert-outline', label: 'No matching files' },
  optional: { color: 'gray', icon: 'mdi:minus-circle-outline', label: 'Optional, not found' },
  skipped: { color: 'gray', icon: 'mdi:debug-step-over', label: 'Left out' },
  'run-folder': { color: 'green', icon: 'mdi:folder-check-outline', label: 'Run folder' },
  detected: { color: 'blue', icon: 'mdi:auto-fix', label: 'Detected' },
  exact: { color: 'green', icon: 'mdi:check-decagram-outline', label: 'Exact match' },
  closest: { color: 'yellow', icon: 'mdi:approximately-equal', label: 'Closest available version' },
  'other-version': { color: 'yellow', icon: 'mdi:swap-horizontal', label: 'Different version' },
  'other-pipeline': { color: 'orange', icon: 'mdi:alert-outline', label: 'Different pipeline' },
  'no-template': { color: 'red', icon: 'mdi:help-circle-outline', label: 'No matching template' },
  latest: { color: 'gray', icon: 'mdi:star-outline', label: 'Newest' },
  'matches-run': { color: 'green', icon: 'mdi:check', label: 'Matches this run' },
  'closest-to-run': { color: 'yellow', icon: 'mdi:approximately-equal', label: 'Closest to this run' },
};

/** The badge for a template match. */
export function matchStatus(match: RunTemplateMatch): FlowStatus {
  return match === 'none' ? 'no-template' : match;
}

interface FlowBadgeProps {
  status: FlowStatus;
  /** Replaces the status's own label. */
  label?: React.ReactNode;
  /** Explains the status on hover. */
  tooltip?: React.ReactNode;
  testId?: string;
  /** Extra attributes for tests and styling hooks (`data-*`). */
  dataAttributes?: Record<string, string | undefined>;
}

export const FlowBadge: React.FC<FlowBadgeProps> = ({
  status,
  label,
  tooltip,
  testId,
  dataAttributes,
}) => {
  const meta = FLOW_STATUS[status];
  const badge = (
    <Badge
      variant="light"
      size="sm"
      radius="sm"
      color={meta.color}
      tt="none"
      leftSection={<Icon icon={meta.icon} width={12} />}
      style={{ flexShrink: 0 }}
      data-testid={testId}
      data-status={status}
      {...dataAttributes}
    >
      {label ?? meta.label}
    </Badge>
  );
  if (!tooltip) return badge;
  return (
    <Tooltip
      label={tooltip}
      withArrow
      multiline
      maw={300}
      zIndex={Z_LAYERS.tooltip}
      events={{ hover: true, focus: true, touch: true }}
    >
      {badge}
    </Tooltip>
  );
};
