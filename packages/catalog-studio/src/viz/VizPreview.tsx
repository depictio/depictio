import { useMemo } from 'react';
import Plot from 'react-plotly.js';
import { Alert, Center, Paper, Text, ScrollArea, Table, useComputedColorScheme } from '@mantine/core';
import { Icon } from '@iconify/react';
import { DepictioCard } from 'depictio-components';
import type { KindsMap, ParsedFixture, RenderSpec } from '../types';
import { buildPreview, isUnavailable } from './figureBuilder';
import { applyPlotlyTheme } from './plotlyTheme';
import { computeCard } from './cardCompute';
import { makeIsHeavy } from '../catalog/kinds';

interface Props {
  fixture: ParsedFixture;
  render: RenderSpec;
  kinds: KindsMap;
  height?: number;
}

/** Badge shown when a heavy advanced_viz can't be previewed client-side. */
function Unavailable({ reason }: { reason: string }) {
  return (
    <Alert color="yellow" variant="light" icon={<Icon icon="mdi:eye-off-outline" />} title="Preview unavailable">
      <Text size="sm">{reason}</Text>
      <Text size="xs" c="dimmed" mt={4}>
        The binding still exports and is validated in CI — verify the render in depictio.
      </Text>
    </Alert>
  );
}

export default function VizPreview({ fixture, render, kinds, height = 320 }: Props) {
  const isHeavy = useMemo(() => makeIsHeavy(kinds), [kinds]);
  const scheme = useComputedColorScheme('light');

  if (render.component === 'card') {
    const value = computeCard(fixture.rows, render.column, render.aggregation);
    const display = typeof value === 'number' && Number.isNaN(value) ? '—' : value;
    return (
      <div style={{ maxWidth: 280 }}>
        <DepictioCard
          title={`${render.aggregation} of ${render.column}`}
          value={display}
          aggregation_description={`(${render.aggregation})`}
        />
      </div>
    );
  }

  if (render.component === 'table') {
    const cols = fixture.columns.slice(0, 12);
    return (
      <Paper withBorder radius="md" p="xs">
        <ScrollArea type="auto" h={height}>
          <Table striped fz="xs" stickyHeader>
            <Table.Thead>
              <Table.Tr>
                {cols.map((c) => (
                  <Table.Th key={c.name}>{c.name}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {fixture.rows.slice(0, 50).map((row, i) => (
                <Table.Tr key={i}>
                  {cols.map((c) => (
                    <Table.Td key={c.name}>{String(row[c.name] ?? '')}</Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Paper>
    );
  }

  if (render.component === 'figure' && render.code) {
    // Code-mode figure: render the Plotly figure produced by executing the
    // snippet in Code Mode (client-side). Only falls back to a note if it was
    // added without executing.
    if (render._previewFigure) {
      return (
        <Plot
          data={render._previewFigure.data as Plotly.Data[]}
          layout={applyPlotlyTheme({ ...render._previewFigure.layout, height }, scheme) as Partial<Plotly.Layout>}
          config={{ displaylogo: false, responsive: true }}
          style={{ width: '100%', height }}
          useResizeHandler
        />
      );
    }
    return (
      <Center h={height}>
        <div style={{ width: '100%', maxWidth: 420 }}>
          <Alert color="gray" variant="light" icon={<Icon icon="tabler:code" width={18} />} title="Code-mode figure">
            <Text size="sm">Open this card in Code Mode and press Execute to render the figure.</Text>
          </Alert>
        </div>
      </Center>
    );
  }

  if (render.component === 'interactive') {
    // Interactive is a component-only catalog render (no binding is exported),
    // so there's nothing to plot — show a neutral placeholder, not the
    // "preview unavailable / verify in depictio" warning used for heavy viz.
    return (
      <Center h={height}>
        <div style={{ width: '100%', maxWidth: 420 }}>
          <Alert color="gray" variant="light" icon={<Icon icon="mdi:filter-variant" />} title="Interactive filter">
            <Text size="sm">Rendered as an interactive filter control by depictio at dashboard time.</Text>
            <Text size="xs" c="dimmed" mt={4}>
              The catalog entry is a bare <code>{'{ component: interactive }'}</code>.
            </Text>
          </Alert>
        </div>
      </Center>
    );
  }

  const result = buildPreview(fixture, render, isHeavy);
  if (isUnavailable(result)) {
    return (
      <Center h={height}>
        <div style={{ width: '100%', maxWidth: 420 }}>
          <Unavailable reason={result.reason} />
        </div>
      </Center>
    );
  }
  return (
    <Plot
      data={result.data as Plotly.Data[]}
      layout={applyPlotlyTheme({ ...result.layout, height }, scheme) as Partial<Plotly.Layout>}
      config={{ displaylogo: false, responsive: true }}
      style={{ width: '100%', height }}
      useResizeHandler
    />
  );
}
