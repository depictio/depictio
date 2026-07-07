/**
 * Right column: design a viz on the active file. Three sources, one output — a
 * `VizSpec` handed up to the shell for live preview + the cart:
 *
 *  • Existing  — catalog renders recognised for this file (one click).
 *  • Suggested — ranked viz kinds from the schema (suggest_viz_kinds).
 *  • Create    — a minimal builder (figure / card / table) on the columns.
 */
import React, { useMemo, useState } from 'react';
import { Badge, Button, Group, Select, Stack, Tabs, Text, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { PreviewData, RecognizeResult, VizSuggestion } from './backend';
import type { VizSpec } from './spec';
import { specLabel } from './spec';

const AGGREGATIONS = ['average', 'median', 'sum', 'min', 'max', 'count', 'nunique', 'std_dev'];
const FIGURE_TYPES = ['scatter', 'line', 'bar', 'histogram', 'box', 'violin', 'density_heatmap'];

interface Props {
  preview: PreviewData | null;
  recognize: RecognizeResult | null;
  suggestions: VizSuggestion[];
  onPreview: (spec: VizSpec) => void;
  onAdd: (spec: VizSpec) => void;
}

function renderToSpec(render: Record<string, unknown>): VizSpec | null {
  const component = render.component as string;
  if (component === 'figure' && render.visu_type)
    return {
      component: 'figure',
      visu_type: String(render.visu_type),
      dict_kwargs: (render.dict_kwargs as Record<string, string>) || {},
    };
  if (component === 'card' && render.column && render.aggregation)
    return {
      component: 'card',
      column: String(render.column),
      aggregation: String(render.aggregation),
    };
  if (component === 'table') return { component: 'table' };
  if (component === 'advanced_viz' && render.kind)
    return {
      component: 'advanced_viz',
      kind: String(render.kind),
      roles: (render.roles as Record<string, string>) || {},
    };
  return null;
}

const SpecRow: React.FC<{ spec: VizSpec; onPreview: (s: VizSpec) => void; onAdd: (s: VizSpec) => void }> = ({
  spec,
  onPreview,
  onAdd,
}) => (
  <Group justify="space-between" wrap="nowrap">
    <Badge variant="light" radius="sm" tt="none">
      {specLabel(spec)}
    </Badge>
    <Group gap={4} wrap="nowrap">
      <Button size="compact-xs" variant="subtle" onClick={() => onPreview(spec)}>
        Preview
      </Button>
      <Button
        size="compact-xs"
        variant="light"
        leftSection={<Icon icon="mdi:plus" width={12} />}
        onClick={() => onAdd(spec)}
      >
        Add
      </Button>
    </Group>
  </Group>
);

const CreateTab: React.FC<{ columns: string[]; onPreview: (s: VizSpec) => void; onAdd: (s: VizSpec) => void }> = ({
  columns,
  onPreview,
  onAdd,
}) => {
  const [kind, setKind] = useState<'figure' | 'card' | 'table'>('figure');
  const [visuType, setVisuType] = useState('scatter');
  const [x, setX] = useState<string | null>(columns[0] ?? null);
  const [y, setY] = useState<string | null>(columns[1] ?? null);
  const [color, setColor] = useState<string | null>(null);
  const [column, setColumn] = useState<string | null>(columns[0] ?? null);
  const [aggregation, setAggregation] = useState('average');

  const spec = useMemo<VizSpec | null>(() => {
    if (kind === 'table') return { component: 'table' };
    if (kind === 'card')
      return column ? { component: 'card', column, aggregation } : null;
    // figure
    if (!x) return null;
    const dict: Record<string, string> = { x };
    if (y) dict.y = y;
    if (color) dict.color = color;
    return { component: 'figure', visu_type: visuType, dict_kwargs: dict };
  }, [kind, visuType, x, y, color, column, aggregation]);

  const colOpts = columns.map((c) => ({ value: c, label: c }));

  return (
    <Stack gap="sm" pt="sm">
      <Select
        label="Component"
        data={['figure', 'card', 'table']}
        value={kind}
        onChange={(v) => setKind((v as 'figure' | 'card' | 'table') ?? 'figure')}
        allowDeselect={false}
      />
      {kind === 'figure' && (
        <>
          <Select label="Chart type" data={FIGURE_TYPES} value={visuType} onChange={(v) => setVisuType(v ?? 'scatter')} allowDeselect={false} />
          <Select label="X" data={colOpts} value={x} onChange={setX} searchable />
          <Select label="Y" data={colOpts} value={y} onChange={setY} searchable clearable />
          <Select label="Color" data={colOpts} value={color} onChange={setColor} searchable clearable />
        </>
      )}
      {kind === 'card' && (
        <>
          <Select label="Column" data={colOpts} value={column} onChange={setColumn} searchable />
          <Select label="Aggregation" data={AGGREGATIONS} value={aggregation} onChange={(v) => setAggregation(v ?? 'average')} allowDeselect={false} />
        </>
      )}
      <Group>
        <Button size="xs" variant="subtle" disabled={!spec} onClick={() => spec && onPreview(spec)}>
          Preview
        </Button>
        <Button size="xs" variant="light" leftSection={<Icon icon="mdi:plus" width={14} />} disabled={!spec} onClick={() => spec && onAdd(spec)}>
          Add to cart
        </Button>
      </Group>
    </Stack>
  );
};

const Designer: React.FC<Props> = ({ preview, recognize, suggestions, onPreview, onAdd }) => {
  if (!preview)
    return (
      <Text size="sm" c="dimmed" p="md">
        Pick a file to design a visualization.
      </Text>
    );

  const existing = (recognize?.catalog_renders || [])
    .map(renderToSpec)
    .filter((s): s is VizSpec => s != null);

  return (
    <Tabs defaultValue={existing.length ? 'existing' : 'create'} p="sm">
      <Tabs.List>
        <Tabs.Tab value="existing" disabled={!existing.length}>
          Existing {existing.length ? `(${existing.length})` : ''}
        </Tabs.Tab>
        <Tabs.Tab value="suggested">Suggested</Tabs.Tab>
        <Tabs.Tab value="create">Create</Tabs.Tab>
      </Tabs.List>

      <Tabs.Panel value="existing" pt="sm">
        <Stack gap="xs">
          {existing.length ? (
            existing.map((s, i) => <SpecRow key={i} spec={s} onPreview={onPreview} onAdd={onAdd} />)
          ) : (
            <Text size="sm" c="dimmed">
              No recognised catalog visualizations for this file.
            </Text>
          )}
        </Stack>
      </Tabs.Panel>

      <Tabs.Panel value="suggested" pt="sm">
        <Stack gap="xs">
          {suggestions.slice(0, 8).map((s) => {
            const roles: Record<string, string> = {};
            for (const [role, cands] of Object.entries(s.role_candidates)) {
              if (cands.length) roles[role] = cands[0];
            }
            const spec: VizSpec = { component: 'advanced_viz', kind: s.viz_kind, roles };
            return (
              <Group key={s.viz_kind} justify="space-between" wrap="nowrap">
                <Group gap={6} wrap="nowrap">
                  <Badge variant="light" radius="sm" tt="none">
                    {s.viz_kind}
                  </Badge>
                  <Text size="xs" c="dimmed">
                    {(s.score * 100).toFixed(0)}%
                  </Text>
                </Group>
                <Group gap={4} wrap="nowrap">
                  <Button size="compact-xs" variant="subtle" onClick={() => onPreview(spec)}>
                    Preview
                  </Button>
                  <Button size="compact-xs" variant="light" onClick={() => onAdd(spec)}>
                    Add
                  </Button>
                </Group>
              </Group>
            );
          })}
        </Stack>
      </Tabs.Panel>

      <Tabs.Panel value="create">
        <CreateTab columns={preview.columns} onPreview={onPreview} onAdd={onAdd} />
      </Tabs.Panel>
    </Tabs>
  );
};

export default Designer;
