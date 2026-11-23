/**
 * The values an `always_selected` Select offers, in the order a reader sees
 * them: the panel's own order (`orderCategoricalOptions`, values other filters
 * rule out marked disabled), then `default_by` best-ranked first. Shared by
 * the automatic pick and the scope banner, so "the first family" and the
 * banner's previous and next keys walk the same list.
 */
import { useMemo } from 'react';

import type { StoredMetadata } from '../../api';
import { useAvailableSet } from '../../availableValues';
import { rankPickOptions } from './alwaysSelected';
import { optionOrderOf, orderCategoricalOptions } from './categoricalOptions';
import { useRankedValues, useSearchedValues, useUniqueValues } from './useInteractiveData';

export interface ScopeOption {
  value: string;
  disabled: boolean;
}

const NONE: readonly string[] = [];

export function useScopeOptions(
  metadata: StoredMetadata,
  /** The values held: listed even when a cut list leaves them out. */
  held: readonly string[] = NONE,
): {
  options: ScopeOption[];
  loading: boolean;
  /** Search the server when the list was cut at its limit. */
  onSearchChange: (query: string) => void;
} {
  const { data: listed, truncated, loading } = useUniqueValues(
    metadata.dc_id,
    metadata.column_name,
    metadata.filter_expr,
    metadata.order_by,
  );
  const { values, onSearchChange } = useSearchedValues(
    metadata.dc_id,
    metadata.column_name,
    metadata.filter_expr,
    metadata.order_by,
    listed,
    truncated,
    held,
  );
  const availableSet = useAvailableSet(metadata.dc_id, metadata.column_name, metadata.index);
  const { data: ranking, loading: rankLoading } = useRankedValues(
    metadata.dc_id,
    metadata.column_name,
    metadata.default_by,
    metadata.default_order,
  );
  const options = useMemo(
    () =>
      rankPickOptions(
        orderCategoricalOptions(values, availableSet, optionOrderOf(metadata)).map((value) => ({
          value,
          disabled: availableSet ? !availableSet.has(value) : false,
        })),
        ranking,
      ),
    [values, availableSet, ranking, metadata],
  );
  return { options, loading: loading || rankLoading, onSearchChange };
}
