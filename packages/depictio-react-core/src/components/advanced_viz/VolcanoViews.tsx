import React, { useMemo } from 'react';
import { SegmentedControl, Stack, Text } from '@mantine/core';

import type { InteractiveFilter, StoredMetadata } from '../../api';
import type { GroupRenderState } from '../../selectionGroups';
import {
  AdvancedVizConfigDraftProvider,
  useAdvancedVizConfigDraft,
  type VizConfigDraftSink,
} from './AdvancedVizConfigDraft';
import { ControlsLeadContext } from './controlsDock';
import {
  resolveView,
  viewMetadata,
  volcanoPatch,
  volcanoViewOptions,
  type DiffView,
  type VolcanoViewsConfig,
} from './diffViews';
import { usePersistedVizControl } from './usePersistedVizControl';
import MARenderer from './MARenderer';
import QQRenderer from './QQRenderer';
import VolcanoRenderer from './VolcanoRenderer';

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: VolcanoViewsConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  groupRender?: GroupRenderState;
}

const RENDERERS: Record<DiffView, React.ComponentType<any>> = {
  volcano: VolcanoRenderer,
  ma: MARenderer,
  qq: QQRenderer,
};

/**
 * A volcano component, drawn as a volcano, an MA plot or a QQ plot of the same
 * test (see diffViews.ts). The switch heads the controls of whichever renderer
 * is on screen, through `ControlsLeadContext`, so none of the three needs to
 * know about the others. A config that binds no other view draws the volcano
 * alone, with no switch.
 */
const VolcanoViews: React.FC<Props> = (props) => {
  const { metadata } = props;
  const config = (metadata.config ?? {}) as VolcanoViewsConfig;
  const options = useMemo(() => volcanoViewOptions(config), [config]);
  const [pick, setPick] = usePersistedVizControl<DiffView>(metadata, 'default_view', 'volcano');
  const view = resolveView(pick, options);
  const viewMeta = useMemo(() => viewMetadata(metadata, view), [metadata, view]);

  // A control of the MA view writes the volcano setting it stands for.
  const sink = useAdvancedVizConfigDraft();
  const viewSink = useMemo<VizConfigDraftSink | null>(() => {
    if (!sink || view === 'volcano') return sink;
    return (index, patch) => {
      const back = volcanoPatch(view, patch);
      if (Object.keys(back).length) sink(index, back);
    };
  }, [sink, view]);

  const lead = useMemo(
    () =>
      options.length > 1 ? (
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            View
          </Text>
          <SegmentedControl
            size="xs"
            fullWidth
            value={view}
            onChange={(v) => setPick(v as DiffView)}
            data={options}
            data-testid="volcano-view-switch"
          />
        </Stack>
      ) : null,
    [options, view, setPick],
  );

  const Renderer = RENDERERS[view];
  return (
    <ControlsLeadContext.Provider value={lead}>
      <AdvancedVizConfigDraftProvider value={viewSink}>
        <Renderer key={view} {...props} metadata={viewMeta} />
      </AdvancedVizConfigDraftProvider>
    </ControlsLeadContext.Provider>
  );
};

export default VolcanoViews;
