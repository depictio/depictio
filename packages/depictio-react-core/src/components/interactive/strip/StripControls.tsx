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
  Popover,
  RangeSlider,
  Skeleton,
  Slider,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';

import type { InteractiveFilter, StoredMetadata } from '../../../api';
import { useAvailableSet } from '../../../availableValues';
import { useBrandScopeAttributes } from '../../branding/BrandScope';
import { useCategoryDotColors } from '../../../hooks/useCategoryColors';
import {
  MAX_STRIP_CHIPS,
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
 * MultiSelect, Select and SegmentedControl as a grey track of toggle chips,
 * each with its value's colour dot (`chipCategoryDots`: the dashboard's
 * colours for the column, else the colorway's for a column this short).
 * Wider than its cell, the track wraps onto a second line rather than hiding
 * values past the edge. Past `MAX_STRIP_CHIPS` values a picker drawn as the
 * same track takes over (`StripSelect`), with the values one per line.
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
  // while the funnel greys other values out. Null: no dots for this column.
  const dots = useCategoryDotColors(metadata.column_name, options, MAX_STRIP_CHIPS);
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
      className="depictio-strip-track depictio-strip-track--chips"
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

/** Past this many values the picker offers a search field. */
const PICKER_SEARCH_MIN = 10;
/** Selected values the closed picker spells out before "+n". */
const PICKER_SHOWN = 2;

/**
 * The bar's picker for a column with too many values for a track of chips.
 *
 * Closed, it is the grey track itself, holding "All N" or the picked values as
 * pressed chips (their colour dot included). Open, it lists every value in one
 * column, each a full-width chip of the bar with a tick when picked, under a
 * search field once the list is long, and over a count and a Clear. A one-of-N
 * filter closes on pick; a multi one stays open. A Mantine Select would have
 * been a second design for the same control.
 */
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
  const [opened, setOpened] = useState(false);
  const [query, setQuery] = useState('');
  const mode = multiple ? 'multi' : 'single';
  const q = query.trim().toLowerCase();
  const shown = q ? options.filter((v) => v.toLowerCase().includes(q)) : options;
  const dotStyle = (value: string) =>
    dots ? ({ '--chip-color': dots.get(value) } as React.CSSProperties) : undefined;
  const pick = (value: string) => {
    onChange(toggleChip(selected, value, mode));
    if (!multiple) setOpened(false);
  };
  const close = () => {
    setOpened(false);
    setQuery('');
  };

  return (
    <Popover
      opened={opened}
      onChange={(o) => (o ? setOpened(true) : close())}
      position="bottom-start"
      offset={6}
      radius="md"
      shadow="md"
      width="target"
      // Focus moves into the dropdown on open, so the search field (marked
      // `data-autofocus`) takes the keys straight away.
      trapFocus
      withinPortal
      // Portaled to <body>, so the dropdown is put back inside the dashboard's
      // brand scope by hand (see `useBrandScopeAttributes`).
      portalProps={
        scope
          ? ({
              className: scope.className,
              'data-mantine-color-scheme': scope['data-mantine-color-scheme'],
            } as React.ComponentPropsWithoutRef<'div'>)
          : undefined
      }
    >
      <Popover.Target>
        <button
          type="button"
          className="depictio-strip-track depictio-strip-picker"
          aria-label={label}
          aria-haspopup="dialog"
          aria-expanded={opened}
          data-has-selection={selected.length > 0}
          onClick={() => (opened ? close() : setOpened(true))}
        >
          <span className="depictio-strip-picker__values">
            {selected.length === 0 ? (
              <span className="depictio-strip-picker__all">All {options.length}</span>
            ) : (
              <>
                {selected.slice(0, PICKER_SHOWN).map((value) => (
                  <span
                    key={value}
                    className="depictio-strip-chip"
                    aria-pressed="true"
                    style={dotStyle(value)}
                  >
                    {dots && <span className="depictio-strip-chip__dot" aria-hidden />}
                    <span>{value}</span>
                  </span>
                ))}
                {selected.length > PICKER_SHOWN && (
                  <span className="depictio-strip-picker__more">
                    +{selected.length - PICKER_SHOWN}
                  </span>
                )}
              </>
            )}
          </span>
          <svg
            className="depictio-strip-picker__chevron"
            viewBox="0 0 24 24"
            width="16"
            height="16"
            aria-hidden
          >
            <path d="M7 10l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
      </Popover.Target>
      <Popover.Dropdown className="depictio-strip-picker__dropdown" p={8}>
        {options.length >= PICKER_SEARCH_MIN && (
          <TextInput
            size="xs"
            radius="md"
            placeholder={`Search ${options.length} values`}
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
            data-autofocus
            mb={8}
            aria-label={`Search ${label}`}
          />
        )}
        <div
          className="depictio-strip-picker__list"
          role="group"
          aria-label={label}
          data-has-selection={selected.length > 0}
        >
          {shown.map((value) => {
            const on = selected.includes(value);
            const disabled = Boolean(available) && !available!.has(value) && !on;
            return (
              <button
                key={value}
                type="button"
                className="depictio-strip-chip"
                aria-pressed={on}
                disabled={disabled}
                title={disabled ? `${value}: no data left under the other filters` : value}
                onClick={() => pick(value)}
                style={dotStyle(value)}
              >
                {dots && <span className="depictio-strip-chip__dot" aria-hidden />}
                <span className="depictio-strip-chip__label">{value}</span>
                <svg
                  className="depictio-strip-chip__tick"
                  viewBox="0 0 24 24"
                  width="16"
                  height="16"
                  aria-hidden
                >
                  <path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" strokeWidth="2.2" />
                </svg>
              </button>
            );
          })}
          {shown.length === 0 && (
            <span className="depictio-strip-picker__all">No value matches “{query}”</span>
          )}
        </div>
        <div className="depictio-strip-picker__foot">
          <span>
            {selected.length > 0 ? `${selected.length} of ${options.length}` : `All ${options.length}`}
          </span>
          {selected.length > 0 && (
            <button type="button" className="depictio-strip-picker__clear" onClick={() => onChange([])}>
              Clear
            </button>
          )}
        </div>
      </Popover.Dropdown>
    </Popover>
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
