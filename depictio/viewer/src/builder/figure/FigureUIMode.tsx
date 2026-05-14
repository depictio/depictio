/**
 * Figure UI mode panel — visualization Select + parameter accordion.
 *
 * Mirrors the right-column controls Dash builds in design_figure() and the
 * accordion structure produced by AccordionBuilder. Parameter spec comes
 * from the backend (`/figure/parameter-discovery/{viz_type}`) so the form
 * stays in lockstep with figure_component/parameter_discovery.py.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  Alert,
  Group,
  Loader,
  Select,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  fetchFigureParameterDiscovery,
  fetchFigureVisualizationList,
} from 'depictio-react-core';
import type {
  FigureParameterCategory,
  FigureParameterSpec,
  FigureVisualizationDefinition,
} from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import {
  VISU_TYPES_FALLBACK,
  buildVisuSelectOptions,
  getVisuTypeMeta,
  summariesToVisuMeta,
} from './visuTypes';
import ParameterField from './ParameterField';
import CrossFilterSection from '../shared/CrossFilterSection';

type CategoryKey = 'core' | 'common' | 'specific' | 'advanced';

interface CategoryDef {
  key: CategoryKey;
  category: FigureParameterCategory;
  title: string;
  icon: string;
}

const FIXED_CATEGORIES: CategoryDef[] = [
  {
    key: 'core',
    category: 'core',
    title: 'Core Parameters',
    icon: 'mdi:cog',
  },
  {
    key: 'common',
    category: 'common',
    title: 'Styling & Layout',
    icon: 'mdi:palette',
  },
  {
    key: 'advanced',
    category: 'advanced',
    title: 'Advanced Options',
    icon: 'mdi:tune',
  },
];

const FigureUIMode: React.FC = () => {
  const visuType = useBuilderStore((s) => s.visuType);
  const setVisuType = useBuilderStore((s) => s.setVisuType);
  const figureParamSpecs = useBuilderStore((s) => s.figureParamSpecs);
  const setFigureParamSpec = useBuilderStore((s) => s.setFigureParamSpec);
  const figureVisualizationList = useBuilderStore(
    (s) => s.figureVisualizationList,
  );
  const setFigureVisualizationList = useBuilderStore(
    (s) => s.setFigureVisualizationList,
  );
  const config = useBuilderStore((s) => s.config) as {
    selection_enabled?: boolean;
    selection_column?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch the curated viz list once on mount. The fetch is idempotent —
  // store cache prevents repeats across re-renders, and a fetch failure
  // falls back to the static `VISU_TYPES_FALLBACK` so the UI never blanks.
  useEffect(() => {
    if (figureVisualizationList !== null) return;
    let cancelled = false;
    fetchFigureVisualizationList()
      .then((list) => {
        if (cancelled) return;
        setFigureVisualizationList(list);
      })
      .catch((err) => {
        if (cancelled) return;
        // eslint-disable-next-line no-console
        console.warn(
          'Failed to fetch /figure/visualizations — using fallback list:',
          err,
        );
        setFigureVisualizationList([]); // mark "tried" so we don't loop
      });
    return () => {
      cancelled = true;
    };
  }, [figureVisualizationList, setFigureVisualizationList]);

  const cachedSpec: FigureVisualizationDefinition | undefined =
    figureParamSpecs[visuType.toLowerCase()];

  useEffect(() => {
    if (!visuType) return;
    if (cachedSpec) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchFigureParameterDiscovery(visuType)
      .then((spec) => {
        if (cancelled) return;
        setFigureParamSpec(visuType, spec);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        // Always clear the loading flag — `cancelled` exists to gate stale
        // data writes, not the UI flag. When the spec lands, React re-runs the
        // effect because `cachedSpec` is in the deps array; the cleanup flips
        // `cancelled` to true before this `.finally` resolves, which would
        // otherwise leave the spinner spinning forever.
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [visuType, cachedSpec, setFigureParamSpec]);

  const visuList = useMemo(
    () =>
      figureVisualizationList && figureVisualizationList.length > 0
        ? summariesToVisuMeta(figureVisualizationList)
        : VISU_TYPES_FALLBACK,
    [figureVisualizationList],
  );
  const visuOptions = useMemo(
    () => buildVisuSelectOptions(visuList),
    [visuList],
  );
  const visuMeta = getVisuTypeMeta(visuType, visuList);

  const params = cachedSpec?.parameters ?? [];
  const byCategory: Record<FigureParameterCategory, FigureParameterSpec[]> = {
    core: [],
    common: [],
    specific: [],
    advanced: [],
  };
  for (const p of params) {
    if (byCategory[p.category]) byCategory[p.category].push(p);
  }

  const specificTitle = `${cachedSpec?.label ?? visuMeta.label} Options`;
  const specificIcon = cachedSpec?.icon || visuMeta.icon || 'mdi:chart-line';

  // Description lookup keyed by viz `name` so the Select can render it
  // beneath each option without re-running array searches per option.
  const descByType = useMemo(() => {
    const map: Record<string, string> = {};
    for (const v of visuList) {
      if (v.description) map[v.type] = v.description;
    }
    return map;
  }, [visuList]);

  return (
    <Stack gap="md" style={{ padding: '0 4px' }}>
      <div>
        <Group gap="xs" align="center" mb={10}>
          <Icon icon="mdi:chart-line" width={18} height={18} />
          <Text fw={700} size="md" style={{ fontSize: 16 }}>
            Visualization Type:
          </Text>
        </Group>
        <Select
          data={visuOptions}
          value={visuType}
          onChange={(v) => {
            if (v && !v.startsWith('__')) setVisuType(v);
          }}
          placeholder="Choose visualization type..."
          clearable={false}
          searchable
          size="md"
          comboboxProps={{ withinPortal: false }}
          style={{ width: '100%', fontSize: 14 }}
          renderOption={({ option }) => {
            // Group headers (`__group__core`, etc.) are styled flat — no
            // description, no extra padding. Items get a two-line layout.
            if (option.value.startsWith('__group__')) {
              return (
                <Text size="xs" c="dimmed" fw={600}>
                  {option.label}
                </Text>
              );
            }
            const desc = descByType[option.value];
            return (
              <Stack gap={2} style={{ width: '100%' }}>
                <Text size="sm">{option.label.trim()}</Text>
                {desc && (
                  <Text size="xs" c="dimmed" lineClamp={2}>
                    {desc}
                  </Text>
                )}
              </Stack>
            );
          }}
        />
      </div>

      {loading && (
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="xs" c="dimmed">
            Loading parameters…
          </Text>
        </Group>
      )}

      {error && (
        <Alert color="red" title="Couldn’t load parameters">
          <Text size="xs">{error}</Text>
        </Alert>
      )}

      {cachedSpec && (
        <Accordion
          variant="separated"
          radius="md"
          multiple
          defaultValue={['core']}
        >
          {FIXED_CATEGORIES.map((c) => {
            const items = byCategory[c.category];
            if (!items.length) return null;
            return (
              <Accordion.Item key={c.key} value={c.key}>
                <Accordion.Control
                  icon={<Icon icon={c.icon} width={18} height={18} />}
                >
                  <Text fw={700} size="sm">
                    {c.title}
                  </Text>
                </Accordion.Control>
                <Accordion.Panel>
                  <Stack gap="sm">
                    {items.map((p) => (
                      <ParameterField key={p.name} param={p} />
                    ))}
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            );
          })}

          {byCategory.specific.length > 0 && (
            <Accordion.Item value="specific">
              <Accordion.Control
                icon={<Icon icon={specificIcon} width={18} height={18} />}
              >
                <Text fw={700} size="sm">
                  {specificTitle}
                </Text>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="sm">
                  {byCategory.specific.map((p) => (
                    <ParameterField key={p.name} param={p} />
                  ))}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          )}

          {/* Cross-filtering only carries per-row identity for scatter
           *  traces (their customdata lines up 1:1 with input rows).
           *  Aggregated visus — histogram, bar, box, pie — would emit
           *  per-bin envelopes with no useful filter target, so we hide the
           *  toggle entirely on those. FigureRenderer + ComponentRenderer
           *  enforce the same gate defensively for legacy metadata. */}
          {(visuType === 'scatter' || visuType === 'scatter_3d') && (
            <CrossFilterSection
              enabled={Boolean(config.selection_enabled)}
              onEnabledChange={(checked) =>
                patchConfig({ selection_enabled: checked })
              }
              column={config.selection_column}
              onColumnChange={(name) => patchConfig({ selection_column: name })}
              columnDescription="Column to extract from selected points"
            />
          )}
        </Accordion>
      )}
    </Stack>
  );
};

export default FigureUIMode;
