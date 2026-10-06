/**
 * A filter bar: a grid section's interactive components as one compact card.
 *
 * Each filter is a label — optionally led by its icon in a small coloured
 * badge — and a compact control: chips for a categorical column, a thin slider
 * for a numeric one, a switch, a date range. Thin rules separate them. The bar
 * is one row where the filters fit, wraps where they don't, and stacks one
 * filter per row on a phone (see filterStrip.css).
 */
import React from 'react';
import { Group, Paper, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { FilterSectionSpec, InteractiveFilter, StoredMetadata } from '../../../api';
import { isFilterActive } from '../../../activeFilters';
import SectionIcon from '../../SectionIcon';
import { interactiveAccent, interactiveIcon, interactiveTitle } from '../frame';
import {
  StripCategorical,
  StripDate,
  StripRange,
  StripSlider,
  StripToggle,
} from './StripControls';
import { stripControlKind, stripLabel, stripShowsIcon } from './stripLayout';
import './filterStrip.css';

/** The brand's primary, as the dashboard's `BrandScope` resolved it. */
const BRAND_ACCENT = 'var(--mantine-primary-color-filled)';

export interface FilterStripProps {
  members: StoredMetadata[];
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Accessible name of the bar — its section's name. */
  label?: string;
  /** Editor only: per-filter actions (the ⋮ menu), drawn after each label. */
  renderItemActions?: (metadata: StoredMetadata) => React.ReactNode;
}

const FilterStripItem: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  actions?: React.ReactNode;
}> = ({ metadata, filters, onFilterChange, actions }) => {
  const kind = stripControlKind(metadata.interactive_component_type);
  const title = interactiveTitle(metadata);
  const label = stripLabel(metadata, title);
  const accent = interactiveAccent(metadata) ?? BRAND_ACCENT;
  const entry = filters.find((f) => f.index === metadata.index);
  const active = entry ? isFilterActive(entry) : false;
  const props = { metadata, filters, onFilterChange, label };

  let control: React.ReactNode;
  switch (kind) {
    case 'categorical':
      control = <StripCategorical {...props} />;
      break;
    case 'range':
      control = <StripRange {...props} accent={accent} />;
      break;
    case 'slider':
      control = <StripSlider {...props} accent={accent} />;
      break;
    case 'toggle':
      control = <StripToggle {...props} accent={accent} />;
      break;
    case 'date':
      control = <StripDate {...props} />;
      break;
    default:
      control = (
        <Text size="xs" c="dimmed">
          {metadata.interactive_component_type} has no filter-bar form; it works in the
          filter panel.
        </Text>
      );
  }

  return (
    <div
      className="depictio-filter-strip__item"
      data-kind={kind}
      data-active={active}
      data-component-id={metadata.index}
      style={{ '--strip-accent': accent } as React.CSSProperties}
    >
      <div className="depictio-filter-strip__label">
        {stripShowsIcon(metadata) && (
          <span className="depictio-filter-strip__badge" aria-hidden>
            <Icon icon={interactiveIcon(metadata)} width={18} height={18} />
          </span>
        )}
        {/* The short label stands in for the title; the title stays one hover
            away, since it is often the more precise of the two. */}
        <Tooltip label={title} disabled={label === title} withArrow openDelay={400}>
          <span className="depictio-filter-strip__name">{label}</span>
        </Tooltip>
        {actions}
      </div>
      <div className="depictio-filter-strip__control">{control}</div>
    </div>
  );
};

export const FilterStrip: React.FC<FilterStripProps> = ({
  members,
  filters,
  onFilterChange,
  label,
  renderItemActions,
}) => (
  // A plain element rather than a Mantine Paper: the viewer strips every
  // Paper's border and shadow inside the dashboard grid (tiles draw their own
  // frame), and the bar must keep its card look there. See filterStrip.css.
  <div className="depictio-filter-strip" role="group" aria-label={label}>
    <div className="depictio-filter-strip__clip">
      <div className="depictio-filter-strip__row">
        {members.map((m) => (
          <FilterStripItem
            key={m.index}
            metadata={m}
            filters={filters}
            onFilterChange={onFilterChange}
            actions={renderItemActions?.(m)}
          />
        ))}
      </div>
    </div>
  </div>
);

export interface FilterStripSectionProps extends Omit<FilterStripProps, 'label'> {
  spec?: FilterSectionSpec | null;
  name: string;
  /** Editor: draws the section's name and its actions above the bar, so the
   *  section can be found and edited; readers only ever see the bar. */
  editMode?: boolean;
  /** The section's own actions (the editor's "…"). */
  actions?: React.ReactNode;
  /** The section's non-interactive members, already rendered as a grid. */
  rest?: React.ReactNode;
}

/**
 * A grid section drawn as a filter bar, with whatever else it holds below.
 * No header and no fold for readers: the bar is the section.
 */
export const FilterStripSection: React.FC<FilterStripSectionProps> = ({
  spec,
  name,
  editMode,
  actions,
  rest,
  members,
  ...stripProps
}) => (
  <div className="depictio-strip-section" data-strip-section={name}>
    {editMode && (
      <div className="depictio-strip-section__edit-head">
        <Group gap={6} wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
          <SectionIcon spec={spec ?? undefined} size={14} fallbackIcon="mdi:tune-variant" />
          <Text size="sm" fw={600} truncate>
            {name}
          </Text>
          <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
            Filter bar
          </Text>
        </Group>
        {actions}
      </div>
    )}
    {members.length > 0 ? (
      <FilterStrip members={members} label={name} {...stripProps} />
    ) : editMode ? (
      <Paper withBorder radius="lg" p="md" bg="var(--mantine-color-default-hover)">
        <Group gap="xs" justify="center" wrap="nowrap">
          <Icon icon="mdi:tune-variant" width={16} color="var(--mantine-color-dimmed)" />
          <Text size="sm" c="dimmed">
            No filters yet — move one here from its ⋮ menu, or pick this section in a
            filter&apos;s Placement.
          </Text>
        </Group>
      </Paper>
    ) : null}
    {rest ? <div className="depictio-strip-section__rest">{rest}</div> : null}
  </div>
);

export default FilterStrip;
