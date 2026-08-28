/**
 * Right panel: one header band, the preview, and the source data behind it.
 *
 * The band carries only what identifies the offered component and the two ways
 * to take it. The reference material (output id, fixture, `find` rule, upstream
 * links, the catalog YAML itself) is one click away in the details popover,
 * because it is looked up, not read on every selection.
 *
 * What is *not* one click away is the data collection: the offer is an
 * abstraction over a real collection, and the user has to be able to tie the two
 * together, so the tag sits in the header and its rows are a disclosure away.
 *
 * The render switcher always shows, even for the many outputs that offer exactly
 * one render. A strip that comes and goes moved the preview up and down between
 * selections, and the single-render case is precisely the one where nothing else
 * on the band says what the offer will land on the dashboard as.
 */
import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Anchor,
  Badge,
  Box,
  Button,
  Code,
  Collapse,
  Group,
  Popover,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import type {
  AdvancedVizKindDescriptor,
  CatalogOutputMatch,
  CatalogRender,
} from 'depictio-react-core';
import { catalogToolUrl, componentTypeVisual, defaultLayoutForType } from 'depictio-react-core';
import PreviewLoading from '../shared/PreviewLoading';
import DataPreviewTable from '../data/DataPreviewTable';

export type VizKinds = Map<string, AdvancedVizKindDescriptor>;

interface CatalogPreviewPanelProps {
  match: CatalogOutputMatch;
  toolId: string;
  toolName: string;
  /** Advanced-viz kind metadata, keyed by `viz_kind` (labels + descriptions). */
  vizKinds: VizKinds;
  onAdd: (render: CatalogRender, overrides: Record<string, unknown> | null) => void;
  onDirectAdd: (render: CatalogRender, overrides: Record<string, unknown> | null) => void;
}

/** What distinguishes one render of an output from its siblings. */
export function renderVariant(render: CatalogRender, vizKinds: VizKinds): string {
  if (render.kind) return vizKinds.get(render.kind)?.label ?? render.kind.replace(/_/g, ' ');
  if (render.visu_type) return render.visu_type;
  if (render.aggregation)
    return render.column ? `${render.aggregation} · ${render.column}` : render.aggregation;
  if (render.code) return 'custom code';
  return '';
}

/** One-line explanation of a render, for a tooltip. Advanced viz has a real
 *  description served with the kind; the other components describe themselves. */
function renderHint(render: CatalogRender, vizKinds: VizKinds): string {
  if (render.kind) return vizKinds.get(render.kind)?.description ?? '';
  return componentTypeVisual(render.component).label;
}

// ---------------------------------------------------------------------------
// use: <tool>/<ref> — only advanced_viz renders resolve through the catalog
// `use:` expander today, so a snippet is only meaningful there. Prefer the
// render's own id; fall back to the output short id. Exported (imported by
// CatalogTab, which stamps the same ref as provenance on the added component).
// ---------------------------------------------------------------------------
function outputShort(outputId: string, toolId: string): string {
  return outputId.startsWith(`${toolId}_`) ? outputId.slice(toolId.length + 1) : outputId;
}

export function catalogUseRef(
  toolId: string,
  outputId: string,
  render: CatalogRender,
): string | undefined {
  if (render.component !== 'advanced_viz') return undefined;
  const ref = render.id || outputShort(outputId, toolId);
  return `${toolId}/${ref}`;
}

/** "Adapter trimming (Cutadapt)" — the aggregator names its producer. */
export function matchTitle(match: CatalogOutputMatch): string {
  const name = match.name || match.output_id;
  return match.origin_tool ? `${name} (${match.origin_tool})` : name;
}

const PREVIEW_BASE = '/depictio/api/v1/catalog/output';

// DashboardGrid's lg-breakpoint geometry (see DashboardGrid.tsx). Mirrored here
// so the preview frame is the same box the component gets on the dashboard.
const GRID_COLS = 8;
const GRID_ROW_HEIGHT = 100;
const GRID_MARGIN_X = 12;
const GRID_MARGIN_Y = 4;
// Empty room left below a card's tile inside the iframe.
//
// An iframe clips at its viewport edge no matter the z-index, and a metric
// strip's tooltip (the Tukey five-number summary, a top-N breakdown) is taller
// than the 204px a 2x2 card tile gets — so framed at exactly the tile size the
// tooltip was cut in half with no way to reach the rest of it. The tile keeps
// its real size; the headroom is transparent and only exists for what the tile
// raises above itself.
const CARD_TOOLTIP_HEADROOM = 240;

