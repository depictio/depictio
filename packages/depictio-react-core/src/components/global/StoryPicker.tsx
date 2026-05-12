/**
 * Story selector — sits at the top of the left sidebar above the Global
 * filter section. Lets the user switch between named directional paths
 * ("Genes → Locations", "Locations → Genes") or stay in Free Explore mode.
 *
 * Selection seeds any `default_global_filter_ids` declared by the story
 * (handled in the store's `setActiveStory`) and triggers a navigation to the
 * story's first tab via the optional `onNavigate` callback.
 */

import React from 'react';
import { Paper, SegmentedControl, Select, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { Story } from '../../api';

export interface StoryPickerProps {
  stories: Story[];
  activeStoryId: string | null;
  onChange: (storyId: string | null) => void;
  /** Called with the dashboard ID of the first tab in the newly-activated
   *  story so the parent can navigate. Receives `null` when switching to
   *  Free Explore. */
  onNavigateToFirstStep?: (firstTabDashboardId: string | null) => void;
}

const FREE_EXPLORE = '__free__';

const StoryPicker: React.FC<StoryPickerProps> = ({
  stories,
  activeStoryId,
  onChange,
  onNavigateToFirstStep,
}) => {
  if (stories.length === 0) return null;

  const handleChange = (value: string) => {
    const next = value === FREE_EXPLORE ? null : value;
    onChange(next);
    if (next && onNavigateToFirstStep) {
      const story = stories.find((s) => s.id === next);
      const firstTab = story?.tab_order?.[0] ?? null;
      onNavigateToFirstStep(firstTab);
    } else if (!next && onNavigateToFirstStep) {
      onNavigateToFirstStep(null);
    }
  };

  // Up to 3 stories: SegmentedControl is more scannable. More: fall back to Select.
  const totalOptions = stories.length + 1;
  const useSegmented = totalOptions <= 3;

  return (
    <Paper withBorder p="xs" radius="md">
      <Stack gap={6}>
        <Text size="xs" fw={600} c="dimmed" tt="uppercase">
          <Icon
            icon="tabler:route"
            width={12}
            style={{ verticalAlign: 'middle', marginRight: 4 }}
          />
          Story
        </Text>
        {useSegmented ? (
          <SegmentedControl
            fullWidth
            size="xs"
            value={activeStoryId ?? FREE_EXPLORE}
            onChange={handleChange}
            data={[
              { value: FREE_EXPLORE, label: 'Free explore' },
              ...stories.map((s) => ({ value: s.id, label: s.name })),
            ]}
          />
        ) : (
          <Select
            size="xs"
            value={activeStoryId ?? FREE_EXPLORE}
            onChange={(v) => v && handleChange(v)}
            data={[
              { value: FREE_EXPLORE, label: 'Free explore' },
              ...stories.map((s) => ({ value: s.id, label: s.name })),
            ]}
            comboboxProps={{ withinPortal: true }}
          />
        )}
      </Stack>
    </Paper>
  );
};

export default StoryPicker;
