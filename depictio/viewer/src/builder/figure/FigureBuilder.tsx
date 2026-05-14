/**
 * Figure builder. Layout matches Dash's design_figure() in
 * depictio/dash/modules/figure_component/utils.py:2226+ — centered mode
 * toggle on top, then preview-LEFT (60%) / controls-RIGHT (38%) inline-block
 * row. Mode toggle drives which controls panel is shown; preview pane reads
 * `figureMode` to decide between live UI preview and the last code-mode
 * Execute result.
 */
import React, { Suspense } from 'react';
import { Accordion, Box, Center, Loader, SegmentedControl, Stack } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useBuilderStore } from '../store/useBuilderStore';
import CrossFilterSection from '../shared/CrossFilterSection';
import FigureUIMode from './FigureUIMode';
import FigurePreview from './FigurePreview';

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
  const config = useBuilderStore((s) => s.config) as {
    selection_enabled?: boolean;
    selection_column?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  return (
    <Stack gap="md" pt="md">
      <Center>
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
              label: (
                <span style={TOGGLE_LABEL_STYLE}>
                  <Icon icon="tabler:code" width={16} />
                  Code Mode (Beta)
                </span>
              ),
            },
          ]}
        />
      </Center>

      <Box style={{ width: '100%' }}>
        <Box
          component="div"
          style={{
            width: '60%',
            display: 'inline-block',
            verticalAlign: 'top',
            marginRight: '2%',
            minHeight: 400,
            border: '1px solid var(--mantine-color-gray-3)',
            borderRadius: 'var(--mantine-radius-md)',
            padding: 'var(--mantine-spacing-sm)',
            boxSizing: 'border-box',
          }}
        >
          <FigurePreview />
        </Box>
        <Box
          component="div"
          style={{
            width: '38%',
            display: 'inline-block',
            verticalAlign: 'top',
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
      </Box>

      {/* In UI mode the cross-filter section is rendered inside the right-
       *  panel Accordion (see FigureUIMode) to match the other visualization
       *  config sections. In code mode the right panel is taken by the
       *  editor, so the section is shown directly under the preview row. */}
      {figureMode === 'code' && (
        <Accordion variant="separated" radius="md" multiple>
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
    </Stack>
  );
};

export default FigureBuilder;
