/**
 * Right panel: one header band, then the preview fills everything below it.
 *
 * The band carries only what identifies the offered component and the two ways
 * to take it. Everything else that used to have its own row — the data
 * collection, the output id, the fixture, the recipe, the `find` rule, the
 * upstream links — is one click away in the details popover, because it is
 * reference material rather than something to read on every selection.
 *
 * The render switcher appears only when an output offers more than one render;
 * most offer exactly one, and a tab strip holding a single tab is pure chrome.
 */
import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Code,
  Group,
  Popover,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import type { CatalogOutputMatch, CatalogRender } from 'depictio-react-core';
import PreviewLoading from '../shared/PreviewLoading';
import { defaultLayoutForType } from 'depictio-react-core';

interface CatalogPreviewPanelProps {
  match: CatalogOutputMatch;
  toolId: string;
  toolName: string;
  onAdd: (render: CatalogRender) => void;
  onDirectAdd: (render: CatalogRender) => void;
}

const COMP_META: Record<string, { icon: string; color: string; label: string }> = {
  figure:       { icon: 'mdi:chart-bar',          color: 'blue',   label: 'Figure' },
  card:         { icon: 'formkit:number',         color: 'teal',   label: 'Card' },
  table:        { icon: 'octicon:table-24',       color: 'gray',   label: 'Table' },
  advanced_viz: { icon: 'mdi:chart-scatter-plot', color: 'violet', label: 'Advanced viz' },
  multiqc:      { icon: 'mdi:chart-line',         color: 'orange', label: 'MultiQC' },
};

