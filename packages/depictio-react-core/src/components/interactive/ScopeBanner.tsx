/**
 * The scope banner: on a tab that shows one unit at a time, the identity card
 * of that unit, under the header, whatever the reader has scrolled to.
 *
 * One card per filter that sets the scope (`scopeUnits`):
 * - the filter's icon tile in its accent, as the Filters panel draws it;
 * - the filter's title as an eyebrow over the unit's name, which is the
 *   picker itself (a searchable list in the panel's order), so the card reads
 *   as a heading rather than a form field;
 * - the filter's `banner_facts`, read from the unit's row, as figures;
 * - previous and next keys with the unit's rank ("3 / 12"), walking the same
 *   list as the automatic pick (`useScopeOptions`).
 *
 * The facts are left out while a data version is pinned: the row lookup reads
 * the newest commit only. Surfaces and shapes come from the chrome
 * (`scopeBanner.css`, and the Paper rules beside `.hy-strip`); nothing here
 * picks a colour but the filter's own accent.
 */
import {
  ActionIcon,
  Combobox,
  getRadius,
  Group,
  Text,
  Tooltip,
  UnstyledButton,
  useCombobox,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import React from 'react';

import type { InteractiveFilter, StoredMetadata } from '../../api';
import { useChromeStyle } from '../../chrome';
import { ownFilterValues } from './alwaysSelected';
import { filterEvent } from './categoricalOptions';
import { interactiveAccent, interactiveIcon, interactiveTitle } from './frame';
import { bannerFactColumns, bannerFactItems, unitSteps } from './scope';
import { useRowValues } from './useInteractiveData';
import { useScopeOptions, type ScopeOption } from './useScopeOptions';

import './scopeBanner.css';

/** Options drawn in the list at once; the search narrows the rest. */
const MAX_LISTED = 200;

/** The unit's name as a heading that opens a searchable list of the others. */
const UnitPicker: React.FC<{
  title: string;
  value: string | undefined;
  options: readonly ScopeOption[];
  onPick?: (value: string) => void;
}> = ({ title, value, options, onPick }) => {
  const style = useChromeStyle();
  const [search, setSearch] = React.useState('');
  const combobox = useCombobox({
    onDropdownOpen: () => combobox.focusSearchInput(),
    onDropdownClose: () => {
      combobox.resetSelectedOption();
      setSearch('');
    },
  });
  const listed = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    const hits = q ? options.filter((o) => o.value.toLowerCase().includes(q)) : options;
    return hits.slice(0, MAX_LISTED);
  }, [options, search]);

  const name = (
    <Text
      component="span"
      className="depictio-scope-banner__name"
      fw={700}
      data-testid="scope-banner-value"
    >
      {value ?? '…'}
    </Text>
  );
  if (!onPick) return name;

  return (
    <Combobox
      store={combobox}
      position="bottom-start"
      width="target"
      withinPortal
      onOptionSubmit={(v) => {
        combobox.closeDropdown();
        if (v !== value) onPick(v);
      }}
    >
      <Combobox.Target>
        <UnstyledButton
          className="depictio-scope-banner__picker"
          style={{ '--scope-radius': getRadius(style.radius) } as React.CSSProperties}
          onClick={() => combobox.toggleDropdown()}
          aria-label={`Change ${title}`}
          aria-haspopup="listbox"
          aria-expanded={combobox.dropdownOpened}
          data-testid="scope-banner-picker"
        >
          {name}
          <Icon icon="tabler:selector" width={18} height={18} aria-hidden />
        </UnstyledButton>
      </Combobox.Target>
      {/* As wide as the name it opens from, never narrower than a readable list. */}
      <Combobox.Dropdown miw={320} maw="min(640px, calc(100vw - 32px))">
        <Combobox.Search
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          placeholder={`Search ${title.toLowerCase()}`}
        />
        <Combobox.Options mah={320} style={{ overflowY: 'auto' }}>
          {listed.length === 0 ? (
            <Combobox.Empty>Nothing found</Combobox.Empty>
          ) : (
            listed.map((o) => (
              <Combobox.Option
                key={o.value}
                value={o.value}
                disabled={o.disabled}
                active={o.value === value}
              >
                <Text
                  size="sm"
                  fw={o.value === value ? 600 : undefined}
                  className="depictio-scope-banner__option"
                >
                  {o.value}
                </Text>
              </Combobox.Option>
            ))
          )}
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
};

