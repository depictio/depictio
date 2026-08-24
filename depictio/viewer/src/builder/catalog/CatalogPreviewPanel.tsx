/**
 * Right panel: one component fills the full height.
 * A compact tab row at the top lets the user switch between renders_as entries.
 * The "Add" / "Edit & Add" buttons live in the same row as the tabs, and — for
 * advanced_viz renders — a copyable `use: <tool>/<ref>` snippet is offered so a
 * dashboard YAML can reference the same catalog render.
 */
import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Code,
  Group,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import type { CatalogOutputMatch, CatalogRender } from 'depictio-react-core';

import { PreviewLoading } from '../shared/PreviewPanel';

interface CatalogPreviewPanelProps {
  match: CatalogOutputMatch;
  toolId: string;
  toolName: string;
  onAdd: (render: CatalogRender) => void;
  onDirectAdd: (render: CatalogRender) => void;
}

const COMP_META: Record<string, { icon: string; color: string; label: string }> = {
  figure:       { icon: 'mdi:chart-bar',        color: 'blue',   label: 'Figure' },
  card:         { icon: 'formkit:number',         color: 'teal',   label: 'Card' },
  table:        { icon: 'octicon:table-24',       color: 'gray',   label: 'Table' },
  advanced_viz: { icon: 'mdi:chart-scatter-plot', color: 'violet', label: 'Advanced viz' },
  multiqc:      { icon: 'mdi:chart-line',         color: 'orange', label: 'MultiQC' },
};

function renderVariant(render: CatalogRender): string {
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

const CatalogPreviewPanel: React.FC<CatalogPreviewPanelProps> = ({
  match,
  toolId,
  toolName,
  onAdd,
  onDirectAdd,
}) => {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [copied, setCopied] = useState(false);
  const renders = match.renders_as;
  const current = renders[selectedIdx];
  const renderId = `${match.output_id}-${selectedIdx}`;
  // render_id via hash: read by the bundle's own JS (no backend restart needed).
  // ?render_id= also sent as an optimisation hint for the backend to filter payload size.
  const previewUrl = `${PREVIEW_BASE}/${encodeURIComponent(match.output_id)}/preview-html?render_id=${encodeURIComponent(renderId)}#render_id=${encodeURIComponent(renderId)}`;

  // The iframe paints white until its document arrives, which on a heavy render
  // reads as "the panel is broken". Reset on every URL so switching render tabs
  // shows the spinner again, and clear it on the frame's own load event.
  const [previewLoaded, setPreviewLoaded] = useState(false);
  useEffect(() => setPreviewLoaded(false), [previewUrl]);

  const useRef = current ? catalogUseRef(toolId, match.output_id, current) : undefined;
  const useSnippet = useRef ? `use: ${useRef}` : '';

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

      {/* Output identity */}
      <Box
        px="lg"
        pt="sm"
        pb="xs"
        style={{ borderBottom: '1px solid var(--mantine-color-default-border)', flexShrink: 0 }}
      >
        <Group gap="xs" mb={2}>
          <Badge variant="dot" color="violet" size="sm">{toolName}</Badge>
          <Text size="xs" c="dimmed">{match.dc_tag}</Text>
        </Group>
        <Title order={4} fw={700} lineClamp={1}>
          {match.description || match.output_id}
        </Title>
      </Box>

      {/* Render switcher + Add button */}
      <Group
        px="lg"
        py="xs"
        justify="space-between"
        wrap="nowrap"
        style={{ borderBottom: '1px solid var(--mantine-color-default-border)', flexShrink: 0 }}
      >
        {/* Tab pills */}
        <Group gap={4} style={{ overflow: 'hidden' }}>
          {renders.map((r, i) => {
            const meta = COMP_META[r.component] ?? { icon: 'mdi:puzzle', color: 'gray', label: r.component };
            const variant = renderVariant(r);
            const active = selectedIdx === i;
            return (
              <Button
                key={i}
                size="xs"
                variant={active ? 'filled' : 'subtle'}
                color={meta.color}
                leftSection={<Icon icon={meta.icon} width={13} />}
                onClick={() => setSelectedIdx(i)}
                styles={{ root: { fontWeight: active ? 600 : 400 } }}
              >
                {meta.label}{variant ? ` · ${variant}` : ''}
              </Button>
            );
          })}
        </Group>

        {/* Add buttons for the currently-shown component */}
        <Group gap="xs" style={{ flexShrink: 0 }}>
          <Button
            size="sm"
            color="violet"
            variant="filled"
            leftSection={<Icon icon="mdi:plus" width={16} />}
            onClick={() => onDirectAdd(current)}
          >
            Add
          </Button>
          <Button
            size="sm"
            color="violet"
            variant="outline"
            leftSection={<Icon icon="mdi:pencil-plus-outline" width={16} />}
            onClick={() => onAdd(current)}
          >
            Edit & Add
          </Button>
        </Group>
      </Group>

      {/* use: snippet — advanced_viz renders only (the ones `use:` resolves) */}
      {useSnippet && (
        <Group
          px="lg"
          py={6}
          gap="xs"
          wrap="nowrap"
          style={{ borderBottom: '1px solid var(--mantine-color-default-border)', flexShrink: 0 }}
        >
          <Tooltip label="Reference this catalog render from a dashboard YAML" withArrow>
            <Icon icon="mdi:code-tags" width={14} color="var(--mantine-color-violet-6)" />
          </Tooltip>
          <Code style={{ fontSize: 12 }}>{useSnippet}</Code>
          <Tooltip label={copied ? 'Copied!' : 'Copy snippet'} withArrow>
            <ActionIcon variant="subtle" color="violet" size="sm" onClick={copyUse} aria-label="Copy use snippet">
              <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
            </ActionIcon>
          </Tooltip>
        </Group>
      )}

      {/* Full-height bare component preview */}
      <Box style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        {!previewLoaded && (
          <Box
            style={{
              position: 'absolute',
              inset: 0,
              zIndex: 2,
              background: 'var(--mantine-color-body)',
            }}
          >
            <PreviewLoading label="Loading preview…" />
          </Box>
        )}
        <iframe
          key={previewUrl}
          src={previewUrl}
          onLoad={() => setPreviewLoaded(true)}
          style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
          title={`Preview: ${match.output_id}`}
        />
      </Box>

    </Stack>
  );
};

export default CatalogPreviewPanel;
