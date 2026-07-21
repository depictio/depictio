/**
 * catalog-studio's figure builder. Replicates depictio's real
 * `viewer/src/builder/figure/FigureBuilder.tsx` layout verbatim — centered
 * UI/Code toggle, then preview-LEFT (60%) / controls-RIGHT (38%) — but:
 *  - the RIGHT panel reuses depictio's `FigureUIMode` unchanged (the whole
 *    parameter accordion — the substantive code — is reused as-is);
 *  - the LEFT preview is a client-side Plotly approximation (`FigureStorePreview`)
 *    in UI mode, or the Pyodide-executed figure in Code mode;
 *  - Code Mode runs Python in-browser via Pyodide (`FigureCodeModeLocal`)
 *    instead of depictio's backend executor.
 */
import { useMemo } from 'react';
import Plot from 'react-plotly.js';
import { Box, Center, SegmentedControl, Stack, Text, useComputedColorScheme } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useBuilderStore } from 'depictio-builder/store/useBuilderStore';
import FigureUIMode from 'depictio-builder/figure/FigureUIMode';
import type { ParsedFixture } from '../types';
import { buildPreview, isUnavailable } from '../viz/figureBuilder';
import { applyPlotlyTheme } from '../viz/plotlyTheme';
import FigureCodeModeLocal from './FigureCodeModeLocal';

const TOGGLE_LABEL_STYLE: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 10,
  width: 200,
};

// Shared 360px-high Plotly render used by both the UI-mode and code-mode previews.
function PreviewPlot({ figure }: { figure: { data: unknown[]; layout: Record<string, unknown> } }) {
  const scheme = useComputedColorScheme('light');
  return (
    <Plot
      data={figure.data as Plotly.Data[]}
      layout={applyPlotlyTheme({ ...figure.layout, height: 360 }, scheme) as Partial<Plotly.Layout>}
      config={{ displaylogo: false, responsive: true }}
      style={{ width: '100%', height: 360 }}
      useResizeHandler
    />
  );
}

// ── UI mode: live Plotly preview driven by the store's visuType/dictKwargs ───
function FigureStorePreview({ fixture }: { fixture: ParsedFixture }) {
  const visuType = useBuilderStore((s) => s.visuType);
  const dictKwargs = useBuilderStore((s) => s.dictKwargs);
  const result = useMemo(() => {
    const dict_kwargs: Record<string, string> = {};
    for (const [k, v] of Object.entries(dictKwargs)) {
      if (v === '' || v == null) continue;
      dict_kwargs[k] = typeof v === 'string' ? v : String(v);
    }
    return buildPreview(
      fixture,
      { uid: 'preview', component: 'figure', visu_type: visuType as never, dict_kwargs },
      () => false,
    );
  }, [fixture, visuType, dictKwargs]);

  if (isUnavailable(result)) {
    return (
      <Center h={360}>
        <Text c="dimmed" size="sm">
          <Icon icon="mdi:chart-box-outline" width={16} style={{ verticalAlign: 'middle' }} /> {result.reason}
        </Text>
      </Center>
    );
  }
  return (
    <>
      <PreviewPlot figure={result} />
      {result.ignoredParams && result.ignoredParams.length > 0 && (
        <Text size="xs" c="dimmed" ta="center" mt={4}>
          <Icon icon="mdi:information-outline" width={12} style={{ verticalAlign: 'middle' }} />{' '}
          Not shown in this preview (exported &amp; rendered by depictio): {result.ignoredParams.join(', ')}
        </Text>
      )}
    </>
  );
}

// ── Code mode: render the Pyodide-executed figure from the store ─────────────
function CodeFigurePreview() {
  const fig = useBuilderStore((s) => s.lastCodeFigure);
  if (!fig) {
    return (
      <Center h={360}>
        <Text c="dimmed" size="sm" ta="center" maw={320}>
          <Icon icon="tabler:code" width={16} style={{ verticalAlign: 'middle' }} /> Write Plotly code on the
          right and press <strong>Execute</strong> to run it in your browser.
        </Text>
      </Center>
    );
  }
  return <PreviewPlot figure={fig} />;
}

export default function FigureBuilderLocal({ fixture }: { fixture: ParsedFixture }) {
  const figureMode = useBuilderStore((s) => s.figureMode);
  const setFigureMode = useBuilderStore((s) => s.setFigureMode);

  return (
    <Stack gap="md" pt="xs">
      <Center>
        <SegmentedControl
          size="md"
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
                  Code Mode
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
            boxSizing: 'border-box',
          }}
        >
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
            {figureMode === 'code' ? <CodeFigurePreview /> : <FigureStorePreview fixture={fixture} />}
          </Box>
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
          {figureMode === 'code' ? <FigureCodeModeLocal fixture={fixture} /> : <FigureUIMode hideCrossFilter />}
        </Box>
      </Box>
    </Stack>
  );
}
