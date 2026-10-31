/**
 * Searchable picker for the UCSC Genome Browser tracks a genome browser shows
 * by default (`ucsc_tracks`). Options come from
 * `GET /jbrowse/ucsc/{assembly}/tracks`, searched server-side (debounced) and
 * paged: the list loads the next page when scrolled to its end, and says how
 * many tracks match. A group selector narrows to one UCSC group (Variation,
 * Regulation...) with its match count; options are headed by the UCSC
 * collection (composite track) they belong to. The assembly is the form's, or
 * the collection's when the form inherits it.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Loader, MultiSelect, Select, Stack } from '@mantine/core';
import type { ComboboxItem, ComboboxItemGroup, OptionsFilter } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import { fetchUcscTracks } from 'depictio-react-core';
import type { UcscTrackGroup, UcscTrackOption } from 'depictio-react-core';

const SEARCH_DEBOUNCE_MS = 300;
const PAGE_SIZE = 100;
// Select needs a non-empty value for "every group"; '' is the ungrouped tracks.
const ALL_GROUPS = '*';

// The server already filtered on the query (on names, labels and collections):
// keep its answer as is instead of Mantine re-filtering it on the label alone.
const keepServerOrder: OptionsFilter = ({ options }) => options;

interface Props {
  /** Preset name or alias; null when neither the form nor the DC has one. */
  assembly: string | null;
  value: string[];
  onChange: (names: string[]) => void;
}

const optionLabel = (t: UcscTrackOption) =>
  t.label && t.label !== t.name ? `${t.label} (${t.name})` : t.name;

/** API timestamps are naive UTC (no offset on the wire). */
const readOn = (iso: string | null) =>
  iso ? new Date(`${iso}Z`).toLocaleDateString(undefined, { dateStyle: 'medium' }) : null;

const UcscTrackPicker: React.FC<Props> = ({ assembly, value, onChange }) => {
  const [search, setSearch] = useState('');
  const [debounced] = useDebouncedValue(search, SEARCH_DEBOUNCE_MS);
  const [group, setGroup] = useState<string>(ALL_GROUPS);
  const [tracks, setTracks] = useState<UcscTrackOption[]>([]);
  const [total, setTotal] = useState(0);
  const [groups, setGroups] = useState<UcscTrackGroup[]>([]);
  const [fetchedAt, setFetchedAt] = useState<string | null>(null);
  // undefined = not asked yet; null = the assembly has no UCSC genome.
  const [genome, setGenome] = useState<string | null | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Every option seen so far, so a picked track keeps its label (and its pill)
  // once a later search no longer returns it.
  const known = useRef(new Map<string, UcscTrackOption>());
  // The query the listed pages belong to; a page of an older query is dropped.
  const queryId = useRef(0);
  const ctrlRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setGenome(undefined);
    setTracks([]);
    setGroup(ALL_GROUPS);
    known.current = new Map();
  }, [assembly]);

  const load = useCallback(
    (offset: number) => {
      if (!assembly) return;
      ctrlRef.current?.abort();
      const ctrl = new AbortController();
      ctrlRef.current = ctrl;
      const id = queryId.current;
      setLoading(true);
      setError(null);
      fetchUcscTracks(
        assembly,
        {
          q: debounced.trim(),
          limit: PAGE_SIZE,
          offset,
          group: group === ALL_GROUPS ? null : group,
        },
        ctrl.signal,
      )
        .then((res) => {
          if (ctrl.signal.aborted || id !== queryId.current) return;
          setGenome(res.genome);
          setTracks((prev) => (offset === 0 ? res.tracks : [...prev, ...res.tracks]));
          setTotal(res.total);
          setGroups(res.groups);
          setFetchedAt(res.fetched_at);
          for (const t of res.tracks) known.current.set(t.name, t);
        })
        .catch((e: unknown) => {
          if (ctrl.signal.aborted) return;
          setError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => {
          if (!ctrl.signal.aborted) setLoading(false);
        });
    },
    [assembly, debounced, group],
  );

  // A new query (search, group or assembly) starts over from its first page.
  useEffect(() => {
    queryId.current += 1;
    load(0);
    return () => ctrlRef.current?.abort();
  }, [load]);

  const loadMore = useCallback(() => {
    if (!loading && tracks.length < total) load(tracks.length);
  }, [load, loading, tracks.length, total]);

  const data = useMemo(() => {
    const byHeading = new Map<string, ComboboxItem[]>();
    const listed = new Set<string>();
    const groupLabel = new Map(groups.map((g) => [g.id, g.label]));
    const add = (heading: string, item: ComboboxItem) => {
      if (listed.has(item.value)) return;
      listed.add(item.value);
      const list = byHeading.get(heading);
      if (list) list.push(item);
      else byHeading.set(heading, [item]);
    };
    // Picked tracks first (MultiSelect needs them in `data` to draw their pills).
    for (const name of value) {
      const t = known.current.get(name);
      add('Selected', { value: name, label: t ? optionLabel(t) : name });
    }
    for (const t of tracks) {
      const heading = t.collection || groupLabel.get(t.group ?? '') || t.group || 'Other';
      add(heading, { value: t.name, label: optionLabel(t) });
    }
    return [...byHeading].map(
      ([heading, items]): ComboboxItemGroup<ComboboxItem> => ({ group: heading, items }),
    );
  }, [tracks, value, groups]);

  const groupData = useMemo(() => {
    const all = groups.reduce((n, g) => n + g.count, 0);
    return [
      { value: ALL_GROUPS, label: `All groups (${all.toLocaleString()})` },
      ...groups.map((g) => ({ value: g.id, label: `${g.label} (${g.count.toLocaleString()})` })),
    ];
  }, [groups]);

  const unavailable = !assembly || genome === null;
  const read = readOn(fetchedAt);
  const description = !assembly
    ? 'Pick an assembly (or bind a collection that declares one) to browse UCSC tracks'
    : genome === null
      ? `No UCSC genome matches ${assembly}: UCSC tracks are unavailable`
      : genome
        ? [
            `${total.toLocaleString()} UCSC ${genome} track${total === 1 ? '' : 's'}`,
            tracks.length < total
              ? `${tracks.length.toLocaleString()} listed, scroll for more`
              : null,
            read ? `catalogue read ${read}` : null,
          ]
            .filter(Boolean)
            .join(' · ')
        : 'UCSC tracks shown by default next to the manifest tracks';

  return (
    <Stack gap={6}>
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
        maxDropdownHeight={320}
        scrollAreaProps={{ onBottomReached: loadMore }}
        nothingFoundMessage={loading ? 'Searching…' : 'No UCSC track matches'}
        disabled={unavailable && value.length === 0}
        error={error}
        leftSection={<Icon icon="mdi:web" width={14} />}
        rightSection={loading ? <Loader size={14} /> : undefined}
        data-testid="jbrowse-builder-ucsc-tracks"
      />
      {!unavailable && groups.length > 1 && (
        <Select
          size="xs"
          aria-label="UCSC track group"
          data={groupData}
          value={group}
          onChange={(v) => setGroup(v ?? ALL_GROUPS)}
          allowDeselect={false}
          leftSection={<Icon icon="mdi:folder-outline" width={14} />}
          data-testid="jbrowse-builder-ucsc-group"
        />
      )}
    </Stack>
  );
};

export default UcscTrackPicker;
