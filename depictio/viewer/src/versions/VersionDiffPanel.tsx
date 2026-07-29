/**
 * "What changed in this version" — shown under the selected timeline row.
 *
 * Sibling of `VersionCompatibilityPanel`, and the same shape: loads on mount,
 * degrades quietly. The two answer adjacent questions — this one is *what the
 * author changed*, that one is *whether the data still fits*.
 *
 * Named fields rather than a bare "reconfigured": "y axis, colour" is something
 * a reader can act on, and it also exposes the diff's own noise. If a routine
 * re-save started reporting a field, it would be visible here rather than
 * silently inflating a count.
 */

import React from 'react';
import { Alert, Badge, Group, Loader, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { VersionComponentDiff } from 'depictio-react-core';

import { describeChange, summariseDiff } from './diffMarks';
import { useVersionDiff } from './useVersionDiff';

interface VersionDiffPanelProps {
  versionId: string | null;
  /** Skips the request entirely when the panel is collapsed. */
  enabled?: boolean;
  /** Rendered next to the summary — e.g. "since v11 (12 saves)". */
  contextLabel?: string;
}

const CHANGE_META: Record<string, { color: string; icon: string; verb: string }> = {
  added: { color: 'green', icon: 'mdi:plus-circle', verb: 'Added' },
  removed: { color: 'red', icon: 'mdi:minus-circle', verb: 'Removed' },
  modified: { color: 'yellow', icon: 'mdi:pencil-circle', verb: 'Changed' },
};

const DiffRow: React.FC<{ component: VersionComponentDiff }> = ({ component }) => {
  const meta = CHANGE_META[component.change] ?? CHANGE_META.modified;
  const detail = describeChange(component);

  return (
    <Group gap={8} wrap="nowrap" align="flex-start" data-testid="version-diff-row">
      <Icon
        icon={meta.icon}
        width={15}
        style={{ color: `var(--mantine-color-${meta.color}-6)`, flexShrink: 0, marginTop: 2 }}
      />
      <Stack gap={0} style={{ minWidth: 0 }}>
        <Text size="xs" fw={600} truncate>
          {meta.verb} {component.title || component.component_type || component.index}
        </Text>
        {detail && (
          <Text size="xs" c="dimmed" truncate>
            {detail}
          </Text>
        )}
      </Stack>
    </Group>
  );
};

const VersionDiffPanel: React.FC<VersionDiffPanelProps> = ({
  versionId,
  enabled = true,
  contextLabel,
}) => {
  const { diff, loading, error } = useVersionDiff(versionId, 'previous', enabled);

  if (!enabled || !versionId) return null;

  if (loading) {
    return (
      <Group gap={8} py="xs">
        <Loader size="xs" />
        <Text size="xs" c="dimmed">
          Working out what changed…
        </Text>
      </Group>
    );
  }

  if (error) {
    // Not an Alert: a missing diff is strictly less informative, never wrong,
    // and it sits inside a drawer whose other actions all still work.
    return (
      <Text size="xs" c="dimmed" py="xs">
        Couldn’t work out what changed.
      </Text>
    );
  }

  if (!diff) return null;

  const rows = diff.tabs.flatMap((tab) => tab.components);
  const summary = summariseDiff(diff);

  if (!rows.length) {
    return (
      <Text size="xs" c="dimmed" py="xs" data-testid="version-diff-panel">
        No component changes{contextLabel ? ` ${contextLabel}` : ''}.
      </Text>
    );
  }

  return (
    <Stack gap={6} py="xs" data-testid="version-diff-panel">
      <Group gap={6} wrap="nowrap">
        <Badge size="xs" variant="light" color="gray">
          {summary}
        </Badge>
        {contextLabel && (
          // The base is whatever is *now* adjacent — retention can prune what
          // used to be — so the panel names it rather than implying seq - 1.
          <Tooltip label="Compared against the previous version in the timeline" withArrow>
            <Text size="xs" c="dimmed" truncate>
              {contextLabel}
            </Text>
          </Tooltip>
        )}
      </Group>

      {diff.tabs
        .filter((tab) => tab.change === 'added' || tab.change === 'removed')
        .map((tab) => (
          <Group key={`tab-${tab.tab_id}`} gap={8} wrap="nowrap">
            <Icon
              icon={tab.change === 'added' ? 'mdi:tab-plus' : 'mdi:tab-minus'}
              width={15}
              style={{
                color: `var(--mantine-color-${tab.change === 'added' ? 'green' : 'red'}-6)`,
                flexShrink: 0,
              }}
            />
            <Text size="xs" fw={600} truncate>
              Tab “{tab.title || tab.tab_id}” {tab.change}
              {tab.components.length ? ` (${tab.components.length} components)` : ''}
            </Text>
          </Group>
        ))}

      {rows
        // Components carried by a whole added/removed tab are already summarised
        // by the line above; listing them again would bury the rest.
        .filter((component) => !component.via_tab)
        .map((component) => (
          <DiffRow key={`${component.tab_id}:${component.index}`} component={component} />
        ))}

      {diff.tabs.some((tab) => tab.change === 'changed' && tab.changed_fields.length > 0) && (
        <Alert
          color="gray"
          variant="light"
          p="xs"
          icon={<Icon icon="mdi:tab" width={14} />}
          styles={{ message: { fontSize: 'var(--mantine-font-size-xs)' } }}
        >
          Tab settings changed:{' '}
          {diff.tabs
            .filter((tab) => tab.changed_fields.length > 0)
            .flatMap((tab) => tab.changed_fields)
            .join(', ')}
        </Alert>
      )}
    </Stack>
  );
};

export default VersionDiffPanel;
