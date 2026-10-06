/**
 * The filter bar's compact controls, one per kind of interactive component.
 *
 * Each reads the same data and emits the same filter events as its Filters
 * panel counterpart: the fetching lives in `useInteractiveData`, the option
 * order and the event shape in `categoricalOptions`, the slider bounds in
 * `numericScale`. Only the drawing differs.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  MultiSelect,
  RangeSlider,
  Select,
  Skeleton,
  Slider,
  Switch,
  Text,
  type ComboboxItem,
  type ComboboxLikeRenderOptionInput,
} from '@mantine/core';

import type { InteractiveFilter, StoredMetadata } from '../../../api';
import { useAvailableSet } from '../../../availableValues';
import { useBrandScopeAttributes } from '../../branding/BrandScope';
import { useCategoryDotColors } from '../../../hooks/useCategoryColors';
import {
  categoricalDisplay,
  chipFilterValue,
  chipSelectionMode,
  filterEvent,
  orderCategoricalOptions,
  selectedValues,
  toggleChip,
} from '../categoricalOptions';
import { coerceBool } from '../CheckboxSwitchRenderer';
import DatePickerRenderer from '../DatePickerRenderer';
import {
  buildNumericScale,
  formatSliderValue,
  rangeSliderBounds,
  sliderBounds,
} from '../numericScale';
import { useColumnRange, useUniqueValues } from '../useInteractiveData';
import { isFullRange } from './stripLayout';

export interface StripControlProps {
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** The filter's label, for the control's accessible name. */
  label: string;
}

const filterValueOf = (filters: InteractiveFilter[], index: string): unknown =>
  filters.find((f) => f.index === index)?.value;

const ControlSkeleton: React.FC = () => (
  <Skeleton height={40} radius="md" style={{ flex: 1, minWidth: 120 }} />
);

const ControlMessage: React.FC<{ error?: boolean; children: React.ReactNode }> = ({
  error,
  children,
}) => (
  <Text size="xs" c={error ? 'red' : 'dimmed'} truncate>
    {children}
  </Text>
);

// ------------------------------------------------------------- categorical

/**
 * MultiSelect, Select and SegmentedControl as a grey track of toggle chips.
 * A chip carries a colour dot only when the dashboard gives its column colours
 * (`category_colors`): there the dot is the colour the figures draw the value
 * in. Past `MAX_STRIP_CHIPS` values the chips no longer fit, and a compact
 * select drawn as the same track takes over.
 */
export const StripCategorical: React.FC<StripControlProps> = ({
  metadata,
  filters,
  onFilterChange,
  label,
}) => {
  const type = metadata.interactive_component_type;
  const { data: options, loading, error } = useUniqueValues(
    metadata.dc_id,
    metadata.column_name,
    metadata.filter_expr,
  );
  const availableSet = useAvailableSet(metadata.dc_id, metadata.column_name, metadata.index);
  const ordered = useMemo(
    () => orderCategoricalOptions(options, availableSet),
    [options, availableSet],
  );
  // Keyed on the full universe, not on `ordered`: a value keeps its colour
  // while the funnel greys other values out. Null: the column has no colours.
  const dots = useCategoryDotColors(metadata.column_name, options);
  const selected = selectedValues(filterValueOf(filters, metadata.index));
  const mode = chipSelectionMode(type);
  const emit = (next: string[]) =>
    onFilterChange?.(filterEvent(metadata, chipFilterValue(next, type)));

  if (loading) return <ControlSkeleton />;
  if (error) return <ControlMessage error>Could not load values</ControlMessage>;
  if (options.length === 0) return <ControlMessage>No values</ControlMessage>;

  if (categoricalDisplay(options.length) === 'select') {
    return (
      <StripSelect
        options={ordered}
        available={availableSet}
        dots={dots}
        selected={selected}
        multiple={mode === 'multi'}
        label={label}
        onChange={emit}
      />
    );
  }

  return (
    <div
      className="depictio-strip-track"
      role="group"
      aria-label={label}
      data-has-selection={selected.length > 0}
      data-dots={dots ? 'true' : 'false'}
    >
      {ordered.map((value) => {
        const on = selected.includes(value);
        // A selected value stays clickable even once the funnel has exhausted
        // it, or it could never be deselected.
        const disabled = Boolean(availableSet) && !availableSet!.has(value) && !on;
        return (
          <button
            key={value}
            type="button"
            className="depictio-strip-chip"
            aria-pressed={on}
            disabled={disabled}
            title={disabled ? `${value}: no data left under the other filters` : value}
            onClick={() => emit(toggleChip(selected, value, mode))}
            style={dots ? ({ '--chip-color': dots.get(value) } as React.CSSProperties) : undefined}
          >
            {dots && <span className="depictio-strip-chip__dot" aria-hidden />}
            <span>{value}</span>
          </button>
        );
      })}
    </div>
  );
};

