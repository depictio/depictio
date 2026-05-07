import React, { useCallback, useEffect, useState } from 'react';
import { Paper, Stack, Text, Group, RangeSlider } from '@mantine/core';
import { Icon } from '@iconify/react';

/**
 * RangeSlider interactive filter — selects a numeric [min, max] range.
 * Mirrors what `_build_select_component` produces for
 * interactive_component_type === "RangeSlider":
 *   - dmc.RangeSlider with marks at min/max/midpoints
 *   - emits the selected [low, high] tuple via setProps({value})
 */
export interface DepictioRangeSliderProps {
  id?: string | Record<string, string>;
  title?: string;
  column_name?: string;
  interactive_component_type?: string;
  /** Available range bounds. */
  min?: number;
  max?: number;
  /** Step size; defaults to (max-min)/100 if absent. */
  step?: number;
  /** Marks count; default 5. */
  marks_number?: number;
  /** When false, suppress tick marks for a denser look. Defaults to true. */
  show_marks?: boolean;
  /** Compact rendering: drop the outer Paper, tighten internal spacing, and
   *  shrink the title row. Used when this slider is embedded inside another
   *  Paper-bearing container (e.g. InteractiveGroupCard). */
  compact?: boolean;
  /** Currently selected [low, high]. Defaults to [min, max]. */
  value?: [number, number] | null;
  color?: string;
  icon_name?: string;
  icon_color?: string;
  title_color?: string;
  title_size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  setProps?: (props: Partial<DepictioRangeSliderProps>) => void;
  onChange?: (value: [number, number]) => void;
}

const DepictioRangeSlider: React.FC<DepictioRangeSliderProps> = ({
  title,
  column_name,
  interactive_component_type,
  min = 0,
  max = 100,
  step,
  // Default = 2 marks (just min + max). Caller can override via metadata.
  marks_number = 2,
  show_marks = true,
  compact = false,
  value,
  color,
  icon_name,
  icon_color,
  title_color,
  title_size = 'sm',
  setProps,
  onChange,
}) => {
  const safeMin = Number.isFinite(min) ? min : 0;
  const safeMax = Number.isFinite(max) ? max : 100;
  const initial: [number, number] =
    value && value.length === 2 ? value : [safeMin, safeMax];

  const [local, setLocal] = useState<[number, number]>(initial);

  useEffect(() => {
    if (value && value.length === 2) setLocal(value);
  }, [value?.[0], value?.[1]]);

  const handleChange = useCallback((next: [number, number]) => {
    setLocal(next);
  }, []);

  const handleChangeEnd = useCallback(
    (next: [number, number]) => {
      // Drop filter if it equals the full unfiltered range.
      const isFull = next[0] === safeMin && next[1] === safeMax;
      const emit = isFull ? null : next;
      if (setProps) setProps({ value: emit ?? undefined });
      if (onChange && emit) onChange(emit);
    },
    [setProps, onChange, safeMin, safeMax],
  );

  // Mark generation between [safeMin, safeMax] at marks_number positions.
  // When show_marks is false the slider renders without any tick labels —
  // used for compact group rendering where labels would compete for space.
  const marks = React.useMemo(() => {
    if (!show_marks) return undefined;
    const n = Math.max(2, marks_number);
    const stepSize = (safeMax - safeMin) / (n - 1);
    return Array.from({ length: n }, (_, i) => {
      const v = safeMin + stepSize * i;
      return { value: v, label: formatMark(v) };
    });
  }, [safeMin, safeMax, marks_number, show_marks]);

  const displayTitle =
    title ||
    (column_name
      ? `${interactive_component_type || 'Range'} on ${column_name}`
      : '');
  const resolveColor = (c?: string): string | undefined => {
    if (!c) return undefined;
    if (c.startsWith('#') || c.startsWith('rgb') || c.startsWith('var(')) return c;
    return `var(--mantine-color-${c}-6)`;
  };
  const iconCol =
    resolveColor(icon_color) ||
    resolveColor(color) ||
    'var(--mantine-color-blue-6)';
  const titleCol =
    resolveColor(title_color) ||
    resolveColor(color) ||
    'var(--mantine-color-text)';

  // Compact mode: render the slider inline (no Paper, smaller title row,
  // tighter spacing) so a parent container's frame is the only visible one.
  const sliderTitleSize: 'xs' | 'sm' | 'md' | 'lg' | 'xl' = compact ? 'xs' : title_size;
  const stackGap = compact ? 2 : 6;
  const sliderMb = compact ? 0 : 'xs';
  const inner = (
    <Stack gap={stackGap}>
      {displayTitle && (
        <Group gap="xs" align="center" wrap="nowrap">
          {icon_name && (
            <Icon
              icon={icon_name}
              width={compact ? 14 : 18}
              height={compact ? 14 : 18}
              style={{ color: iconCol, flexShrink: 0 }}
            />
          )}
          <Text
            fw={600}
            size={sliderTitleSize}
            style={{ color: titleCol }}
            truncate
          >
            {displayTitle}
          </Text>
        </Group>
      )}
      <RangeSlider
        min={safeMin}
        max={safeMax}
        step={step ?? (safeMax - safeMin) / 100}
        value={local}
        onChange={handleChange}
        onChangeEnd={handleChangeEnd}
        marks={marks}
        minRange={(safeMax - safeMin) / 1000}
        size={compact ? 'sm' : 'md'}
        thumbSize={compact ? 12 : undefined}
        mb={sliderMb}
        // Apply the metadata color (track + thumb). Mantine accepts a token
        // name ('blue') or `color.shade` ('blue.5'); a raw hex/rgb is set
        // via the `styles` prop instead.
        color={
          color && !color.startsWith('#') && !color.startsWith('rgb')
            ? color
            : undefined
        }
        styles={
          color && (color.startsWith('#') || color.startsWith('rgb'))
            ? {
                bar: { backgroundColor: color },
                thumb: { borderColor: color, backgroundColor: color },
              }
            : undefined
        }
      />
    </Stack>
  );

  if (compact) return inner;

  return (
    <Paper
      p="xs"
      radius="md"
      shadow="xs"
      withBorder
      className="dashboard-component-hover"
      style={{
        height: '100%',
        boxSizing: 'border-box',
      }}
    >
      {inner}
    </Paper>
  );
};

function formatMark(v: number): string {
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(2).replace(/\.?0+$/, '');
}

export default DepictioRangeSlider;