export function renderVariant(render: CatalogRender): string {
  if (render.kind)        return render.kind.replace(/_/g, ' ');
  if (render.visu_type)   return render.visu_type;
  if (render.aggregation) return render.column ? `${render.aggregation} · ${render.column}` : render.aggregation;
  if (render.code)        return 'custom code';
  return '';
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

const PREVIEW_BASE = '/depictio/api/v1/catalog/output';

// DashboardGrid's lg-breakpoint geometry (see DashboardGrid.tsx). Mirrored here
// so the preview frame is the same box the component gets on the dashboard.
const GRID_COLS = 8;
const GRID_ROW_HEIGHT = 100;
const GRID_MARGIN_X = 12;
const GRID_MARGIN_Y = 4;

// ---------------------------------------------------------------------------

const DetailRow: React.FC<{ label: string; children: React.ReactNode; mono?: boolean }> = ({
  label,
  children,
  mono,
}) => (
  <Group gap={8} wrap="nowrap" align="flex-start">
    <Text size="xs" c="dimmed" w={72} style={{ flexShrink: 0 }}>
      {label}
    </Text>
    {mono ? (
      <Code fz={11} style={{ wordBreak: 'break-all' }}>{children}</Code>
    ) : (
      <Text size="xs" style={{ lineHeight: 1.4, wordBreak: 'break-word' }}>{children}</Text>
    )}
  </Group>
);

const CatalogPreviewPanel: React.FC<CatalogPreviewPanelProps> = ({
  match,
  toolId,
  toolName,
  onAdd,
  onDirectAdd,
}) => {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [copied, setCopied] = useState(false);
  // Each selection reloads the whole single-file preview bundle, which is not
  // instant. Same treatment as every other builder preview rather than a blank
  // frame — see shared/PreviewLoading.
  //
  // Derived from which URL has finished loading rather than held in an effect:
  // an effect runs after the render in which `previewUrl` changed, so that one
  // render would still show the previous frame as loaded.
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  const renders = match.renders_as;

  // A newly selected output may offer fewer renders than the previous one.
  useEffect(() => setSelectedIdx(0), [match.output_id, match.dc_id]);

  const current = renders[selectedIdx] ?? renders[0];
  const renderId = `${match.output_id}-${selectedIdx}`;
  // render_id via hash: read by the bundle's own JS (no backend restart needed).
  // ?render_id= also sent as an optimisation hint for the backend to filter payload size.
  const previewUrl = `${PREVIEW_BASE}/${encodeURIComponent(match.output_id)}/preview-html?render_id=${encodeURIComponent(renderId)}#render_id=${encodeURIComponent(renderId)}`;

  const previewLoading = loadedUrl !== previewUrl;

  const useRef = current ? catalogUseRef(toolId, match.output_id, current) : undefined;
  const useSnippet = useRef ? `use: ${useRef}` : '';
  const title = match.name || match.output_id;
  const box = defaultLayoutForType(current?.component ?? '', 'right', 0);

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
    <Stack gap={0} h="100%" style={{ minHeight: 0 }}>

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
          <Text size="sm" fw={600} style={{ flexShrink: 0 }}>{title}</Text>
          {match.description && (
            <Text size="xs" c="dimmed" lineClamp={1} style={{ minWidth: 0 }}>
              {match.description}
            </Text>
          )}
        </Group>

        <Group gap={6} wrap="nowrap" style={{ flexShrink: 0 }}>
          <Popover position="bottom-end" withArrow shadow="md" width={380}>
            <Popover.Target>
              <Tooltip label="Details" withArrow>
                <ActionIcon variant="subtle" color="gray" size="md" aria-label="Output details">
                  <Icon icon="mdi:information-outline" width={17} />
                </ActionIcon>
              </Tooltip>
            </Popover.Target>
            <Popover.Dropdown p="sm">
              <Stack gap={3}>
                <DetailRow label="Tool">{toolName} ({toolId})</DetailRow>
                <DetailRow label="Output" mono>{match.output_id}</DetailRow>
                {match.mode && <DetailRow label="Mode">{match.mode}</DetailRow>}
                <DetailRow label="Collection" mono>{match.dc_tag}</DetailRow>
                {match.find?.path_glob && (
                  <DetailRow label="Matches" mono>{match.find.path_glob}</DetailRow>
                )}
                {match.find?.filename && !match.find?.path_glob && (
                  <DetailRow label="Matches" mono>{match.find.filename}</DetailRow>
                )}
                {match.recipe && <DetailRow label="Recipe" mono>{match.recipe}</DetailRow>}
                {match.fixture && <DetailRow label="Preview on" mono>{match.fixture}</DetailRow>}
                {match.description && <DetailRow label="About">{match.description}</DetailRow>}
                {(match.nf_core_url || match.biotools_url) && (
                  <Group gap="sm" mt={4}>
                    {match.nf_core_url && (
                      <Text
                        size="xs" c="teal" component="a"
                        href={match.nf_core_url} target="_blank" rel="noreferrer"
                      >
                        nf-core module
                      </Text>
                    )}
                    {match.biotools_url && (
                      <Text
                        size="xs" c="teal" component="a"
                        href={match.biotools_url} target="_blank" rel="noreferrer"
                      >
                        bio.tools
                      </Text>
                    )}
                  </Group>
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
            onClick={() => onDirectAdd(current)}
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
                onClick={() => onAdd(current)}
              >
                Edit
              </Button>
            </Tooltip>
          )}
        </Group>
      </Group>

      {/* Render switcher — only when there is a choice to make */}
      {renders.length > 1 && (
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
            const meta = COMP_META[r.component] ?? { icon: 'mdi:puzzle', color: 'gray', label: r.component };
            const variant = renderVariant(r);
            const active = selectedIdx === i;
            return (
              <Button
                key={i}
                size="xs"
                variant={active ? 'light' : 'subtle'}
                color={meta.color}
                leftSection={<Icon icon={meta.icon} width={13} />}
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
                {variant || meta.label}
              </Button>
            );
          })}
        </Group>
      )}

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
            height: box.h * GRID_ROW_HEIGHT + (box.h - 1) * GRID_MARGIN_Y,
            flexShrink: 0,
            overflow: 'hidden',
            borderRadius: 'var(--mantine-radius-md)',
            border: '1px solid var(--mantine-color-default-border)',
            background: 'var(--mantine-color-body)',
            boxShadow: 'var(--mantine-shadow-xs)',
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

    </Stack>
  );
};

export default CatalogPreviewPanel;
