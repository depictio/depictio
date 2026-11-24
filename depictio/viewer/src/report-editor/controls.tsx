import React from 'react';
import { SegmentedControl, Stack, Text } from '@mantine/core';
import type { LucideIcon } from 'lucide-react';

import { STROKE } from '../chrome/variants/glass/icons';

/** One option of an `IconSegmented`: its value, its label and a light icon. */
export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  icon: LucideIcon;
}

interface IconSegmentedProps<T extends string> {
  /** The field's name above the control; none when the context says it. */
  label?: string;
  value: T;
  options: SegmentOption<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  /** A line under the control: what the current choice does. */
  hint?: React.ReactNode;
  'data-testid'?: string;
}

/** The editor's segmented control: one size, a light icon before each label,
 *  the field's name above it in the same type as every other field of the
 *  editor (the tile settings, the report settings). */
export function IconSegmented<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
  hint,
  'data-testid': testId,
}: IconSegmentedProps<T>) {
  return (
    <Stack gap={4}>
      {label && (
        <Text size="xs" fw={500}>
          {label}
        </Text>
      )}
      <SegmentedControl
        size="xs"
        fullWidth
        value={value}
        disabled={disabled}
        onChange={(v) => onChange(v as T)}
        data-testid={testId}
        data={options.map(({ value: v, label: l, icon: I }) => ({
          value: v,
          label: (
            <span className="re-seg-option">
              <I size={14} strokeWidth={STROKE} aria-hidden />
              <span>{l}</span>
            </span>
          ),
        }))}
      />
      {hint && (
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      )}
    </Stack>
  );
}
