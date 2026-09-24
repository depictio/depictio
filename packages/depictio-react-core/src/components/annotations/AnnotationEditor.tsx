import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Group, SegmentedControl, Stack, Text, TextInput } from '@mantine/core';

import {
  annotationPatch,
  effectiveStyle,
  hasRegion,
  STROKE_WIDTH_MAX,
  STROKE_WIDTH_MIN,
} from '../../annotations/edit';
import type { AnnotationPatchInput, EffectiveStyle } from '../../annotations/edit';
import { KIND_LABELS, validateLabel } from '../../annotations/layer';
import { DEFAULT_COLOR } from '../../annotations/toPlotly';
import { MAX_LABEL_CHARS } from '../../annotations/types';
import type { Annotation, AnnotationColor } from '../../annotations/types';
import AnnotationColorPicker from './AnnotationColorPicker';
import { LabelledSlider, OpacitySlider, RegionHighlightFields } from './AnnotationStyleFields';

export type { AnnotationPatchInput } from '../../annotations/edit';

export interface AnnotationEditorProps {
  /** Current annotation of the thread. */
  annotation: Annotation;
  /** Rejects on failure; the editor then stays open with the edits. */
  onSave: (patch: AnnotationPatchInput) => Promise<void>;
  onCancel: () => void;
  /**
   * The unsaved changes, reported whenever they change so the chart can draw
   * them live; `{}` when the editor unmounts (saved or cancelled).
   */
  onDraftChange?: (patch: AnnotationPatchInput) => void;
}

const DASH_OPTIONS = [
  { value: 'solid', label: 'Solid' },
  { value: 'dash', label: 'Dashed' },
  { value: 'dot', label: 'Dotted' },
];

/**
 * Edit an existing annotation: label, colour and the style controls relevant
 * to its kind. Only changed fields are sent; a changed style is sent whole.
 * Publishing stays on the thread card.
 */
export const AnnotationEditor: React.FC<AnnotationEditorProps> = ({
  annotation,
  onSave,
  onCancel,
  onDraftChange,
}) => {
  const [label, setLabel] = useState(annotation.label);
  const [color, setColor] = useState<AnnotationColor>(annotation.color ?? DEFAULT_COLOR);
  const [style, setStyle] = useState<EffectiveStyle>(() => effectiveStyle(annotation));
  const [keepRegion, setKeepRegion] = useState(true);
  const [saving, setSaving] = useState(false);

  const withRegion = hasRegion(annotation.geometry);
  const labelError = validateLabel(label);
  const patch = useMemo(
    () => annotationPatch(annotation, { label, color, style, keepRegion }),
    [annotation, label, color, style, keepRegion],
  );
  const dirty = Object.keys(patch).length > 0;
  const onDraftChangeRef = useRef(onDraftChange);
  onDraftChangeRef.current = onDraftChange;
  useEffect(() => {
    onDraftChangeRef.current?.(patch);
  }, [patch]);
  // Closing the editor puts the saved version back on the chart.
  useEffect(() => () => onDraftChangeRef.current?.({}), []);
  const setStyleField = <K extends keyof EffectiveStyle>(key: K, value: EffectiveStyle[K]) =>
    setStyle((s) => ({ ...s, [key]: value }));

  const submit = async () => {
    if (labelError || saving || !dirty) return;
    setSaving(true);
    try {
      await onSave(patch);
    } catch {
      // The app reports the failure; the editor stays open so nothing is lost.
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack gap="xs" data-testid="annotation-editor">
      <Text size="sm" fw={600}>
        Edit {KIND_LABELS[annotation.kind].toLowerCase()}
      </Text>
      <TextInput
        size="xs"
        label="Label"
        required
        data-autofocus
        value={label}
        maxLength={MAX_LABEL_CHARS}
        onChange={(e) => setLabel(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void submit();
        }}
        error={labelError}
      />
      <AnnotationColorPicker value={color} onChange={setColor} />
      {annotation.kind === 'range' && (
        <OpacitySlider
          label="Opacity"
          value={style.opacity}
          onChange={(v) => setStyleField('opacity', v)}
          testId="annotation-opacity"
        />
      )}
      {annotation.kind === 'line' && (
        <>
          <Stack gap={2}>
            <Text size="xs" fw={500}>
              Line style
            </Text>
            <SegmentedControl
              size="xs"
              data={DASH_OPTIONS}
              value={style.dash}
              onChange={(v) => setStyleField('dash', v as EffectiveStyle['dash'])}
              data-testid="annotation-dash"
            />
          </Stack>
          <LabelledSlider
            label="Line width"
            value={style.width}
            onChange={(v) => setStyleField('width', v)}
            min={STROKE_WIDTH_MIN}
            max={STROKE_WIDTH_MAX}
            step={0.5}
            testId="annotation-width"
          />
        </>
      )}
      {annotation.kind === 'points' && (
        <>
          <LabelledSlider
            label="Ring width"
            value={style.width}
            onChange={(v) => setStyleField('width', v)}
            min={STROKE_WIDTH_MIN}
            max={STROKE_WIDTH_MAX}
            step={0.5}
            testId="annotation-width"
          />
          {withRegion && (
            <RegionHighlightFields
              enabled={keepRegion}
              onEnabledChange={setKeepRegion}
              opacity={style.fillOpacity}
              onOpacityChange={(v) => setStyleField('fillOpacity', v)}
            />
          )}
        </>
      )}
      <Group justify="flex-end" gap="xs">
        <Button size="xs" variant="default" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button
          size="xs"
          onClick={() => void submit()}
          loading={saving}
          disabled={!dirty || !!labelError}
          data-testid="annotation-editor-save"
        >
          Save
        </Button>
      </Group>
    </Stack>
  );
};

export default AnnotationEditor;