const StripSelect: React.FC<{
  options: string[];
  available: Set<string> | null;
  dots: Map<string, string> | null;
  selected: string[];
  multiple: boolean;
  label: string;
  onChange: (next: string[]) => void;
}> = ({ options, available, dots, selected, multiple, label, onChange }) => {
  const scope = useBrandScopeAttributes();
  const data = useMemo(
    () =>
      options.map((value) => ({
        value,
        label: value,
        disabled: available ? !available.has(value) && !selected.includes(value) : false,
      })),
    [options, available, selected],
  );
  const renderOption = ({ option }: ComboboxLikeRenderOptionInput<ComboboxItem>) => (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      {dots && (
        <span
          className="depictio-strip-chip__dot"
          style={{ '--chip-color': dots.get(option.value) } as React.CSSProperties}
          aria-hidden
        />
      )}
      {option.label}
    </span>
  );
  const shared = {
    'aria-label': label,
    data,
    size: 'sm' as const,
    radius: 'md' as const,
    searchable: true,
    clearable: true,
    maxDropdownHeight: 260,
    className: 'depictio-strip-select',
    classNames: { input: 'depictio-strip-select__input' },
    renderOption,
    // Portaled to <body>, so the dropdown is put back inside the dashboard's
    // brand scope by hand (see `useBrandScopeAttributes`).
    comboboxProps: {
      withinPortal: true,
      portalProps: scope
        ? ({
            className: scope.className,
            'data-mantine-color-scheme': scope['data-mantine-color-scheme'],
          } as React.ComponentPropsWithoutRef<'div'>)
        : undefined,
    },
  };
  return multiple ? (
    <MultiSelect
      {...shared}
      value={selected}
      onChange={onChange}
      placeholder={selected.length ? undefined : `All ${options.length}`}
    />
  ) : (
    <Select
      {...shared}
      value={selected[0] ?? null}
      onChange={(v) => onChange(v ? [v] : [])}
      placeholder={`All ${options.length}`}
    />
  );
};

// ----------------------------------------------------------------- numeric

/** Shared look of both sliders: a 4px track, hollow 16px handles in the
 *  filter's accent (the brand's primary unless the author picked one). */
const SLIDER_CLASSES = {
  root: 'depictio-strip-slider',
  thumb: 'depictio-strip-slider__thumb',
  bar: 'depictio-strip-slider__bar',
};

const Readout: React.FC<{ left: string; right?: string }> = ({ left, right }) => (
  <div className="depictio-strip-readout" aria-hidden>
    <span>{left}</span>
    {right !== undefined && <span>{right}</span>}
  </div>
);

/**
 * RangeSlider as a thin inline slider. Emits `[low, high]` on release, like
 * the panel's; a release on the column's full extent clears the filter
 * (`null`, what the panel's reset emits) instead of pinning a range that
 * filters nothing.
 */
