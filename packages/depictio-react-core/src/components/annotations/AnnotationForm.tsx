import React, { useState } from 'react';
import {
  Button,
  ColorSwatch,
  Group,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { AnnotationDraft, PendingAnnotation } from '../../annotations/AnnotationLayerContext';
import { defaultColorFor, KIND_LABELS, validateLabel } from '../../annotations/layer';
import { ANNOTATION_COLORS, MAX_LABEL_CHARS } from '../../annotations/types';
import type { AnnotationColor } from '../../annotations/types';

export interface AnnotationFormProps {
  pending: PendingAnnotation;
  onSave: (draft: AnnotationDraft) => Promise<void>;
  onCancel: () => void;
}

function geometrySummary(p: PendingAnnotation): string | null {
  const g = p.geometry;
  switch (g.kind) {
    case 'x_range':
      return `x from ${g.x0} to ${g.x1}`;
    case 'y_range':
      return `y from ${g.y0} to ${g.y1}`;
    case 'ref_line':
      return `${g.axis} = ${g.value}`;
    case 'points': {
      const n = g.ids?.length ?? g.coords?.length ?? 0;
      return `${n} point${n === 1 ? '' : 's'}`;
    }
    case 'arrow_note':
      return `at (${g.x}, ${g.y})`;
  }
}

/**
 * Label, colour, optional comment and visibility of an annotation that was
 * just drawn. Colours are Mantine palette names rendered through the theme's
 * CSS variables, so the swatches follow light/dark mode like the shapes.
 */
const AnnotationForm: React.FC<AnnotationFormProps> = ({ pending, onSave, onCancel }) => {
  const [label, setLabel] = useState('');
  const [color, setColor] = useState<AnnotationColor>(defaultColorFor(pending.kind));
  const [body, setBody] = useState('');
  const [published, setPublished] = useState(false);
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState(false);

  const labelError = validateLabel(label);
  const summary = geometrySummary(pending);

  const submit = async () => {
    setTouched(true);
    if (labelError || saving) return;
    setSaving(true);
    try {
      const comment = body.trim();
      await onSave({
        annotation: {
          kind: pending.kind,
          geometry: pending.geometry,
          label: label.trim(),
          color,
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
      <Group gap={6} wrap="nowrap">
        <Icon icon="mdi:draw" width={16} />
        <Text size="sm" fw={600}>
          {KIND_LABELS[pending.kind]}
        </Text>
        {summary && (
          <Text size="xs" c="dimmed" truncate>
            {summary}
          </Text>
        )}
      </Group>
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
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Color
        </Text>
        <Group gap={4}>
          {ANNOTATION_COLORS.map((c) => (
            <Tooltip key={c} label={c} withArrow openDelay={300}>
              <UnstyledButton
                onClick={() => setColor(c)}
                aria-label={`Color ${c}`}
                aria-pressed={color === c}
              >
                <ColorSwatch
                  color={`var(--mantine-color-${c}-filled)`}
                  size={18}
                  withShadow={color === c}
                >
                  {color === c && (
                    <Icon
                      icon="mdi:check"
                      width={12}
                      style={{ color: 'var(--mantine-color-white)' }}
                    />
                  )}
                </ColorSwatch>
              </UnstyledButton>
            </Tooltip>
          ))}
        </Group>
      </Stack>
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
