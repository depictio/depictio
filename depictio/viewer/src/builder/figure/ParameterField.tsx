/**
 * Renders a single Plotly Express parameter row inside the figure UI mode
 * accordion. Mirrors `figure_component/component_builder.py:ComponentBuilder`
 * — switches on the discovered ParameterType and emits the matching Mantine
 * input bound to dictKwargs in the builder store.
 *
 * Handles all Dash parameter types: column, select, multi_select, string,
 * integer, float, boolean, range, color. Special-cases `hover_data` /
 * `custom_data` (column lists) and `features` (numeric-only with Select All).
 */
import React, { useMemo } from 'react';
import {
  Anchor,
  Button,
  Checkbox,
  Code,
  ColorInput,
  Group,
  HoverCard,
  MultiSelect,
  NumberInput,
  Select,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import type { FigureParameterSpec } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';

interface Props {
  param: FigureParameterSpec;
}

const NUMERIC_TYPES = new Set([
  'int64',
  'int32',
  'float64',
  'float32',
  'number',
  'numeric',
]);

// Visualization types that map 1:1 to a Plotly Express function and therefore
// have a stable docs URL. Custom builders (heatmap → ComplexHeatmap, umap)
// don't, so we hide the doc link for those.
const PLOTLY_EXPRESS_VIZ = new Set([
  'scatter',
  'line',
  'bar',
  'histogram',
  'box',
  'violin',
  'ecdf',
  'area',
  'funnel',
  'density_heatmap',
  'density_contour',
  'scatter_matrix',
  'strip',
]);

function plotlyDocsUrl(visuType: string): string | null {
  if (!PLOTLY_EXPRESS_VIZ.has(visuType)) return null;
  return `https://plotly.com/python-api-reference/generated/plotly.express.${visuType}.html`;
}

const ParameterField: React.FC<Props> = ({ param }) => {
  const cols = useBuilderStore((s) => s.cols);
  const dictKwargs = useBuilderStore((s) => s.dictKwargs);
  const patchDictKwargs = useBuilderStore((s) => s.patchDictKwargs);
  const visuType = useBuilderStore((s) => s.visuType);

  const value = dictKwargs[param.name];
  const docsUrl = plotlyDocsUrl(visuType);

  const colOptions = useMemo(
    () => cols.map((c) => ({ value: c.name, label: `${c.name} (${c.type})` })),
    [cols],
  );
  const numericColOptions = useMemo(
    () =>
      cols
        .filter((c) => NUMERIC_TYPES.has(c.type))
        .map((c) => ({ value: c.name, label: `${c.name} (${c.type})` })),
    [cols],
  );

  // The visible field label is the human name (e.g. "X axis"). Hovering it
  // opens a card with the original Plotly parameter name, the description,
  // and a link to the Plotly Express API reference. HoverCard (not Tooltip)
  // because the user needs to be able to click the docs link without it
  // dismissing on mouse-leave.
  const labelNode = (
    <Text
      size="sm"
      fw={700}
      style={{
        cursor: 'help',
        textDecoration: 'underline dotted',
      }}
    >
      {param.label}
    </Text>
  );

  const wrappedLabel = (
    <HoverCard
      width={300}
      shadow="md"
      position="top"
      withArrow
      openDelay={200}
      closeDelay={100}
    >
      <HoverCard.Target>{labelNode}</HoverCard.Target>
      <HoverCard.Dropdown>
        <Stack gap="xs">
          {param.description && <Text size="xs">{param.description}</Text>}
          <Group gap="xs" wrap="nowrap">
            <Text size="xs" c="dimmed">
              Plotly param:
            </Text>
            <Code>{param.name}</Code>
          </Group>
          {docsUrl && (
            <Anchor
              href={`${docsUrl}#plotly.express.${visuType}`}
              target="_blank"
              rel="noopener noreferrer"
              size="xs"
            >
              <Group gap={4} wrap="nowrap">
                <span>API reference</span>
                <Icon icon="mdi:open-in-new" width={12} />
              </Group>
            </Anchor>
          )}
        </Stack>
      </HoverCard.Dropdown>
    </HoverCard>
  );

  let input: React.ReactNode;

  switch (param.type) {
    case 'column': {
      input = (
        <Select
          data={colOptions}
          value={typeof value === 'string' ? value : null}
          onChange={(v) => patchDictKwargs({ [param.name]: v })}
          placeholder={`Select ${param.label.toLowerCase()}...`}
          clearable={!param.required}
          searchable
          comboboxProps={{ withinPortal: false }}
          style={{ width: '100%' }}
          leftSection={<Icon icon="mdi:table-column" width={14} />}
        />
      );
      break;
    }
    case 'select': {
      const opts = (param.options || []).map((o) => ({
        value: String(o),
        label: String(o),
      }));
      input = (
        <Select
          data={opts}
          value={value != null ? String(value) : null}
          onChange={(v) => patchDictKwargs({ [param.name]: v })}
          placeholder={`Select ${param.label.toLowerCase()}...`}
          clearable={!param.required}
          searchable
          comboboxProps={{ withinPortal: false }}
          style={{ width: '100%' }}
        />
      );
      break;
    }
    case 'multi_select': {
      // Param names that should pull from the dataset's columns instead of a
      // fixed enum. `features` and `dimensions` (scatter_matrix) are
      // numeric-only with a Select All shortcut; `hover_data` / `custom_data`
      // accept any column.
      const isColList =
        param.name === 'hover_data' ||
        param.name === 'custom_data' ||
        param.name === 'features' ||
        param.name === 'dimensions';
      const isNumericColList =
        param.name === 'features' || param.name === 'dimensions';
      const opts = isColList
        ? isNumericColList
          ? numericColOptions
          : colOptions
        : (param.options || []).map((o) => ({
            value: String(o),
            label: String(o),
          }));
      const arr = Array.isArray(value) ? (value as string[]) : [];
      const sel = (
        <MultiSelect
          data={opts}
          value={arr}
          onChange={(v) => patchDictKwargs({ [param.name]: v })}
          placeholder={`Select ${param.label.toLowerCase()}...`}
          searchable
          comboboxProps={{ withinPortal: false }}
          style={{ width: '100%', flex: 1 }}
        />
      );
      input = isNumericColList ? (
        <Group gap="xs" wrap="nowrap" style={{ width: '100%' }}>
          {sel}
          <Button
            size="xs"
            variant="outline"
            leftSection={<Icon icon="mdi:select-all" width={14} />}
            onClick={() =>
              patchDictKwargs({
                [param.name]: numericColOptions.map((o) => o.value),
              })
            }
          >
            Select All
          </Button>
        </Group>
      ) : (
        sel
      );
      break;
    }
    case 'string': {
      input = (
        <TextInput
          value={typeof value === 'string' ? value : ''}
          onChange={(e) =>
            patchDictKwargs({ [param.name]: e.currentTarget.value })
          }
          placeholder={param.label}
          style={{ width: '100%' }}
          leftSection={<Icon icon="mdi:format-text" width={14} />}
        />
      );
      break;
    }
    case 'integer':
    case 'float': {
      const isInt = param.type === 'integer';
      input = (
        <NumberInput
          value={typeof value === 'number' ? value : (value as number) ?? ''}
          onChange={(v) =>
            patchDictKwargs({ [param.name]: v === '' ? null : v })
          }
          step={isInt ? 1 : 0.1}
          min={param.min_value ?? undefined}
          max={param.max_value ?? undefined}
          decimalScale={isInt ? 0 : undefined}
          allowDecimal={!isInt}
          style={{ width: '100%' }}
          leftSection={
            <Icon icon={isInt ? 'mdi:numeric' : 'mdi:decimal'} width={14} />
          }
        />
      );
      break;
    }
    case 'boolean': {
      input = (
        <Checkbox
          checked={Boolean(value)}
          onChange={(e) =>
            patchDictKwargs({ [param.name]: e.currentTarget.checked })
          }
          label={param.description || ''}
        />
      );
      break;
    }
    case 'range': {
      const arr = Array.isArray(value) ? (value as Array<number | null>) : [];
      const lo = arr[0];
      const hi = arr[1];
      input = (
        <Group gap="xs" wrap="nowrap">
          <NumberInput
            placeholder="Min"
            value={typeof lo === 'number' ? lo : ''}
            onChange={(v) => {
              const next: Array<number | null> = [
                v === '' ? null : (v as number),
                typeof hi === 'number' ? hi : null,
              ];
              const clean =
                next[0] == null && next[1] == null ? null : next;
              patchDictKwargs({ [param.name]: clean });
            }}
            style={{ width: 130 }}
            leftSection={<Icon icon="mdi:decimal" width={14} />}
          />
          <NumberInput
            placeholder="Max"
            value={typeof hi === 'number' ? hi : ''}
            onChange={(v) => {
              const next: Array<number | null> = [
                typeof lo === 'number' ? lo : null,
                v === '' ? null : (v as number),
              ];
              const clean =
                next[0] == null && next[1] == null ? null : next;
              patchDictKwargs({ [param.name]: clean });
            }}
            style={{ width: 130 }}
            leftSection={<Icon icon="mdi:decimal" width={14} />}
          />
        </Group>
      );
      break;
    }
    case 'color': {
      input = (
        <ColorInput
          value={typeof value === 'string' ? value : '#1f77b4'}
          onChange={(v) => patchDictKwargs({ [param.name]: v })}
          style={{ width: '100%' }}
        />
      );
      break;
    }
    default: {
      input = (
        <Text size="xs" c="dimmed">
          Unsupported parameter type: {param.type}
        </Text>
      );
    }
  }

  // Boolean rows put the description on the input itself, so the row label
  // above is just the param name. Other types use the standard 30/70 split.
  if (param.type === 'boolean') {
    return (
      <Group gap="md" align="center" wrap="nowrap" style={{ width: '100%' }}>
        <div style={{ width: '30%', flexShrink: 0 }}>{wrappedLabel}</div>
        <div style={{ flex: 1 }}>{input}</div>
      </Group>
    );
  }

  return (
    <Group gap="md" align="center" wrap="nowrap" style={{ width: '100%' }}>
      <div style={{ width: '30%', flexShrink: 0 }}>{wrappedLabel}</div>
      <div style={{ flex: 1 }}>{input}</div>
    </Group>
  );
};

export default ParameterField;
