import { Stack, Title, Text, Button, Menu, Paper, Group, Select, ActionIcon, Badge, Alert, SimpleGrid, Grid } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useStudioStore, nextUid } from '../state/useStudioStore';
import VizPreview from '../viz/VizPreview';
import { validateRender } from '../catalog/grounding';
import { CLIENT_AGGREGATIONS } from '../viz/cardCompute';
import type {
  AdvancedVizRender,
  CardRender,
  FigureRender,
  FigureVisuType,
  KindsMap,
  RenderSpec,
} from '../types';

const VISU_TYPES: FigureVisuType[] = ['scatter', 'line', 'bar', 'box', 'histogram', 'heatmap'];
// The plotly-express kwargs we surface as bindable dropdowns in the designer.
const FIGURE_BINDABLE: string[] = ['x', 'y', 'color', 'facet_col', 'size', 'symbol'];

export default function VizDesigner({ kinds }: { kinds: KindsMap }) {
  const fixture = useStudioStore((s) => s.fixture);
  const renders = useStudioStore((s) => s.renders);
  const addRender = useStudioStore((s) => s.addRender);
  const removeRender = useStudioStore((s) => s.removeRender);

  if (!fixture) return <Text c="dimmed">Drop a fixture first.</Text>;
  const colNames = fixture.columns.map((c) => c.name);

  const addFigure = () =>
    addRender({ uid: nextUid(), component: 'figure', visu_type: 'bar', dict_kwargs: {} } as FigureRender);
  const addCard = () =>
    addRender({ uid: nextUid(), component: 'card', column: colNames[0] ?? '', aggregation: 'average' } as CardRender);
  const addTable = () => addRender({ uid: nextUid(), component: 'table' } as RenderSpec);
  const addAdvanced = (kind: string) =>
    addRender({ uid: nextUid(), component: 'advanced_viz', kind, roles: {} } as AdvancedVizRender);

  const kindEntries = Object.entries(kinds).sort((a, b) => a[0].localeCompare(b[0]));

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={3} style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
            Visualizations
          </Title>
          <Text c="dimmed" size="sm">
            Bind fixture columns to dashboard components. Previews are client-side approximations.
          </Text>
        </div>
        <Menu shadow="md" width={240}>
          <Menu.Target>
            <Button leftSection={<Icon icon="mdi:plus" />} color="blue">
              Add visualization
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Label>Basic</Menu.Label>
            <Menu.Item leftSection={<Icon icon="mdi:chart-bar" />} onClick={addFigure}>
              Figure
            </Menu.Item>
            <Menu.Item leftSection={<Icon icon="mdi:card-text-outline" />} onClick={addCard}>
              Card (metric)
            </Menu.Item>
            <Menu.Item leftSection={<Icon icon="mdi:table" />} onClick={addTable}>
              Table
            </Menu.Item>
            <Menu.Divider />
            <Menu.Label>Advanced viz</Menu.Label>
            <ScrollableKindList entries={kindEntries} onPick={addAdvanced} />
          </Menu.Dropdown>
        </Menu>
      </Group>

      {renders.length === 0 && (
        <Alert color="blue" variant="light" icon={<Icon icon="mdi:information-outline" />}>
          No visualizations yet. Add at least one to continue.
        </Alert>
      )}

      <Stack gap="md">
        {renders.map((render) => (
          <RenderCard
            key={render.uid}
            render={render}
            colNames={colNames}
            kinds={kinds}
            onRemove={() => removeRender(render.uid)}
          />
        ))}
      </Stack>
    </Stack>
  );
}

function ScrollableKindList({
  entries,
  onPick,
}: {
  entries: [string, KindsMap[string]][];
  onPick: (kind: string) => void;
}) {
  return (
    <div style={{ maxHeight: 260, overflowY: 'auto' }}>
      {entries.map(([kind, desc]) => (
        <Menu.Item
          key={kind}
          onClick={() => onPick(kind)}
          rightSection={
            desc.heavy ? (
              <Badge size="xs" color="orange" variant="light">
                heavy
              </Badge>
            ) : null
          }
        >
          {desc.label}
        </Menu.Item>
      ))}
    </div>
  );
}

