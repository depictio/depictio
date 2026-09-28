/**
 * Searchable picker for the UCSC Genome Browser tracks a genome browser shows
 * by default (`ucsc_tracks`). Options come from
 * `GET /jbrowse/ucsc/{assembly}/tracks?q=…`, searched server-side (debounced);
 * the assembly is the form's, or the collection's when the form inherits it.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Loader, MultiSelect } from '@mantine/core';
import type { ComboboxItem, ComboboxItemGroup, OptionsFilter } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import { fetchUcscTracks } from 'depictio-react-core';
import type { UcscTrackOption } from 'depictio-react-core';

const SEARCH_DEBOUNCE_MS = 300;
const SEARCH_LIMIT = 50;

// The server already filtered on the query (on names *and* labels): keep its
// answer as is instead of Mantine re-filtering it on the label alone.
const keepServerOrder: OptionsFilter = ({ options }) => options;

interface Props {
  /** Preset name or alias; null when neither the form nor the DC has one. */
  assembly: string | null;
  value: string[];
  onChange: (names: string[]) => void;
}

const optionLabel = (t: UcscTrackOption) =>
  t.label && t.label !== t.name ? `${t.label} (${t.name})` : t.name;

const UcscTrackPicker: React.FC<Props> = ({ assembly, value, onChange }) => {
  const [search, setSearch] = useState('');
  const [debounced] = useDebouncedValue(search, SEARCH_DEBOUNCE_MS);
  const [tracks, setTracks] = useState<UcscTrackOption[]>([]);
  // undefined = not asked yet; null = the assembly has no UCSC genome.
  const [genome, setGenome] = useState<string | null | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Every option seen so far, so a picked track keeps its label (and its pill)
  // once a later search no longer returns it.
  const known = useRef(new Map<string, UcscTrackOption>());

  useEffect(() => {
    setGenome(undefined);
    setTracks([]);
    known.current = new Map();
  }, [assembly]);

  useEffect(() => {
    if (!assembly) return;
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    fetchUcscTracks(assembly, debounced.trim(), SEARCH_LIMIT, ctrl.signal)
      .then((res) => {
        if (ctrl.signal.aborted) return;
        setGenome(res.genome);
        setTracks(res.tracks);
        for (const t of res.tracks) known.current.set(t.name, t);
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [assembly, debounced]);

  const data = useMemo(() => {
    const groups = new Map<string, ComboboxItem[]>();
    const listed = new Set<string>();
    const add = (group: string, item: ComboboxItem) => {
      if (listed.has(item.value)) return;
      listed.add(item.value);
      const list = groups.get(group);
      if (list) list.push(item);
      else groups.set(group, [item]);
    };
    // Picked tracks first (MultiSelect needs them in `data` to draw their pills).
    for (const name of value) {
      const t = known.current.get(name);
      add('Selected', { value: name, label: t ? optionLabel(t) : name });
    }
    for (const t of tracks) add(t.group || 'Other', { value: t.name, label: optionLabel(t) });
    return [...groups].map(
      ([group, items]): ComboboxItemGroup<ComboboxItem> => ({ group, items }),
    );
  }, [tracks, value]);

  const unavailable = !assembly || genome === null;
  const description = !assembly
    ? 'Pick an assembly (or bind a collection that declares one) to browse UCSC tracks'
    : genome === null
      ? `No UCSC genome matches ${assembly}: UCSC tracks are unavailable`
      : genome
        ? `Tracks of UCSC ${genome}, shown by default next to the manifest tracks`
        : 'UCSC tracks shown by default next to the manifest tracks';

  return (
    <MultiSelect
      label="UCSC tracks"
      description={description}
      placeholder={unavailable ? undefined : 'Search UCSC tracks'}
      data={data}
      value={value}
      onChange={onChange}
      searchable
      searchValue={search}
      onSearchChange={setSearch}
      filter={keepServerOrder}
      clearable
      hidePickedOptions
      maxDropdownHeight={280}
      nothingFoundMessage={loading ? 'Searching…' : 'No UCSC track matches'}
      disabled={unavailable && value.length === 0}
      error={error}
      leftSection={<Icon icon="mdi:web" width={14} />}
      rightSection={loading ? <Loader size={14} /> : undefined}
      data-testid="jbrowse-builder-ucsc-tracks"
    />
  );
};

export default UcscTrackPicker;