// ---------------------------------------------------------------------------
// Details popover pieces
// ---------------------------------------------------------------------------

const DetailSection: React.FC<{ title: string; children: React.ReactNode }> = ({
  title,
  children,
}) => (
  <Box>
    <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb={4}>
      {title}
    </Text>
    <Stack gap={3}>{children}</Stack>
  </Box>
);

const DetailRow: React.FC<{ label: string; children: React.ReactNode; mono?: boolean }> = ({
  label,
  children,
  mono,
}) => (
  <Group gap={8} wrap="nowrap" align="flex-start">
    <Text size="xs" c="dimmed" w={78} style={{ flexShrink: 0 }}>
      {label}
    </Text>
    {mono ? (
      <Code fz={11} style={{ wordBreak: 'break-all' }}>
        {children}
      </Code>
    ) : (
      <Text size="xs" style={{ lineHeight: 1.4, wordBreak: 'break-word' }}>
        {children}
      </Text>
    )}
  </Group>
);

/** External link that shows where it goes: icon, readable label, full URL on hover. */
const OutLink: React.FC<{ href: string; icon: string; label: string }> = ({
  href,
  icon,
  label,
}) => (
  <Anchor href={href} target="_blank" rel="noreferrer" size="xs" title={href}>
    <Group gap={4} wrap="nowrap" component="span" display="inline-flex">
      <Icon icon={icon} width={13} />
      <Text span>{label}</Text>
      <Icon icon="mdi:open-in-new" width={11} />
    </Group>
  </Anchor>
);

/** Component-type chip, in the app's one component palette. */
const TypeChip: React.FC<{ type: string }> = ({ type }) => {
  const visual = componentTypeVisual(type);
  return (
    <Badge
      size="xs"
      radius="sm"
      variant="light"
      color={visual.color}
      leftSection={<Icon icon={visual.icon} width={11} />}
    >
      {visual.label}
    </Badge>
  );
};

// ---------------------------------------------------------------------------

