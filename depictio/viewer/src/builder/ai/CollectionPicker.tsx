/**
 * Data collection picker of the AI Describe step.
 *
 * Chips rather than a dropdown: a dashboard uses one to a handful of
 * collections, and the choice that matters most ("let the AI choose" versus
 * "this one") should be readable at a glance. The dashboard's own collections
 * come first; the rest of the project folds under a toggle, and past a dozen
 * it becomes a searchable select so the chip row never sprawls.
 */
import React, { useState } from 'react';
import { Anchor, Chip, Collapse, Group, Select, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { AI_COLOR } from 'depictio-react-ai';

export const AUTO_COLLECTION = 'auto';

export interface CollectionOption {
  dcId: string;
  tag: string;
  wfId: string;
  wfTag: string | null;
  type: string | null;
  onDashboard: boolean;
}

const TYPE_ICON: Record<string, string> = {
  table: 'mdi:table',
  multiqc: 'mdi:chart-line',
  image: 'mdi:image-area',
  jbrowse2: 'mdi:dna',
};

/** Past this many, the project's other collections are a select, not chips. */
const CHIP_LIMIT = 12;

interface Props {
  collections: CollectionOption[] | null;
  value: string;
  onChange: (value: string) => void;
  /** Rendered dimmed and inert, with `disabledReason` under the chips. */
  disabled?: boolean;
  disabledReason?: string;
}

const CollectionChip: React.FC<{ c: CollectionOption }> = ({ c }) => (
  <Chip value={c.dcId} variant="light" size="sm" radius="sm" data-testid={`ai-describe-dc-${c.dcId}`}>
    <Group gap={4} wrap="nowrap" component="span">
      <Icon icon={TYPE_ICON[c.type ?? ''] ?? 'mdi:database'} width={13} />
      <span>{c.tag}</span>
    </Group>
  </Chip>
);

const CollectionPicker: React.FC<Props> = ({
  collections,
  value,
  onChange,
  disabled = false,
  disabledReason,
}) => {
  const [othersOpen, setOthersOpen] = useState(false);
  const list = collections ?? [];
  const onDashboard = list.filter((c) => c.onDashboard);
  const others = list.filter((c) => !c.onDashboard);
  const otherSelected = others.find((c) => c.dcId === value);
  // Keep the fold open once an "other" collection is chosen (or pinned when
  // coming back from Design) so the selection is never hidden.
  const showOthers = othersOpen || Boolean(otherSelected);

  return (
    <Stack gap="xs" style={{ opacity: disabled ? 0.5 : 1 }} data-testid="ai-describe-dc">
      <Chip.Group multiple={false} value={value} onChange={(v) => !disabled && onChange(String(v))}>
        <Group gap="xs">
          <Chip value={AUTO_COLLECTION} variant="light" color={AI_COLOR} size="sm" radius="sm" disabled={disabled}>
            <Group gap={4} wrap="nowrap" component="span">
              <Icon icon="material-symbols:auto-awesome-outline" width={13} />
              <span>Auto</span>
            </Group>
          </Chip>
          {collections === null && (
            <Text size="xs" c="dimmed">
              Loading collections…
            </Text>
          )}
          {onDashboard.map((c) => (
            <CollectionChip key={c.dcId} c={c} />
          ))}
          {onDashboard.length > 0 && others.length > 0 && (
            <Text size="xs" c="dimmed">
              on this dashboard
            </Text>
          )}
        </Group>
        {others.length > 0 && (
          <Stack gap={6} mt={4}>
            {!showOthers ? (
              <Anchor
                size="xs"
                c="dimmed"
                component="button"
                type="button"
                onClick={() => setOthersOpen(true)}
                disabled={disabled}
                data-testid="ai-describe-dc-more"
              >
                {others.length} other collection{others.length === 1 ? '' : 's'} in the project…
              </Anchor>
            ) : (
              <Text size="xs" c="dimmed">
                Other collections in the project
              </Text>
            )}
            <Collapse in={showOthers}>
              {others.length <= CHIP_LIMIT ? (
                <Group gap="xs">
                  {others.map((c) => (
                    <CollectionChip key={c.dcId} c={c} />
                  ))}
                </Group>
              ) : (
                <Select
                  size="xs"
                  searchable
                  placeholder="Search the project's collections"
                  value={otherSelected?.dcId ?? null}
                  onChange={(v) => v && onChange(v)}
                  data={others.map((c) => ({
                    value: c.dcId,
                    label: c.wfTag ? `${c.tag}  (${c.wfTag})` : c.tag,
                  }))}
                  disabled={disabled}
                  maw={420}
                />
              )}
            </Collapse>
          </Stack>
        )}
      </Chip.Group>
      {disabled && disabledReason && (
        <Text size="xs" c="dimmed">
          {disabledReason}
        </Text>
      )}
    </Stack>
  );
};

export default CollectionPicker;
