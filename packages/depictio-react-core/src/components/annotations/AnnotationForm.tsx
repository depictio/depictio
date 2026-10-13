import React, { useEffect, useState } from 'react';
import { Button, Group, Stack, Switch, Text, Textarea, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';

import type {
  AnnotationDraft,
  PendingAnnotation,
  PendingDraftPatch,
} from '../../annotations/AnnotationLayerContext';
import { hasRegion, withoutRegion } from '../../annotations/edit';
import { defaultColorFor, KIND_LABELS, validateLabel } from '../../annotations/layer';
import { DEFAULT_RANGE_OPACITY } from '../../annotations/toPlotly';
import { annotationSummary } from '../../annotations/summary';
import type { AnnotationStats } from '../../annotations/summary';
import { MAX_LABEL_CHARS } from '../../annotations/types';
import type { AnnotationColor, AnnotationStyle } from '../../annotations/types';
import AnnotationColorPicker from './AnnotationColorPicker';
import { RegionHighlightFields } from './AnnotationStyleFields';

export interface AnnotationFormProps {
  pending: PendingAnnotation;
  onSave: (draft: AnnotationDraft) => Promise<void>;
  onCancel: () => void;
  /** Receives the label, colour, style and geometry as they change (the preview). */
  onDraftChange?: (patch: PendingDraftPatch) => void;
  /** Counts measured on the component's data for the pending shape. */
  stats?: AnnotationStats;
}

function geometrySummary(p: PendingAnnotation, stats?: AnnotationStats): string {
  return annotationSummary({ kind: p.kind, geometry: p.geometry, label: '' }, stats);
}

/**
 * Label, colour, optional comment and visibility of an annotation that was
 * just drawn. Lassoed or boxed points also get their selected area shaded,
 * unless switched off.
 */
const AnnotationForm: React.FC<AnnotationFormProps> = ({
  pending,
  onSave,
  onCancel,
  onDraftChange,
  stats,
}) => {
  const [label, setLabel] = useState('');
  const [color, setColor] = useState<AnnotationColor>(defaultColorFor(pending.kind));
  const [body, setBody] = useState('');
  const [published, setPublished] = useState(false);
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const withRegion = hasRegion(pending.geometry);
  const [highlight, setHighlight] = useState(true);
  const [fillOpacity, setFillOpacity] = useState(DEFAULT_RANGE_OPACITY);

  const labelError = validateLabel(label);
  const summary = geometrySummary(pending, stats);
  const geometry = withRegion && !highlight ? withoutRegion(pending.geometry) : pending.geometry;
  const style: AnnotationStyle | undefined =
    withRegion && highlight ? { fill_opacity: fillOpacity } : undefined;

  // Keep the preview on the chart in step with the form.
  useEffect(() => {
    onDraftChange?.({ label: label.trim(), color, style, geometry });
    // `style` and `geometry` are derived from the deps below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onDraftChange, label, color, highlight, fillOpacity, pending]);

  const submit = async () => {
    setTouched(true);
    if (labelError || saving) return;
    setSaving(true);
    try {
      const comment = body.trim();
      await onSave({
        annotation: {
          kind: pending.kind,
          geometry,
          label: label.trim(),
          color,
          ...(style ? { style } : {}),
          published,
        },
        body: comment || undefined,
      });
    } catch {
      // The app reports the failure; the form stays open so nothing is lost.
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack gap="xs" data-testid="annotation-form">
      {/* Summary on its own line: next to the kind it was truncated, and the
          point count is the part worth reading. */}
      <Stack gap={2}>
        <Group gap={6} wrap="nowrap">
          <Icon icon="mdi:draw" width={16} />
          <Text size="sm" fw={600}>
            {KIND_LABELS[pending.kind]}
          </Text>
        </Group>
        {summary && (
          <Text size="xs" c="dimmed">
            {summary}
          </Text>
        )}
      </Stack>
      <TextInput
        size="xs"
        label="Label"
        placeholder="What should readers notice?"
        required
        data-autofocus
        value={label}
        maxLength={MAX_LABEL_CHARS}
        onChange={(e) => setLabel(e.currentTarget.value)}
        onBlur={() => setTouched(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void submit();
        }}
        error={touched ? labelError : null}
      />
      <AnnotationColorPicker value={color} onChange={setColor} />
      {withRegion && (
        <RegionHighlightFields
          enabled={highlight}
          onEnabledChange={setHighlight}
          opacity={fillOpacity}
          onOpacityChange={setFillOpacity}
        />
      )}
      <Textarea
        size="xs"
        label="Comment"
        placeholder="Optional: start the discussion"
        autosize
        minRows={2}
        maxRows={5}
        maxLength={4000}
        value={body}
        onChange={(e) => setBody(e.currentTarget.value)}
      />
      <Switch
        size="xs"
        label="Visible to viewers"
        description="Viewers see the shape and its label, never the comments"
        checked={published}
        onChange={(e) => setPublished(e.currentTarget.checked)}
      />
      <Group justify="flex-end" gap="xs">
        <Button size="xs" variant="default" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button size="xs" onClick={() => void submit()} loading={saving} disabled={touched && !!labelError}>
          Save
        </Button>
      </Group>
    </Stack>
  );
};

export default AnnotationForm;