const CatalogPreviewPanel: React.FC<CatalogPreviewPanelProps> = ({
  match,
  toolId,
  toolName,
  vizKinds,
  onAdd,
  onDirectAdd,
}) => {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [copied, setCopied] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  // Each selection reloads the whole single-file preview bundle, which is not
  // instant. Same treatment as every other builder preview rather than a blank
  // frame — see shared/PreviewLoading.
  //
  // Derived from which URL has finished loading rather than held in an effect:
  // an effect runs after the render in which `previewUrl` changed, so that one
  // render would still show the previous frame as loaded.
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  // Tier-2 edits made inside the preview's own settings popover. The preview is
  // a separate document, so they arrive by postMessage rather than through the
  // in-process draft context the builder's own preview uses.
  const [previewOverrides, setPreviewOverrides] = useState<Record<string, unknown> | null>(null);
  const renders = match.renders_as;

  // A newly selected output may offer fewer renders than the previous one, and
  // its source data is a different collection.
  useEffect(() => {
    setSelectedIdx(0);
    setSourceOpen(false);
    setPreviewOverrides(null);
  }, [match.output_id, match.dc_id]);

  // A different render is a different component; its predecessor's controls do
  // not carry over.
  useEffect(() => setPreviewOverrides(null), [selectedIdx]);

  const current = renders[selectedIdx] ?? renders[0];
  const renderId = `${match.output_id}-${selectedIdx}`;
  const box = defaultLayoutForType(current?.component ?? '', 'right', 0);
  const tileHeight = box.h * GRID_ROW_HEIGHT + (box.h - 1) * GRID_MARGIN_Y;
  // A card paints its own surface (DepictioCard is a Paper with its own radius,
  // border and background), so the frame's chrome would only double it — and
  // dropping it is what lets the iframe stand taller than the tile without a
  // border drawn across the middle of it.
  const isCard = current?.component === 'card';

  // render_id via hash: read by the bundle's own JS (no backend restart needed).
  // ?render_id= also sent as an optimisation hint for the backend to filter payload size.
  // `tile_h` pins the component to its dashboard height inside a taller
  // viewport; without it the bundle stretches the single render to fill 100vh
  // and the headroom would just make the card bigger.
  const previewUrl =
    `${PREVIEW_BASE}/${encodeURIComponent(match.output_id)}/preview-html` +
    `?render_id=${encodeURIComponent(renderId)}` +
    `#render_id=${encodeURIComponent(renderId)}${isCard ? `&tile_h=${tileHeight}` : ''}`;

  const previewLoading = loadedUrl !== previewUrl;

  // Only messages from this preview, for the render currently on screen, and
  // only from our own origin. `renderId` changes with the selection, so a patch
  // posted just before a switch cannot land on the render that replaced it.
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data as
        | { type?: string; renderId?: string; patch?: Record<string, unknown> }
        | null;
      if (!data || data.type !== 'depictio:viz-config-draft') return;
      if (data.renderId !== renderId || !data.patch) return;
      setPreviewOverrides((prev) => ({ ...(prev ?? {}), ...data.patch }));
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [renderId]);

  const useRef = current ? catalogUseRef(toolId, match.output_id, current) : undefined;
  const useSnippet = useRef ? `use: ${useRef}` : '';
  const matchedOn = match.find?.path_glob || match.find?.filename;
  const toolUrl = catalogToolUrl(toolId);

  const copyUse = async () => {
    if (!useSnippet) return;
    try {
      await navigator.clipboard.writeText(useSnippet);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard denied — silently ignore
    }
  };

  return (
    <Stack
      gap={0}
      h="100%"
      style={{ minHeight: 0 }}
      data-testid="catalog-preview-panel"
      data-output-id={match.output_id}
      data-dc-tag={match.dc_tag}
      data-render-count={renders.length}
      data-selected-index={selectedIdx}
    >

      {/* Header — identity on the left, everything actionable on the right */}
      <Group
        px="lg"
        py="xs"
        gap="sm"
        justify="space-between"
        wrap="nowrap"
        style={{ borderBottom: '1px solid var(--mantine-color-default-border)', flexShrink: 0 }}
      >
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
          <Badge variant="dot" color="violet" size="sm" style={{ flexShrink: 0 }}>
            {toolName}
          </Badge>
          <Text size="sm" fw={600} style={{ flexShrink: 0 }}>{matchTitle(match)}</Text>
          <Tooltip label="The ingested data collection this render reads" withArrow>
            <Code fz={10} style={{ flexShrink: 0 }}>
              <Icon
                icon="mdi:database-outline"
                width={11}
                style={{ verticalAlign: '-1px', marginRight: 3 }}
              />
              {match.dc_tag}
            </Code>
          </Tooltip>
          {match.description && (
            <Text size="xs" c="dimmed" lineClamp={1} style={{ minWidth: 0 }}>
              {match.description}
            </Text>
          )}
        </Group>

        <Group gap={6} wrap="nowrap" style={{ flexShrink: 0 }}>
          <Popover position="bottom-end" withArrow shadow="md" width={400}>
            <Popover.Target>
              <Tooltip label="Details" withArrow>
                <ActionIcon variant="subtle" color="gray" size="md" aria-label="Output details">
                  <Icon icon="mdi:information-outline" width={17} />
                </ActionIcon>
              </Tooltip>
            </Popover.Target>
            <Popover.Dropdown p="md">
              <Stack gap="sm">
                {/* Identity: what is being offered, and as what */}
                <Box>
                  <Text size="sm" fw={700} mb={4} style={{ lineHeight: 1.2 }}>
                    {matchTitle(match)}
                  </Text>
                  {match.description && (
                    <Text size="xs" c="dimmed" style={{ lineHeight: 1.45 }}>
                      {match.description}
                    </Text>
                  )}
                  <Group gap={4} mt={6}>
                    {renders.map((r, i) => (
                      <TypeChip key={i} type={r.component} />
                    ))}
                  </Group>
                </Box>

                <DetailSection title="Source">
                  <DetailRow label="Collection" mono>{match.dc_tag}</DetailRow>
                  {match.dc_type && <DetailRow label="Type">{match.dc_type}</DetailRow>}
                  {matchedOn && <DetailRow label="Matches" mono>{matchedOn}</DetailRow>}
                  {match.recipe && <DetailRow label="Recipe" mono>{match.recipe}</DetailRow>}
                </DetailSection>

                <DetailSection title="Catalog">
                  <DetailRow label="Tool">{toolName} ({toolId})</DetailRow>
                  <DetailRow label="Output" mono>{match.output_id}</DetailRow>
                  {match.mode && <DetailRow label="Mode">{match.mode}</DetailRow>}
                  {match.fixture && <DetailRow label="Preview on" mono>{match.fixture}</DetailRow>}
                </DetailSection>

                {(toolUrl || match.source_url || match.nf_core_url || match.biotools_url) && (
                  <DetailSection title="Links">
                    {/* The tool's folder before the one output's YAML: it is what
                        someone wanting to add or fix a render actually needs, and
                        it holds the recipe and the fixture the file alone omits. */}
                    {toolUrl && (
                      <OutLink
                        href={toolUrl}
                        icon="mdi:github"
                        label={`depictio/catalog/${toolId}`}
                      />
                    )}
                    {match.source_url && (
                      <OutLink
                        href={match.source_url}
                        icon="mdi:github"
                        label="this output's definition"
                      />
                    )}
                    {match.nf_core_url && (
                      <OutLink href={match.nf_core_url} icon="simple-icons:nfcore" label="nf-core module" />
                    )}
                    {match.biotools_url && (
                      <OutLink href={match.biotools_url} icon="mdi:tools" label="bio.tools entry" />
                    )}
                  </DetailSection>
                )}
              </Stack>
            </Popover.Dropdown>
          </Popover>

          {useSnippet && (
            <Popover position="bottom-end" withArrow shadow="md">
              <Popover.Target>
                <Tooltip label="YAML reference" withArrow>
                  <ActionIcon variant="subtle" color="violet" size="md" aria-label="Show use snippet">
                    <Icon icon="mdi:code-tags" width={17} />
                  </ActionIcon>
                </Tooltip>
              </Popover.Target>
              <Popover.Dropdown p="sm">
                <Stack gap={6}>
                  <Text size="xs" c="dimmed">
                    Reference this render from a dashboard YAML:
                  </Text>
                  <Group gap="xs" wrap="nowrap">
                    <Code fz={12}>{useSnippet}</Code>
                    <Tooltip label={copied ? 'Copied!' : 'Copy'} withArrow>
                      <ActionIcon
                        variant="subtle"
                        color={copied ? 'teal' : 'violet'}
                        size="sm"
                        onClick={copyUse}
                        aria-label="Copy use snippet"
                      >
                        <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
                      </ActionIcon>
                    </Tooltip>
                  </Group>
                </Stack>
              </Popover.Dropdown>
            </Popover>
          )}

          <Button
            size="xs"
            color="violet"
            variant="filled"
            leftSection={<Icon icon="mdi:plus" width={15} />}
            data-testid="catalog-add"
            data-component={current?.component}
            onClick={() => onDirectAdd(current, previewOverrides)}
          >
            Add
          </Button>
          {/* A multiqc render is a 1:1 mapping — the catalog already picked the
            * section, and the Design step for multiqc offers nothing else. */}
          {current?.component !== 'multiqc' && (
            <Tooltip label="Add, then open the Design step to customise" withArrow>
              <Button
                size="xs"
                color="violet"
                variant="subtle"
                leftSection={<Icon icon="mdi:pencil-plus-outline" width={15} />}
                data-testid="catalog-edit-add"
                onClick={() => onAdd(current, previewOverrides)}
              >
                Edit
              </Button>
            </Tooltip>
          )}
        </Group>
      </Group>

      {/* Render switcher — see the file header for why it is unconditional. */}
      <Group
        px="lg"
        py={6}
        gap={4}
        wrap="wrap"
        style={{
          borderBottom: '1px solid var(--mantine-color-default-border)',
          flexShrink: 0,
        }}
      >
        {renders.map((r, i) => {
          const visual = componentTypeVisual(r.component);
          const variant = renderVariant(r, vizKinds);
          const hint = renderHint(r, vizKinds);
          const active = selectedIdx === i;
          return (
            <Tooltip key={i} label={hint} withArrow multiline maw={300} disabled={!hint}>
              <Button
                size="xs"
                variant={active ? 'light' : 'subtle'}
                color={visual.color}
                leftSection={<Icon icon={visual.icon} width={13} />}
                data-testid="catalog-render-tab"
                data-render-index={i}
                data-component={r.component}
                onClick={() => setSelectedIdx(i)}
                // Mantine's button label is `overflow: hidden` on a line box the
                // same height as the font, so descenders (the g in "coverage",
                // "average") are cut off. Giving the label real leading and
                // letting it overflow removes the whole class of clipping.
                styles={{
                  root: { fontWeight: active ? 600 : 400, flexShrink: 0 },
                  label: { lineHeight: 1.5, overflow: 'visible' },
                }}
              >
                {variant || visual.label}
              </Button>
            </Tooltip>
          );
        })}
      </Group>

      {/* Preview framed at the box the component will actually get.
        *
        * A full-bleed iframe made every render look like a full-width panel,
        * which is wrong for the small ones: a card is a 2x2 KPI tile on the
        * dashboard, not a banner. The frame reuses `defaultLayoutForType` —
        * the same function that writes the layout entry on add — and the
        * DashboardGrid geometry it is expressed in (cols=8, rowHeight=100,
        * margin=[12, 4] at lg), so the box is arithmetic rather than a guess
        * and cannot drift from what lands on the grid.
        *
        * Width is CSS rather than a measured container: one column is
        * `(100% - 12*(8-1)) / 8`, and `w` of them plus the margins between. */}
      <Box
        style={{
          flex: 1,
          minHeight: 0,
          overflow: 'auto',
          padding: 16,
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'flex-start',
          background: 'var(--mantine-color-default-hover)',
        }}
      >
        <Box
          style={{
            position: 'relative',
            width: `calc(((100% - ${GRID_MARGIN_X * (GRID_COLS - 1)}px) / ${GRID_COLS}) * ${box.w} + ${(box.w - 1) * GRID_MARGIN_X}px)`,
            height: tileHeight + (isCard ? CARD_TOOLTIP_HEADROOM : 0),
            flexShrink: 0,
            overflow: 'hidden',
            ...(isCard
              ? {}
              : {
                  borderRadius: 'var(--mantine-radius-md)',
                  border: '1px solid var(--mantine-color-default-border)',
                  background: 'var(--mantine-color-body)',
                  boxShadow: 'var(--mantine-shadow-xs)',
                }),
          }}
        >
          {previewLoading && <PreviewLoading label="Loading preview…" />}
          <iframe
            key={previewUrl}
            src={previewUrl}
            onLoad={() => setLoadedUrl(previewUrl)}
            style={{
              width: '100%',
              height: '100%',
              border: 'none',
              display: 'block',
              // Keep the frame from flashing the bundle's own empty body before
              // its script has mounted anything.
              visibility: previewLoading ? 'hidden' : 'visible',
            }}
            title={`Preview: ${match.output_id}`}
          />
        </Box>
      </Box>

      {/* Source data — the rows the preview is an abstraction over. Closed by
        * default and only mounted when opened, so no request is made for a
        * collection the user never asks about. */}
      <Box style={{ borderTop: '1px solid var(--mantine-color-default-border)', flexShrink: 0 }}>
        <UnstyledButton
          onClick={() => setSourceOpen((o) => !o)}
          w="100%"
          px="lg"
          py={8}
          aria-expanded={sourceOpen}
        >
          <Group gap={6} wrap="nowrap">
            <Icon
              icon={sourceOpen ? 'mdi:chevron-down' : 'mdi:chevron-right'}
              width={15}
              color="var(--mantine-color-dimmed)"
            />
            <Text size="xs" fw={700} c="dimmed" tt="uppercase">
              Source data
            </Text>
            <Code fz={10}>{match.dc_tag}</Code>
          </Group>
        </UnstyledButton>
        <Collapse in={sourceOpen}>
          <Box px="lg" pb="md" style={{ maxHeight: 520, overflow: 'auto' }}>
            {sourceOpen && (
              <DataPreviewTable dcId={match.dc_id} dcType={match.dc_type ?? null} shape={null} />
            )}
          </Box>
        </Collapse>
      </Box>

    </Stack>
  );
};

export default CatalogPreviewPanel;