function RenderCard({
  render,
  colNames,
  kinds,
  onRemove,
}: {
  render: RenderSpec;
  colNames: string[];
  kinds: KindsMap;
  onRemove: () => void;
}) {
  const fixture = useStudioStore((s) => s.fixture)!;
  const issues = validateRender(render, fixture.columns, kinds);
  const errors = issues.filter((i) => i.severity === 'error');

  const title =
    render.component === 'advanced_viz'
      ? kinds[render.kind]?.label ?? render.kind
      : render.component === 'figure'
        ? `Figure · ${render.visu_type}`
        : render.component === 'card'
          ? 'Card'
          : 'Table';

  return (
    <Paper withBorder radius="md" p="md">
      <Group justify="space-between" mb="sm">
        <Group gap="xs">
          <Icon icon={iconFor(render)} width={20} />
          <Text fw={600}>{title}</Text>
          {errors.length > 0 && (
            <Badge color="red" variant="light" size="sm">
              {errors.length} issue{errors.length > 1 ? 's' : ''}
            </Badge>
          )}
        </Group>
        <ActionIcon variant="subtle" color="red" onClick={onRemove} aria-label="Remove">
          <Icon icon="mdi:trash-can-outline" />
        </ActionIcon>
      </Group>

      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, md: 5 }}>
          <RenderEditor render={render} colNames={colNames} kinds={kinds} />
          {issues.length > 0 && (
            <Stack gap={4} mt="sm">
              {issues.map((i, k) => (
                <Text key={k} size="xs" c={i.severity === 'error' ? 'red' : 'orange'}>
                  <Icon icon={i.severity === 'error' ? 'mdi:alert-circle' : 'mdi:alert'} width={12} style={{ verticalAlign: 'middle' }} /> {i.message}
                </Text>
              ))}
            </Stack>
          )}
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Paper withBorder radius="sm" p="xs" bg="var(--app-subtle-bg)">
            <VizPreview fixture={fixture} render={render} kinds={kinds} height={300} />
          </Paper>
        </Grid.Col>
      </Grid>
    </Paper>
  );
}

function iconFor(render: RenderSpec): string {
  if (render.component === 'card') return 'mdi:card-text-outline';
  if (render.component === 'table') return 'mdi:table';
  if (render.component === 'advanced_viz') return 'mdi:chart-scatter-plot';
  return 'mdi:chart-bar';
}

function RenderEditor({
  render,
  colNames,
  kinds,
}: {
  render: RenderSpec;
  colNames: string[];
  kinds: KindsMap;
}) {
  const updateRender = useStudioStore((s) => s.updateRender);
  const colOptions = colNames.map((c) => ({ value: c, label: c }));
  const clearable = [{ value: '', label: '— none —' }, ...colOptions];

  if (render.component === 'figure') {
    return (
      <Stack gap="xs">
        <Select
          label="Visualization"
          data={VISU_TYPES.map((v) => ({ value: v, label: v }))}
          value={render.visu_type}
          onChange={(v) => v && updateRender(render.uid, { visu_type: v as FigureVisuType })}
          allowDeselect={false}
        />
        <SimpleGrid cols={2}>
          {FIGURE_BINDABLE.map((kw) => (
            <Select
              key={kw}
              label={kw}
              placeholder="—"
              data={clearable}
              value={render.dict_kwargs[kw] ?? ''}
              searchable
              onChange={(v) => {
                const dict = { ...render.dict_kwargs };
                if (v) dict[kw] = v;
                else delete dict[kw];
                updateRender(render.uid, { dict_kwargs: dict });
              }}
            />
          ))}
        </SimpleGrid>
      </Stack>
    );
  }

  if (render.component === 'card') {
    return (
      <Stack gap="xs">
        <Select
          label="Column"
          data={colOptions}
          value={render.column}
          searchable
          onChange={(v) => v && updateRender(render.uid, { column: v })}
        />
        <Select
          label="Aggregation"
          data={CLIENT_AGGREGATIONS.map((a) => ({ value: a, label: a }))}
          value={render.aggregation}
          onChange={(v) => v && updateRender(render.uid, { aggregation: v as CardRender['aggregation'] })}
          allowDeselect={false}
        />
      </Stack>
    );
  }

  if (render.component === 'table') {
    return <Text size="sm" c="dimmed">Renders the fixture as-is. No binding needed.</Text>;
  }

  // advanced_viz — one dropdown per role
  const desc = kinds[render.kind];
  if (!desc) return <Text size="sm" c="red">Unknown kind.</Text>;
  const roleNames = Object.keys(desc.roles);
  return (
    <Stack gap="xs">
      {desc.heavy && (
        <Badge color="orange" variant="light">
          heavy — no client preview
        </Badge>
      )}
      {roleNames.map((role) => {
        const required = desc.required_roles.includes(role);
        return (
          <Select
            key={role}
            label={role}
            withAsterisk={required}
            description={desc.roles[role].join(' / ')}
            placeholder="—"
            data={clearable}
            value={render.roles[role] ?? ''}
            searchable
            onChange={(v) => {
              const roles = { ...render.roles };
              if (v) roles[role] = v;
              else delete roles[role];
              updateRender(render.uid, { roles });
            }}
          />
        );
      })}
    </Stack>
  );
}
