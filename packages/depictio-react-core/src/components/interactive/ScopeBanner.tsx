/**
 * The scope banner: on a tab that shows one unit at a time, which unit that
 * is, under the header, whatever the reader has scrolled to.
 *
 * One row per filter that sets the scope (`scopeUnits`): the filter's icon
 * tile and title as the Filters panel draws them, the held value as the same
 * chip the tiles carry (`ScopeValueBadge`), the filter's `banner_facts` read
 * from the value's row, and a key that takes the reader to the filter. The
 * facts are left out while a data version is pinned: the row lookup reads the
 * newest commit only.
 *
 * Surfaces and shapes come from the chrome (`scopeBanner.css`, and the Paper
 * rules beside `.hy-strip`); nothing here picks a colour but the filter's own
 * accent.
 */
import { Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import React from 'react';

import type { InteractiveFilter, StoredMetadata } from '../../api';
import { ChromeButton } from '../../chrome';
import { ownFilterValues } from './alwaysSelected';
import { interactiveAccent, interactiveIcon, interactiveTitle } from './frame';
import { bannerFactColumns, bannerFactItems, scopeChipColor } from './scope';
import { ScopeValueBadge } from './ScopeValueBadge';
import { useRowValues } from './useInteractiveData';

import './scopeBanner.css';

const ScopeRow: React.FC<{
  metadata: StoredMetadata;
  value: string | undefined;
  onChange?: (index: string) => void;
}> = ({ metadata, value, onChange }) => {
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
  return (
    <div className="depictio-scope-banner__row" data-component-id={metadata.index}>
      <Group gap="xs" wrap="nowrap" style={{ minWidth: 0, flex: '0 1 auto' }}>
        <span
          className="depictio-scope-banner__badge"
          style={
            {
              '--scope-accent': interactiveAccent(metadata) ?? 'var(--mantine-primary-color-filled)',
            } as React.CSSProperties
          }
          aria-hidden
        >
          <Icon icon={interactiveIcon(metadata)} width={16} height={16} />
        </span>
        <Text size="sm" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
          {title}
        </Text>
        {value !== undefined ? (
          <ScopeValueBadge value={value} color={scopeChipColor([metadata])} size="md" title={title} />
        ) : (
          <Text size="sm" c="dimmed">
            …
          </Text>
        )}
      </Group>
      {facts.length > 0 && (
        <Group gap="md" wrap="wrap" className="depictio-scope-banner__facts">
          {facts.map((f) => (
            <Text key={f.label} size="sm" style={{ whiteSpace: 'nowrap' }}>
              <Text span c="dimmed" inherit>
                {f.label}
              </Text>{' '}
              <Text span fw={600} inherit>
                {f.text}
              </Text>
            </Text>
          ))}
        </Group>
      )}
      {onChange && (
        <ChromeButton
          role="secondary"
          icon="filters"
          label={`Change ${title}`}
          collapse
          onClick={() => onChange(metadata.index)}
          className="depictio-scope-banner__change"
          data-testid="scope-banner-change"
        >
          Change
        </ChromeButton>
      )}
    </div>
  );
};

export const ScopeBanner: React.FC<{
  /** The filters that set the scope (`scopeUnits`); nothing renders without. */
  units: readonly StoredMetadata[];
  filters: readonly InteractiveFilter[];
  /** Take the reader to the filter (open the panel, focus the control). */
  onChange?: (index: string) => void;
}> = ({ units, filters, onChange }) => {
  if (units.length === 0) return null;
  return (
    <section className="depictio-scope-banner" data-testid="scope-banner" aria-label="Scope">
      {units.map((m) => (
        <ScopeRow
          key={m.index}
          metadata={m}
          value={ownFilterValues(filters, m.index)[0]}
          onChange={onChange}
        />
      ))}
    </section>
  );
};

export default ScopeBanner;
