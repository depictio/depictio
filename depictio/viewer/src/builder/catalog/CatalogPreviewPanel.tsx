/**
 * Right panel: one component fills the full height.
 * A compact tab row at the top lets the user switch between renders_as entries.
 * The "Add to dashboard" button lives in the same row as the tabs.
 */
import React, { useState } from 'react';
import {
  Badge,
  Box,
  Button,
  Group,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import type { CatalogOutputMatch, CatalogRender } from 'depictio-react-core';

interface CatalogPreviewPanelProps {
  match: CatalogOutputMatch;
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

const PREVIEW_BASE = '/depictio/api/v1/catalog/output';

const CatalogPreviewPanel: React.FC<CatalogPreviewPanelProps> = ({ match, toolName, onAdd, onDirectAdd }) => {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const renders = match.renders_as;
  const current = renders[selectedIdx];
  const renderId = `${match.output_id}-${selectedIdx}`;
  // render_id via hash: read by the bundle's own JS (no backend restart needed).
  // ?render_id= also sent as an optimisation hint for the backend to filter payload size.
  const previewUrl = `${PREVIEW_BASE}/${encodeURIComponent(match.output_id)}/preview-html?render_id=${encodeURIComponent(renderId)}#render_id=${encodeURIComponent(renderId)}`;

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
          <Badge variant="dot" color="teal" size="sm">{toolName}</Badge>
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
            color="teal"
            variant="filled"
            leftSection={<Icon icon="mdi:plus" width={16} />}
            onClick={() => onDirectAdd(current)}
          >
            Add
          </Button>
          <Button
            size="sm"
            color="teal"
            variant="outline"
            leftSection={<Icon icon="mdi:pencil-plus-outline" width={16} />}
            onClick={() => onAdd(current)}
          >
            Edit & Add
          </Button>
        </Group>
      </Group>

      {/* Full-height bare component preview */}
      <Box style={{ flex: 1, minHeight: 0 }}>
        <iframe
          key={previewUrl}
          src={previewUrl}
          style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
          title={`Preview: ${match.output_id}`}
        />
      </Box>

    </Stack>
  );
};

export default CatalogPreviewPanel;