const ScopeCard: React.FC<{
  metadata: StoredMetadata;
  value: string | undefined;
  onFilterChange?: (filter: InteractiveFilter) => void;
}> = ({ metadata, value, onFilterChange }) => {
  const style = useChromeStyle();
  const title = interactiveTitle(metadata);
  const columns = React.useMemo(() => bannerFactColumns(metadata.banner_facts), [metadata.banner_facts]);
  const { data: row } = useRowValues(
    metadata.dc_id,
    metadata.column_name,
    value,
    columns,
    metadata.filter_expr,
  );
  const facts = bannerFactItems(metadata.banner_facts, row);
  const { options } = useScopeOptions(metadata);
  const steps = unitSteps(options, value);
  const pick = onFilterChange
    ? (v: string) => onFilterChange(filterEvent(metadata, [v]))
    : undefined;

  const stepKey = (dir: 'prev' | 'next') => {
    const target = steps[dir];
    const label = dir === 'prev' ? `Previous ${title.toLowerCase()}` : `Next ${title.toLowerCase()}`;
    return (
      <Tooltip label={target ? `${label}: ${target}` : label} withinPortal openDelay={300}>
        <ActionIcon
          variant="default"
          radius={style.radius}
          size={style.controlSize === 'xs' ? 'md' : 'lg'}
          disabled={!target}
          onClick={() => target && pick?.(target)}
          aria-label={label}
          data-testid={`scope-banner-${dir}`}
        >
          <Icon
            icon={dir === 'prev' ? 'tabler:chevron-left' : 'tabler:chevron-right'}
            width={18}
            height={18}
          />
        </ActionIcon>
      </Tooltip>
    );
  };

  return (
    <div className="depictio-scope-banner__card" data-component-id={metadata.index}>
      <span
        className="depictio-scope-banner__badge"
        style={
          {
            '--scope-accent': interactiveAccent(metadata) ?? 'var(--mantine-primary-color-filled)',
          } as React.CSSProperties
        }
        aria-hidden
      >
        <Icon icon={interactiveIcon(metadata)} width={22} height={22} />
      </span>
      <div className="depictio-scope-banner__identity">
        <Text className="depictio-scope-banner__eyebrow" c="dimmed" fw={600}>
          {title}
        </Text>
        <UnitPicker title={title} value={value} options={options} onPick={pick} />
      </div>
      {facts.length > 0 && (
        <dl className="depictio-scope-banner__facts">
          {facts.map((f) => (
            <div key={f.label} className="depictio-scope-banner__fact">
              <dd>
                <Text component="span" fw={700} className="depictio-scope-banner__figure">
                  {f.text}
                </Text>
              </dd>
              <dt>
                <Text component="span" size="xs" c="dimmed">
                  {f.label}
                </Text>
              </dt>
            </div>
          ))}
        </dl>
      )}
      {pick && steps.total > 1 && (
        <Group gap={6} wrap="nowrap" className="depictio-scope-banner__steps">
          {stepKey('prev')}
          <Text size="sm" c="dimmed" className="depictio-scope-banner__rank" aria-live="polite">
            {steps.position > 0 ? `${steps.position} / ${steps.total}` : `${steps.total}`}
          </Text>
          {stepKey('next')}
        </Group>
      )}
    </div>
  );
};

export const ScopeBanner: React.FC<{
  /** The filters that set the scope (`scopeUnits`); nothing renders without. */
  units: readonly StoredMetadata[];
  filters: readonly InteractiveFilter[];
  /** Set the unit; without it the card is read-only. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}> = ({ units, filters, onFilterChange }) => {
  if (units.length === 0) return null;
  return (
    <section className="depictio-scope-banner" data-testid="scope-banner" aria-label="Scope">
      {units.map((m) => (
        <ScopeCard
          key={m.index}
          metadata={m}
          value={ownFilterValues(filters, m.index)[0]}
          onFilterChange={onFilterChange}
        />
      ))}
    </section>
  );
};

export default ScopeBanner;