export const StripRange: React.FC<StripControlProps & { accent: string }> = ({
  metadata,
  filters,
  onFilterChange,
  label,
  accent,
}) => {
  const { data: range, loading } = useColumnRange(metadata.dc_id, metadata.column_name);
  const bounds = useMemo(() => rangeSliderBounds(range), [range]);
  const scale = useMemo(
    () => (bounds ? buildNumericScale(bounds, { marksNumber: 2 }) : null),
    [bounds],
  );
  const stored = filterValueOf(filters, metadata.index);
  const selected =
    Array.isArray(stored) &&
    stored.length === 2 &&
    typeof stored[0] === 'number' &&
    typeof stored[1] === 'number'
      ? (stored as [number, number])
      : null;
  const full: [number, number] | null = bounds ? [bounds.min, bounds.max] : null;
  const [local, setLocal] = useState<[number, number] | null>(selected ?? full);
  // Follow the stored value (a reset, another tab, the active-filter chips).
  useEffect(() => {
    setLocal(selected ?? full);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.[0], selected?.[1], full?.[0], full?.[1]]);

  if (loading || !bounds || !scale || !local) return <ControlSkeleton />;

  return (
    <>
      <RangeSlider
        aria-label={label}
        min={bounds.min}
        max={bounds.max}
        step={scale.step}
        restrictToMarks={scale.discrete}
        // A restricted slider needs its marks to snap to; their labels would
        // only crowd a 40px row.
        marks={scale.discrete ? scale.marks.map((m) => ({ value: m.value })) : undefined}
        minRange={scale.discrete ? 0 : (bounds.max - bounds.min) / 1000}
        value={local}
        onChange={setLocal}
        onChangeEnd={(next) =>
          onFilterChange?.(
            filterEvent(
              metadata,
              isFullRange(next, bounds.min, bounds.max) ? null : next,
              'RangeSlider',
            ),
          )
        }
        label={null}
        size={4}
        thumbSize={16}
        color={accent}
        classNames={SLIDER_CLASSES}
      />
      <Readout left={formatSliderValue(local[0])} right={formatSliderValue(local[1])} />
    </>
  );
};

/** Slider as a thin inline slider with one handle. Same value space and the
 *  same event as `SliderRenderer`, log10 scale included. */
export const StripSlider: React.FC<StripControlProps & { accent: string }> = ({
  metadata,
  filters,
  onFilterChange,
  label,
  accent,
}) => {
  const defaultState = (metadata.default_state || {}) as Record<string, unknown>;
  const logScale = ((defaultState.scale as string) || 'linear') === 'log10';
  const { data: range, loading, error: fetchError } = useColumnRange(
    metadata.dc_id,
    metadata.column_name,
  );
  const { bounds, error: boundsError } = useMemo(
    () => sliderBounds(range, metadata.column_name, logScale),
    [range, metadata.column_name, logScale],
  );
  const scale = useMemo(
    () => (bounds ? buildNumericScale(bounds, { marksNumber: 2, continuous: logScale }) : null),
    [bounds, logScale],
  );
  const stored = filterValueOf(filters, metadata.index);
  const selected = typeof stored === 'number' ? stored : null;
  const [local, setLocal] = useState<number | null>(selected ?? bounds?.min ?? null);
  useEffect(() => {
    setLocal(selected ?? bounds?.min ?? null);
  }, [selected, bounds?.min]);

  const error = fetchError ?? boundsError;
  if (error) return <ControlMessage error>{error}</ControlMessage>;
  if (loading || !bounds || !scale || local === null) return <ControlSkeleton />;

  const readout = (v: number) => formatSliderValue(logScale ? 10 ** v : v);
  return (
    <>
      <Slider
        aria-label={label}
        min={bounds.min}
        max={bounds.max}
        step={scale.step}
        restrictToMarks={scale.discrete}
        marks={scale.discrete ? scale.marks.map((m) => ({ value: m.value })) : undefined}
        value={local}
        onChange={setLocal}
        onChangeEnd={(next) => onFilterChange?.(filterEvent(metadata, next, 'Slider'))}
        label={null}
        size={4}
        thumbSize={16}
        color={accent}
        classNames={SLIDER_CLASSES}
      />
      <Readout left={readout(local)} />
    </>
  );
};

// ------------------------------------------------------------ toggle, date

/** Switch and Checkbox both draw as a small switch: the bar's label already
 *  names the filter, so the box-with-caption of a checkbox has nothing to add. */
export const StripToggle: React.FC<StripControlProps & { accent: string }> = ({
  metadata,
  filters,
  onFilterChange,
  label,
  accent,
}) => {
  const stored = filterValueOf(filters, metadata.index);
  const checked =
    typeof stored === 'boolean' ? stored : coerceBool(metadata.default_state?.default_value);
  return (
    <Switch
      aria-label={label}
      size="md"
      color={accent}
      checked={checked}
      onChange={(e) => onFilterChange?.(filterEvent(metadata, e.currentTarget.checked))}
    />
  );
};

/** The panel's date-range picker itself, bare and small. */
export const StripDate: React.FC<StripControlProps> = ({ metadata, filters, onFilterChange }) => (
  <DatePickerRenderer metadata={metadata} filters={filters} onChange={onFilterChange} bare />
);
