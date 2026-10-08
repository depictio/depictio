/**
 * Standard layout for a per-type builder: form panel (left) | arrow | live
 * preview panel (right), with the columns-description panel pinned below.
 * The arrow and preview stick under the header while the form scrolls.
 *
 * Mirrors the Dash design layout used by every component module — see e.g.
 * depictio/dash/modules/card_component/design_ui.py:design_card.
 */
import React from 'react';
import { Box, Center, Grid, Stack } from '@mantine/core';
import { Icon } from '@iconify/react';
import ColumnsDescription from './ColumnsDescription';
import StickyPreview, { STICKY_TOP } from './StickyPreview';

interface Props {
  formSlot: React.ReactNode;
  previewSlot: React.ReactNode;
  /** Hide the columns-description (e.g. multiqc has no tabular schema). */
  hideColumns?: boolean;
}

const DesignShell: React.FC<Props> = ({
  formSlot,
  previewSlot,
  hideColumns,
}) => {
  return (
    <Stack gap="lg" pt="md">
      <Grid columns={24} gutter="md" align="stretch">
        <Grid.Col span={{ base: 24, md: 10 }}>
          {/* The form is the builder's BuilderSections; Placement is one of
              its sections (see PlacementSection), not a block of its own. */}
          <Box style={{ height: '100%' }}>{formSlot}</Box>
        </Grid.Col>
        <Grid.Col span={{ base: 24, md: 1 }} visibleFrom="md">
          {/* Level with the upper part of the preview, which no longer
              stretches to the form's height now that it sticks. */}
          <Center h={200} style={{ position: 'sticky', top: STICKY_TOP }}>
            <Icon icon="mdi:arrow-right" width={24} color="var(--mantine-color-dimmed)" />
          </Center>
        </Grid.Col>
        <Grid.Col span={{ base: 24, md: 13 }}>
          <StickyPreview>{previewSlot}</StickyPreview>
        </Grid.Col>
      </Grid>
      {!hideColumns && <ColumnsDescription />}
    </Stack>
  );
};

export default DesignShell;
