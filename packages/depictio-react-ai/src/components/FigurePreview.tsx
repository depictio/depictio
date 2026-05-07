import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Stack,
  Text,
  Textarea,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import Plot from 'react-plotly.js';

import { previewFigure } from 'depictio-react-core';

import type { PlotSuggestion } from '../types';

interface Props {
  suggestion: PlotSuggestion;
  dataCollectionId: string;
  /** Optional — surfaced as project_id in the preview metadata. The
   *  /figure/preview endpoint resolves the workflow from the DC if both
   *  this and wfId are missing, so passing it is best-effort. */
  projectId?: string;
  workflowId?: string;
  theme?: 'light' | 'dark';
  /** Notify the parent when the user edits the code, so the message in
   *  the transcript can be patched and "Refine"/"Add to dashboard"
   *  consume the updated code instead of the original suggestion. */
  onCodeChange?: (code: string) => void;
}

/**
 * Renders a Plotly chart for the AI-suggested PlotSuggestion by hitting
 * /figure/preview in CODE MODE — same path the persisted figure will
 * use when added to the dashboard, so what-you-see-is-what-you-save.
 *
 * Includes an inline code editor: the user can tweak the Python
 * (e.g. add `color=...`, switch to `px.violin`, change a column) and
 * click "Update preview" to re-render. The edited code propagates back
 * to the parent so "Add to dashboard" persists the edited version.
 */
const FigurePreview: React.FC<Props> = ({
  suggestion,
  dataCollectionId,
  projectId,
  workflowId,
  theme = 'light',
  onCodeChange,
}) => {
  const initialCode = (suggestion.code || '').trim();
  const [code, setCode] = useState(initialCode);
  const [draft, setDraft] = useState(initialCode);
  const [editing, setEditing] = useState(false);
  const [figure, setFigure] = useState<{
    data?: unknown[];
    layout?: Record<string, unknown>;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Reset to the LLM-supplied code when the underlying suggestion
  // changes (e.g. parent refined and got a new suggestion object).
  useEffect(() => {
    setCode(initialCode);
    setDraft(initialCode);
    setEditing(false);
  }, [initialCode]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const metadata: Record<string, unknown> = {
      index: 'ai-preview',
      component_type: 'figure',
      mode: code ? 'code' : 'ui',
      dc_id: dataCollectionId,
      visu_type: suggestion.visu_type,
      dict_kwargs: suggestion.dict_kwargs,
      code_content: code || null,
    };
    if (projectId) metadata.project_id = projectId;
    if (workflowId) metadata.wf_id = workflowId;

    previewFigure({ metadata, filters: [], theme })
      .then((res) => {
        if (cancelled) return;
        setFigure(res.figure || null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    dataCollectionId,
    projectId,
    workflowId,
    theme,
    suggestion.visu_type,
    JSON.stringify(suggestion.dict_kwargs),
    code,
  ]);

  function applyDraft() {
    const next = draft.trim();
    setCode(next);
    setEditing(false);
    onCodeChange?.(next);
  }

  function cancelEdit() {
    setDraft(code);
    setEditing(false);
  }

  return (
    <Stack gap={6}>
      <Group justify="space-between" align="center" gap="xs">
        <Group gap={6} align="center">
          <Badge
            size="xs"
            variant="light"
            color="indigo"
            leftSection={<Icon icon="logos:python" width={10} />}
          >
            Python · code mode
          </Badge>
          {code !== initialCode && (
            <Badge size="xs" variant="light" color="orange">
              edited
            </Badge>
          )}
        </Group>
        <Tooltip label={editing ? 'Cancel edit' : 'Edit code'}>
          <ActionIcon
            size="sm"
            variant="subtle"
            color="gray"
            onClick={() => (editing ? cancelEdit() : setEditing(true))}
            aria-label="Edit code"
          >
            <Icon
              icon={
                editing
                  ? 'material-symbols:close'
                  : 'material-symbols:edit-outline'
              }
              width={16}
            />
          </ActionIcon>
        </Tooltip>
      </Group>

      {editing ? (
        <Stack gap={4}>
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.currentTarget.value)}
            autosize
            minRows={3}
            maxRows={12}
            styles={{
              input: {
                fontFamily:
                  'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                fontSize: 12,
              },
            }}
          />
          <Group gap="xs" justify="flex-end">
            <Button size="compact-xs" variant="subtle" color="gray" onClick={cancelEdit}>
              Cancel
            </Button>
            <Button
              size="compact-xs"
              variant="filled"
              color="violet"
              leftSection={<Icon icon="material-symbols:play-arrow" width={14} />}
              onClick={applyDraft}
            >
              Update preview
            </Button>
          </Group>
        </Stack>
      ) : (
        code && (
          <Code block style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
            {code}
          </Code>
        )
      )}

      {loading ? (
        <Stack align="center" gap={4} py="md">
          <Loader size="sm" />
          <Text size="xs" c="dimmed">
            Rendering figure…
          </Text>
        </Stack>
      ) : error ? (
        <Alert color="red" variant="light" title="Preview failed">
          <Text size="xs" style={{ whiteSpace: 'pre-wrap' }}>
            {error}
          </Text>
        </Alert>
      ) : !figure?.data || figure.data.length === 0 ? (
        <Alert color="yellow" variant="light">
          <Text size="xs">
            The server returned an empty figure. Try a different prompt or
            check that the data collection has rows for the chosen columns.
          </Text>
        </Alert>
      ) : (
        <div style={{ width: '100%', minHeight: 280 }}>
          <Plot
            data={figure.data as Plotly.Data[]}
            layout={
              {
                ...(figure.layout || {}),
                autosize: true,
                margin: { t: 32, r: 8, b: 40, l: 48 },
              } as unknown as Plotly.Layout
            }
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: '100%', height: 320 }}
            useResizeHandler
          />
        </div>
      )}
    </Stack>
  );
};

export default FigurePreview;
