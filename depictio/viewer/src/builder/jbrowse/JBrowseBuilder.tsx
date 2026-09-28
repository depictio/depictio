/**
 * Genome browser builder. Form fields mirror JBrowseLiteComponent
 * (depictio/models/components/lite.py) one-to-one, stored under the same
 * snake_case keys so `loadExisting` rehydrates them without a mapping, and
 * depictio/api/v1/services/jbrowse/render.py builds the view from them.
 *
 * Binds to a `genomic_tracks` DC (the track manifest) or a legacy `jbrowse2`
 * DC. The preview can only summarise the manifest: the real view is rendered
 * server-side from the *saved* component.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  Code,
  Group,
  JsonInput,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  TagsInput,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  fetchDataCollectionConfig,
  fetchDataCollectionPreview,
  fetchProjectFromDashboard,
  fetchSpecs,
} from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import CrossFilterSection from '../shared/CrossFilterSection';
import DesignShell from '../shared/DesignShell';
import JBrowsePreview from './JBrowsePreview';
import UcscTrackPicker from './UcscTrackPicker';
import {
  fetchJBrowseAssemblies,
  fetchJBrowsePresets,
  readGenomicTracksProps,
} from './jbrowseApi';
import type {
  GenomicTracksProps,
  JBrowseAssemblyOption,
  JBrowsePresetOption,
} from './jbrowseApi';

export interface JBrowseLocusFrom {
  data_collection_tag?: string;
  chrom_column?: string;
  start_column?: string;
  end_column?: string | null;
  padding?: number;
  max_rows?: number;
}

export interface JBrowseConfig {
  title?: string;
  assembly?: string | null;
  location?: string | null;
  locus_from?: JBrowseLocusFrom | null;
  track_mode?: 'filtered' | 'all';
  max_tracks?: number;
  initial_tracks?: number;
  default_tracks?: string[];
  /** UCSC Genome Browser track names shown by default. */
  ucsc_tracks?: string[];
  show_annotation?: boolean;
  selection_enabled?: boolean;
  selection_column?: string | null;
  selection_mode?: 'feature_click' | 'visible_tracks';
  show_header?: boolean;
  show_overview?: boolean;
  track_labels?: 'overlapping' | 'offset' | 'hidden';
  /** Default of the viewer's "Force load" toggle. */
  force_load?: boolean;
  /** Per-track fetch cap in MB before JBrowse asks to force load; null = JBrowse default. */
  fetch_size_limit_mb?: number | null;
  preset?: string | null;
  config_overrides?: Record<string, unknown>;
}

const TRACK_MODES = [
  { value: 'filtered', label: 'Filtered tracks' },
  { value: 'all', label: 'All tracks' },
];

const SELECTION_MODES = [
  { value: 'feature_click', label: 'Clicked feature' },
  { value: 'visible_tracks', label: 'Visible tracks' },
];

const TRACK_LABELS = [
  { value: 'offset', label: 'Offset (above the track)' },
  { value: 'overlapping', label: 'Overlapping the track' },
  { value: 'hidden', label: 'Hidden' },
];

/** Top-level `config_overrides` keys render.py reads (`displays` is the legacy
 *  spelling of `formats`). Anything else is ignored server-side. */
const OVERRIDE_KEYS = new Set([
  'formats',
  'displays',
  'tracks',
  'extra_tracks',
  'view',
  'configuration',
  'assembly',
]);

const OVERRIDES_EXAMPLE =
  '{"formats": {"bigwig": {"displays": [{"type": "LinearWiggleDisplay", "height": 80}]}}}';

const LOCUS_DEFAULTS = { padding: 5000, max_rows: 20 };

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

function stringifyOverrides(v: unknown): string {
  return isPlainObject(v) && Object.keys(v).length > 0 ? JSON.stringify(v, null, 2) : '';
}

/** Column names from `/deltatables/specs`, which answers either a list of
 *  specs or a `{name: spec}` map (see StepData). */
function specNames(specs: unknown): string[] {
  if (Array.isArray(specs)) {
    return specs.map((s) => String((s as { name?: unknown })?.name ?? '')).filter(Boolean);
  }
  return isPlainObject(specs) ? Object.keys(specs) : [];
}

