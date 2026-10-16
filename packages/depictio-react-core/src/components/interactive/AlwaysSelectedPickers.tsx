/**
 * The automatic pick of `always_selected` Select filters, made where the
 * filter state lives rather than in the control.
 *
 * A control only exists while it is drawn, and a filter often is not: the
 * panel collapsed (on a landing tab by default, or remembered from a previous
 * visit), its section folded, the phone drawer closed. A pick made by the
 * control would then never happen, and the single-unit tiles the filter feeds
 * would open on every unit at once. A host (the viewer, the editor) mounts
 * this once, inside its `AvailableFilterValuesProvider`, for every component
 * whose filters it holds; it renders nothing.
 */
import React, { useEffect, useMemo, useRef } from 'react';

import type { InteractiveFilter, StoredMetadata } from '../../api';
import { autoPickValue, ownFilterValues } from './alwaysSelected';
import { filterEvent } from './categoricalOptions';
import { alwaysSelectedComponents } from './scope';
import { useScopeOptions } from './useScopeOptions';

const AlwaysSelectedPicker: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onFilterChange: (filter: InteractiveFilter) => void;
}> = ({ metadata, filters, onFilterChange }) => {
  // The same option list, in the same order, as the panel's Select
  // (`MultiSelectRenderer`): "the first option" is the one a reader sees first.
  const { options: ordered, loading } = useScopeOptions(metadata);
  const pick = autoPickValue({
    enabled: true,
    loading,
    selected: ownFilterValues(filters, metadata.index),
    options: ordered,
  });
  // Keyed on the picked value, so it fires once per such state and stays idle
  // while an offered value is held (or if the host ignores the change), which
  // rules out a loop.
  const pickKey = pick?.[0] ?? null;
  const latest = useRef({ metadata, onFilterChange });
  latest.current = { metadata, onFilterChange };
  useEffect(() => {
    if (pickKey === null) return;
    const { metadata: m, onFilterChange: emit } = latest.current;
    emit(filterEvent(m, [pickKey]));
  }, [pickKey]);
  return null;
};

export const AlwaysSelectedPickers: React.FC<{
  /** Every component whose filter state `filters` holds. */
  components: readonly StoredMetadata[];
  filters: InteractiveFilter[];
  onFilterChange: (filter: InteractiveFilter) => void;
}> = ({ components, filters, onFilterChange }) => {
  const pickers = useMemo(() => alwaysSelectedComponents(components), [components]);
  if (pickers.length === 0) return null;
  return (
    <>
      {pickers.map((m) => (
        <AlwaysSelectedPicker
          key={m.index}
          metadata={m}
          filters={filters}
          onFilterChange={onFilterChange}
        />
      ))}
    </>
  );
};

export default AlwaysSelectedPickers;
