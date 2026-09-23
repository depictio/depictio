/**
 * Figure builder: centered mode toggle on top, then controls-LEFT (38%) /
 * preview-RIGHT (60%) row, the same sides as every other builder, the
 * preview sticking while the controls scroll. Mode toggle drives which
 * controls panel is shown; preview pane reads
 * `figureMode` to decide between live UI preview and the last code-mode
 * Execute result.
 */
import React, { Suspense, useEffect } from 'react';
import { Accordion, Box, Center, Loader, SegmentedControl, Stack, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useBuilderStore } from '../store/useBuilderStore';
import { useDashboardAccess } from '../../hooks/useDashboardAccess';
import CrossFilterSection from '../shared/CrossFilterSection';
import FigureUIMode from './FigureUIMode';
import FigurePreview from './FigurePreview';
import StickyPreview from '../shared/StickyPreview';

const FigureCodeMode = React.lazy(() => import('./FigureCodeMode'));

const TOGGLE_LABEL_STYLE: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 10,
  width: 250,
};

const FigureBuilder: React.FC = () => {
  const figureMode = useBuilderStore((s) => s.figureMode);
  const setFigureMode = useBuilderStore((s) => s.setFigureMode);
  const visuType = useBuilderStore((s) => s.visuType);
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const config = useBuilderStore((s) => s.config) as {
    selection_enabled?: boolean;
    selection_column?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  // Cross-filtering only makes sense for traces that carry per-row
  // customdata (scatter / scatter_3d). On aggregated visus we hide the
  // section so authors don't think they're configuring it. Renderer
  // mirrors the same gate.
  const supportsCrossFilter = visuType === 'scatter' || visuType === 'scatter_3d';
  const { canUseCodeMode } = useDashboardAccess(dashboardId);

  // Public/demo deployments shouldn't expose the server-side Python executor.
  // If a non-owner / public visitor lands on a component that was saved in
  // code mode, snap them back to the safe UI mode.
  useEffect(() => {
    if (!canUseCodeMode && figureMode === 'code') {
      setFigureMode('ui');
    }
  }, [canUseCodeMode, figureMode, setFigureMode]);

  return (
    <Stack gap="md" pt="md">
      <Center>
        <Tooltip
          label="Code Mode is unavailable in public / demo deployments."
          disabled={canUseCodeMode}
          withArrow
          position="bottom"
        >
          <SegmentedControl
            size="lg"
            value={figureMode}
            onChange={(val) => setFigureMode(val as 'ui' | 'code')}
            data={[
              {
                value: 'ui',
                label: (
                  <span style={TOGGLE_LABEL_STYLE}>
                    <Icon icon="tabler:eye" width={16} />
                    UI Mode
                  </span>
                ),
              },
              {
                value: 'code',
                disabled: !canUseCodeMode,
                label: (
                  <span style={TOGGLE_LABEL_STYLE}>
                    <Icon icon="tabler:code" width={16} />
                    Code Mode
                  </span>
                ),
              },
            ]}
          />
        </Tooltip>
      </Center>

      {/* Flex items stretch to the row, so the preview column is as tall as
          the controls and the preview has room to stick inside it. */}
      <Box style={{ display: 'flex', gap: '2%' }}>
        <Box
          style={{
            flex: '0 0 38%',
            minWidth: 0,
            minHeight: 400,
            padding: '0 var(--mantine-spacing-sm)',
            boxSizing: 'border-box',
          }}
        >
          {figureMode === 'ui' ? (
            <FigureUIMode />
          ) : (
            <Suspense fallback={<Loader size="sm" />}>
              <FigureCodeMode />
            </Suspense>
          )}
        </Box>
        <Box style={{ flex: '0 0 60%', minWidth: 0 }}>
          <StickyPreview>
            <Box
              component="div"
              style={{
                minHeight: 400,
                border: '1px solid var(--mantine-color-gray-3)',
                borderRadius: 'var(--mantine-radius-md)',
                padding: 'var(--mantine-spacing-sm)',
                boxSizing: 'border-box',
              }}
            >
              <FigurePreview />
            </Box>

            {/* In UI mode the cross-filter section is rendered inside the
             *  controls Accordion (see FigureUIMode) to match the other
             *  visualization config sections. In code mode the controls column
             *  is taken by the editor, so the section sits under the preview
             *  instead, in the same column directly below the chart, easy to
             *  reach without the eyes leaving the preview area. Gated to
             *  scatter-like visus only (see supportsCrossFilter above). */}
            {figureMode === 'code' && supportsCrossFilter && (
              <Accordion variant="separated" radius="md" multiple mt="sm">
                <CrossFilterSection
                  enabled={Boolean(config.selection_enabled)}
                  onEnabledChange={(checked) =>
                    patchConfig({ selection_enabled: checked })
                  }
                  column={config.selection_column}
                  onColumnChange={(name) => patchConfig({ selection_column: name })}
                  columnDescription="Column to extract from selected points"
                />
              </Accordion>
            )}
          </StickyPreview>
        </Box>
      </Box>
    </Stack>
  );
};

export default FigureBuilder;