const JBrowseBuilder: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as JBrowseConfig;
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const setPreviewReady = useBuilderStore((s) => s.setPreviewReady);
  const dcId = useBuilderStore((s) => s.dcId);
  const dashboardId = useBuilderStore((s) => s.dashboardId);

  const [assemblies, setAssemblies] = useState<JBrowseAssemblyOption[]>([]);
  const [builtinPresets, setBuiltinPresets] = useState<JBrowsePresetOption[]>([]);
  const [dcProps, setDcProps] = useState<GenomicTracksProps | null>(null);
  const [trackIds, setTrackIds] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchJBrowseAssemblies()
      .then((list) => !cancelled && setAssemblies(list))
      .catch(() => !cancelled && setAssemblies([]));
    fetchJBrowsePresets()
      .then((list) => !cancelled && setBuiltinPresets(list))
      .catch(() => !cancelled && setBuiltinPresets([]));
    return () => {
      cancelled = true;
    };
  }, []);

  // The DC's own assembly / sample column / presets label the "inherit"
  // defaults, and its track id column (when declared) feeds the default-track
  // suggestions — without one, track ids are hashed uris nobody types.
  useEffect(() => {
    setDcProps(null);
    setTrackIds([]);
    if (!dcId) return;
    let cancelled = false;
    fetchDataCollectionConfig(dcId).then((cfg) => {
      if (cancelled) return;
      const props = readGenomicTracksProps(cfg);
      setDcProps(props);
      const idColumn = props.trackIdColumn;
      if (!idColumn) return;
      fetchDataCollectionPreview(dcId, 200)
        .then((res) => {
          if (cancelled) return;
          const ids = new Set<string>();
          for (const row of res.rows) {
            const v = row?.[idColumn];
            if (v != null && v !== '') ids.add(String(v));
          }
          setTrackIds([...ids]);
        })
        .catch(() => undefined);
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [dcId]);

  // ---- config overrides (JSON) -------------------------------------------
  // The editor keeps its own text so a half-typed object isn't lost; the
  // parsed value only reaches the store once it is valid. Save stays blocked
  // (previewReady) while it isn't, so a typo is never silently dropped.
  const [overridesText, setOverridesText] = useState(() =>
    stringifyOverrides(config.config_overrides),
  );
  const [overridesError, setOverridesError] = useState<string | null>(null);

  const onOverridesChange = (text: string) => {
    setOverridesText(text);
    if (!text.trim()) {
      setOverridesError(null);
      setPreviewReady(true);
      patchConfig({ config_overrides: {} });
      return;
    }
    try {
      const parsed: unknown = JSON.parse(text);
      if (!isPlainObject(parsed)) throw new Error('Overrides must be a JSON object');
      setOverridesError(null);
      setPreviewReady(true);
      patchConfig({ config_overrides: parsed });
    } catch (e) {
      setOverridesError(e instanceof Error ? e.message : String(e));
      setPreviewReady(false);
    }
  };

  // Leaving the builder with an invalid draft must not keep Save disabled.
  useEffect(() => () => setPreviewReady(true), [setPreviewReady]);

  const unknownOverrideKeys = useMemo(
    () =>
      isPlainObject(config.config_overrides)
        ? Object.keys(config.config_overrides).filter((k) => !OVERRIDE_KEYS.has(k))
        : [],
    [config.config_overrides],
  );

  // ---- locus from filtered rows -----------------------------------------
  const locusFrom = config.locus_from ?? null;
  const [projectDcs, setProjectDcs] = useState<Array<{ id: string; tag: string }>>([]);
  const [locusCols, setLocusCols] = useState<string[]>([]);

  useEffect(() => {
    if (!dashboardId || !locusFrom) return;
    let cancelled = false;
    fetchProjectFromDashboard(dashboardId)
      .then(({ project }) => {
        if (cancelled) return;
        const seen = new Set<string>();
        const out: Array<{ id: string; tag: string }> = [];
        for (const wf of project.workflows || []) {
          for (const dc of wf.data_collections || []) {
            const tag = dc.data_collection_tag;
            const type = (dc.config?.type as string | undefined)?.toLowerCase();
            // Coordinates are read from a Delta table: tables and manifests.
            if (!tag || seen.has(tag) || (type !== 'table' && type !== 'genomic_tracks')) continue;
            seen.add(tag);
            out.push({ id: dc._id, tag });
          }
        }
        setProjectDcs(out);
      })
      .catch(() => !cancelled && setProjectDcs([]));
    return () => {
      cancelled = true;
    };
    // Only (re)load when the section is switched on, not on every field edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, Boolean(locusFrom)]);

  const locusDcId = projectDcs.find((d) => d.tag === locusFrom?.data_collection_tag)?.id;
  useEffect(() => {
    setLocusCols([]);
    if (!locusDcId) return;
    let cancelled = false;
    fetchSpecs(locusDcId)
      .then((specs) => !cancelled && setLocusCols(specNames(specs)))
      .catch(() => !cancelled && setLocusCols([]));
    return () => {
      cancelled = true;
    };
  }, [locusDcId]);

  const patchLocus = (patch: Partial<JBrowseLocusFrom>) =>
    patchConfig({ locus_from: { ...LOCUS_DEFAULTS, ...(locusFrom ?? {}), ...patch } });

  // ---- options -------------------------------------------------------------
  const assemblyOptions = useMemo(() => {
    const opts = assemblies.map((a) => ({
      value: a.name,
      label: a.organism ? `${a.display_name || a.name} (${a.organism})` : a.display_name || a.name,
    }));
    // Keep a saved value selectable even if this deployment doesn't list it.
    if (config.assembly && !opts.some((o) => o.value === config.assembly)) {
      opts.push({ value: config.assembly, label: config.assembly });
    }
    return opts;
  }, [assemblies, config.assembly]);

  const presetOptions = useMemo(() => {
    const groups: Array<{ group: string; items: Array<{ value: string; label: string }> }> = [];
    const dcPresets = dcProps?.presets ?? [];
    const dcNames = new Set(dcPresets.map((p) => p.name));
    const label = (p: JBrowsePresetOption) =>
      p.description ? `${p.name} — ${p.description}` : p.name;
    // A collection preset shadows a built-in of the same name (resolve_preset
    // checks the DC's `presets` first), so list it once, under the collection.
    if (dcPresets.length) {
      groups.push({
        group: 'This collection',
        items: dcPresets.map((p) => ({ value: p.name, label: label(p) })),
      });
    }
    const builtins = builtinPresets.filter((p) => !dcNames.has(p.name));
    if (builtins.length) {
      groups.push({
        group: 'Built-in',
        items: builtins.map((p) => ({ value: p.name, label: label(p) })),
      });
    }
    const known = groups.some((g) => g.items.some((i) => i.value === config.preset));
    if (config.preset && !known) {
      groups.push({ group: 'Saved', items: [{ value: config.preset, label: config.preset }] });
    }
    return groups;
  }, [builtinPresets, dcProps, config.preset]);

  const dcAssembly = dcProps?.assembly;
  const selectionEnabled = !!config.selection_enabled;
  const locusColOptions = locusCols.map((c) => ({ value: c, label: c }));
  // Keep a saved tag selectable while the project list loads (or if the DC is gone).
  const locusDcOptions = projectDcs.map((d) => d.tag);
  const savedLocusTag = locusFrom?.data_collection_tag;
  if (savedLocusTag && !locusDcOptions.includes(savedLocusTag)) locusDcOptions.push(savedLocusTag);

  const form = (
    <Stack gap="md">
      <Title order={6}>Genome Browser Configuration</Title>

      <TextInput
        label="Title"
        value={config.title ?? ''}
        onChange={(e) => patchConfig({ title: e.currentTarget.value })}
      />

      <Group grow align="flex-start">
        <Select
          label="Assembly"
          description="Reference genome the tracks are drawn on"
          placeholder={
            dcAssembly ? `Collection's assembly (${dcAssembly})` : "Collection's assembly"
          }
          data={assemblyOptions}
          value={config.assembly ?? null}
          onChange={(val) => patchConfig({ assembly: val || null })}
          searchable
          clearable
          leftSection={<Icon icon="mdi:dna" width={14} />}
        />
        <TextInput
          label="Initial location"
          description="Locus or gene name; empty uses the assembly default"
          placeholder="chr17:7,661,779-7,687,538"
          value={config.location ?? ''}
          onChange={(e) => patchConfig({ location: e.currentTarget.value || null })}
        />
      </Group>

      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Tracks
        </Text>
        <SegmentedControl
          data={TRACK_MODES}
          value={config.track_mode ?? 'filtered'}
          onChange={(val) => patchConfig({ track_mode: val })}
          fullWidth
        />
        <Text size="xs" c="dimmed">
          {(config.track_mode ?? 'filtered') === 'all'
            ? 'Every track is loaded in the track selector; dashboard filters pick which ones are shown.'
            : 'Only the tracks matching the dashboard filters are loaded.'}
        </Text>
      </Stack>

      <Group grow align="flex-start">
        <NumberInput
          label="Max tracks shown"
          min={1}
          max={200}
          value={config.max_tracks ?? 20}
          onChange={(val) => typeof val === 'number' && patchConfig({ max_tracks: val })}
          clampBehavior="strict"
          allowDecimal={false}
        />
        <NumberInput
          label="Tracks shown unfiltered"
          description="First manifest rows"
          min={0}
          max={200}
          value={config.initial_tracks ?? 5}
          onChange={(val) => typeof val === 'number' && patchConfig({ initial_tracks: val })}
          clampBehavior="strict"
          allowDecimal={false}
        />
      </Group>

      <TagsInput
        label="Always-shown tracks"
        description={
          dcProps?.trackIdColumn
            ? `Track ids (${dcProps.trackIdColumn} column) shown whatever the filters`
            : 'Track ids shown whatever the filters'
        }
        placeholder="Type a track id and press Enter"
        data={trackIds}
        value={config.default_tracks ?? []}
        onChange={(vals) => patchConfig({ default_tracks: vals })}
        clearable
      />

      <UcscTrackPicker
        assembly={config.assembly || dcAssembly || null}
        value={config.ucsc_tracks ?? []}
        onChange={(vals) => patchConfig({ ucsc_tracks: vals })}
      />

      <Stack gap={6}>
        <Text size="sm" fw={500}>
          Display
        </Text>
        <Switch
          label="Gene annotation track"
          description="From the assembly preset, when it ships one"
          checked={config.show_annotation !== false}
          onChange={(e) => patchConfig({ show_annotation: e.currentTarget.checked })}
        />
        <Switch
          label="Navigation header"
          checked={config.show_header !== false}
          onChange={(e) => patchConfig({ show_header: e.currentTarget.checked })}
        />
        <Switch
          label="Overview / ruler bar"
          checked={config.show_overview !== false}
          onChange={(e) => patchConfig({ show_overview: e.currentTarget.checked })}
        />
        <Select
          label="Track labels"
          data={TRACK_LABELS}
          value={config.track_labels ?? 'offset'}
          onChange={(val) => val && patchConfig({ track_labels: val })}
          allowDeselect={false}
        />
      </Stack>

      <Stack gap={6}>
        <Text size="sm" fw={500}>
          Data loading
        </Text>
        <Switch
          label="Force load"
          description="Fetch every track even when the region holds a lot of data (may be slow). Viewers can still switch it from the tile toolbar."
          checked={!!config.force_load}
          onChange={(e) => patchConfig({ force_load: e.currentTarget.checked })}
          data-testid="jbrowse-builder-force-load"
        />
        <NumberInput
          label="Fetch size limit (MB)"
          description="Data a track may fetch for the visible region before JBrowse asks to force load; empty uses the JBrowse default"
          placeholder="JBrowse default"
          min={0.1}
          max={10000}
          clampBehavior="blur"
          value={config.fetch_size_limit_mb ?? ''}
          onChange={(val) =>
            patchConfig({ fetch_size_limit_mb: typeof val === 'number' && val > 0 ? val : null })
          }
          allowNegative={false}
          data-testid="jbrowse-builder-fetch-size-limit"
        />
      </Stack>

      <Accordion variant="separated" radius="md" multiple>
        <CrossFilterSection
          enabled={selectionEnabled}
          onEnabledChange={(checked) => patchConfig({ selection_enabled: checked })}
          column={config.selection_column}
          onColumnChange={(name) => patchConfig({ selection_column: name })}
          columnDescription="Manifest column emitted for the picked tracks"
          columnPlaceholder={
            dcProps?.sampleColumn
              ? `Collection's sample column (${dcProps.sampleColumn})`
              : "Collection's sample column"
          }
        >
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Selection source
            </Text>
            <SegmentedControl
              data={SELECTION_MODES}
              value={config.selection_mode ?? 'feature_click'}
              onChange={(val) => patchConfig({ selection_mode: val })}
              disabled={!selectionEnabled}
              fullWidth
            />
            <Text size="xs" c="dimmed">
              {(config.selection_mode ?? 'feature_click') === 'visible_tracks'
                ? 'Every track open in the view filters the dashboard.'
                : "Clicking a feature filters the dashboard to its track's value."}
            </Text>
          </Stack>
        </CrossFilterSection>

        <Accordion.Item value="locus">
          <Accordion.Control icon={<Icon icon="mdi:crosshairs-gps" width={18} height={18} />}>
            <Text fw={700} size="sm">
              Follow filtered rows
            </Text>
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              <Switch
                label="Navigate to the coordinates of filtered rows"
                description="When a filter narrows a table to a few rows (a row click, a volcano point…), jump to the first row's locus."
                checked={!!locusFrom}
                onChange={(e) =>
                  patchConfig({
                    locus_from: e.currentTarget.checked ? { ...LOCUS_DEFAULTS } : null,
                  })
                }
              />
              {locusFrom && (
                <>
                  <Select
                    label="Coordinates data collection"
                    data={locusDcOptions}
                    value={locusFrom.data_collection_tag ?? null}
                    onChange={(val) =>
                      patchLocus({
                        data_collection_tag: val ?? undefined,
                        chrom_column: undefined,
                        start_column: undefined,
                        end_column: null,
                      })
                    }
                    searchable
                    required
                    leftSection={<Icon icon="mdi:database" width={14} />}
                  />
                  <Group grow align="flex-start">
                    <Select
                      label="Chromosome"
                      data={locusColOptions}
                      value={locusFrom.chrom_column ?? null}
                      onChange={(val) => patchLocus({ chrom_column: val ?? undefined })}
                      searchable
                      required
                      disabled={!locusFrom.data_collection_tag}
                    />
                    <Select
                      label="Start"
                      data={locusColOptions}
                      value={locusFrom.start_column ?? null}
                      onChange={(val) => patchLocus({ start_column: val ?? undefined })}
                      searchable
                      required
                      disabled={!locusFrom.data_collection_tag}
                    />
                    <Select
                      label="End"
                      placeholder="Start"
                      data={locusColOptions}
                      value={locusFrom.end_column ?? null}
                      onChange={(val) => patchLocus({ end_column: val })}
                      searchable
                      clearable
                      disabled={!locusFrom.data_collection_tag}
                    />
                  </Group>
                  <Group grow align="flex-start">
                    <NumberInput
                      label="Padding (bp)"
                      description="Added on each side"
                      min={0}
                      value={locusFrom.padding ?? LOCUS_DEFAULTS.padding}
                      onChange={(val) => typeof val === 'number' && patchLocus({ padding: val })}
                      allowDecimal={false}
                      thousandSeparator=","
                    />
                    <NumberInput
                      label="Max matching rows"
                      description="Navigate only below this"
                      min={1}
                      value={locusFrom.max_rows ?? LOCUS_DEFAULTS.max_rows}
                      onChange={(val) => typeof val === 'number' && patchLocus({ max_rows: val })}
                      allowDecimal={false}
                    />
                  </Group>
                </>
              )}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="custom">
          <Accordion.Control icon={<Icon icon="mdi:code-json" width={18} height={18} />}>
            <Text fw={700} size="sm">
              Custom configuration
            </Text>
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              <Select
                label="Preset"
                description="Named JBrowse config fragment applied before the overrides"
                placeholder="None"
                data={presetOptions}
                value={config.preset ?? null}
                onChange={(val) => patchConfig({ preset: val || null })}
                searchable
                clearable
              />
              <JsonInput
                label="Config overrides"
                description="Raw JBrowse config, deep-merged last"
                placeholder={OVERRIDES_EXAMPLE}
                value={overridesText}
                onChange={onOverridesChange}
                error={overridesError}
                validationError={overridesError ?? 'Invalid JSON'}
                autosize
                minRows={4}
                maxRows={16}
                formatOnBlur
                styles={{ input: { fontFamily: 'var(--mantine-font-family-monospace)' } }}
              />
              <Text size="xs" c="dimmed">
                Keys: <Code>formats</Code> (per track format), <Code>tracks</Code> (per track
                id), <Code>extra_tracks</Code>, <Code>view</Code>, <Code>configuration</Code>,{' '}
                <Code>assembly</Code>. Example: <Code>{OVERRIDES_EXAMPLE}</Code>
              </Text>
              {unknownOverrideKeys.length > 0 && (
                <Text size="xs" c="orange">
                  Ignored keys: {unknownOverrideKeys.join(', ')}
                </Text>
              )}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );

  return <DesignShell formSlot={form} previewSlot={<JBrowsePreview dcProps={dcProps} />} />;
};

export default JBrowseBuilder;
