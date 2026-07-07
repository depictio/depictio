import { useMemo } from 'react';
import Plot from 'react-plotly.js';
import { Alert, Center, Paper, Text, ScrollArea, Table } from '@mantine/core';
import { Icon } from '@iconify/react';
import { DepictioCard } from 'depictio-components';
import type { KindsMap, ParsedFixture, RenderSpec } from '../types';
import { buildPreview, isUnavailable } from './figureBuilder';
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
      layout={{ ...result.layout, height } as Partial<Plotly.Layout>}
      config={{ displaylogo: false, responsive: true }}
      style={{ width: '100%', height }}
      useResizeHandler
    />
  );
}
