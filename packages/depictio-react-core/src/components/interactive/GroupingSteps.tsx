import React from 'react';
import { Badge, Group, Stack, Stepper, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useGroupingColor } from '../../selectionGroups';
import { groupingActiveStep, selectionCapableSummary } from './groupingGuide';

/**
 * The guided path to a first group, shown in the Analysis panel while the
 * dashboard has none.
 *
 * It replaces the one grey paragraph that used to stand here ("Lasso points on
 * a chart with cross-filtering enabled…"): a single sentence had to carry
 * where to act, how to act and what happens next, and named only the lasso —
 * so users never learned that a rectangle drag, ticked table rows and a map
 * polygon all feed the same thing.
 *
 * Three steps instead, with the one the user is on marked current (see
 * `groupingActiveStep`). Step 1 quotes how many tiles on *this* dashboard can
 * emit a selection, so the guide is about the dashboard in front of the user
 * rather than about the feature in the abstract.
 */
const GroupingSteps: React.FC<{
  /** Tiles on this dashboard a selection can be saved from. */
  selectableCount: number;
  /** Whether a selection is live right now (the panel's `candidates`). */
  hasSelection: boolean;
}> = ({ selectableCount, hasSelection }) => {
  const groupingColor = useGroupingColor();
  const active = groupingActiveStep(selectableCount, hasSelection);
  const blocked = selectableCount <= 0;

  return (
    <Stepper
      active={active}
      orientation="vertical"
      size="sm"
      iconSize={26}
      color={groupingColor}
      mt={8}
      // The theme's own sizes, matching the panel's other labels: the guide is
      // the first thing a new user reads here and 11px made it work to read.
      styles={{
        stepLabel: { fontSize: 14, fontWeight: 600 },
        stepDescription: { fontSize: 13 },
        stepBody: { marginLeft: 10 },
        verticalSeparator: { marginLeft: 12 },
      }}
    >
      <Stepper.Step
        // Orange with the alert glyph when the dashboard has nothing to select
        // on: the step is not "pending", it cannot be completed here at all,
        // and its description says why.
        color={blocked ? 'orange' : undefined}
        icon={
          <Icon
            icon={blocked ? 'mdi:alert-circle-outline' : 'mdi:select-group'}
            width={15}
            height={15}
          />
        }
        label="Find a tile you can select on"
        description={selectionCapableSummary(selectableCount)}
      />
      <Stepper.Step
        icon={<Icon icon="mdi:lasso" width={15} height={15} />}
        label="Lasso or box-select on it"
        description={
          <Stack gap={4}>
            <Text size="sm" c="dimmed">
              On a chart, hover it and pick either selection tool from the toolbar in its top
              right, then drag over the points. Ticking rows in a table, drawing on a map or
              clicking thumbnails in a gallery all count the same.
            </Text>
            {/* Both drags are equally valid — spelling them out is the whole
                point: the old copy said "lasso" and left box-select looking
                like it would be ignored. */}
            <Group gap={4}>
              <Badge
                size="sm"
                variant="light"
                color={groupingColor}
                leftSection={<Icon icon="mdi:vector-square" width={13} height={13} />}
              >
                Box select
              </Badge>
              <Badge
                size="sm"
                variant="light"
                color={groupingColor}
                leftSection={<Icon icon="mdi:lasso" width={13} height={13} />}
              >
                Lasso
              </Badge>
            </Group>
          </Stack>
        }
      />
      <Stepper.Step
        icon={<Icon icon="mdi:tag-outline" width={15} height={15} />}
        label="Name it and save"
        description="The panel shows what you picked; name it, keep or change the color, save. Saving frees the selection, so the next cohort starts clean."
      />
    </Stepper>
  );
};

export default GroupingSteps;
