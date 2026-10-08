/**
 * A filter bar: interactive components drawn as one compact row of controls.
 *
 * Each filter is a badge (its icon in a small coloured square), a label and a
 * compact control: chips for a categorical column, a thin slider for a numeric
 * one, a switch, a date range. The filters sit in equal columns with a thin rule
 * between them, so every row of a bar lines up with the one above: the rules,
 * the labels (left-aligned, in a column as wide as the bar's widest label) and
 * the controls. See filterStrip.css.
 *
 * Two looks for the two places a bar lives:
 * - `card`: a grid section drawn as a bar (`display: 'strip'`), standing on its
 *   own with a card's frame;
 * - `section`: a section's own bar (`filter_bar`), under its heading, quieter.
 *
 * A bar can show only its first filters (`visibleCount`) and fold the rest
 * behind "More filters", which unfolds them in place, in the same columns.
 */
import React, { useId, useMemo, useState } from 'react';
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
import { stripControlKind, stripLabel, stripShowsIcon, visibleFilterCount } from './stripLayout';
import './filterStrip.css';

/** The brand's primary, as the dashboard's `BrandScope` resolved it. */
const BRAND_ACCENT = 'var(--mantine-primary-color-filled)';

export type FilterStripVariant = 'card' | 'section';

export interface FilterStripProps {
  members: StoredMetadata[];
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Accessible name of the bar — its section's name. */
  label?: string;
  /** Editor only: per-filter actions (the ⋮ menu), drawn after each label. */
  renderItemActions?: (metadata: StoredMetadata) => React.ReactNode;
  /** How many filters show before "More filters"; the rest unfold in place.
   *  Unset shows them all. */
  visibleCount?: number;
  /** `card` (default): a bar on its own. `section`: a section's own bar. */
  variant?: FilterStripVariant;
  /** Clears the bar's filters; offered while one of them is active. */
  onReset?: () => void;
}

/** Whether the bar's control for `m` is narrowing anything. Selections made on
 *  a chart carry a `source`; the bar's own value never does. */
const isMemberActive = (filters: InteractiveFilter[], m: StoredMetadata) =>
  filters.some((f) => f.index === m.index && f.source === undefined && isFilterActive(f));

const FilterStripItem: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  actions?: React.ReactNode;
  /** Every label of the bar: sized against, so all label columns match. */
  labels: string[];
  /** Whether the bar has a badge column (some filter shows its icon). */
  badgeColumn: boolean;
}> = ({ metadata, filters, onFilterChange, actions, labels, badgeColumn }) => {
  const kind = stripControlKind(metadata.interactive_component_type);
  const title = interactiveTitle(metadata);
  const label = stripLabel(metadata, title);
  const accent = interactiveAccent(metadata) ?? BRAND_ACCENT;
  const active = isMemberActive(filters, metadata);
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
      {/* One badge column for the whole bar: a filter whose icon is off keeps
          the empty slot, so its label still starts where the others do. */}
      {badgeColumn && (
        <span
          className="depictio-filter-strip__badge"
          data-empty={!stripShowsIcon(metadata) || undefined}
          aria-hidden
        >
          {stripShowsIcon(metadata) && (
            <Icon icon={interactiveIcon(metadata)} width={18} height={18} />
          )}
        </span>
      )}
      <div className="depictio-filter-strip__label">
        <span className="depictio-filter-strip__name-box">
          {/* The short label stands in for the title; the title stays one hover
              away, since it is often the more precise of the two. */}
          <Tooltip label={title} disabled={label === title} withArrow openDelay={400}>
            <span className="depictio-filter-strip__name">{label}</span>
          </Tooltip>
          {/* Every label of the bar, invisible and stacked in the same cell:
              the cell is as wide as the widest of them, so each filter's label
              column has that width and the controls all start on one line. */}
          <span className="depictio-filter-strip__sizer" aria-hidden>
            {labels.map((l, i) => (
              <span key={i}>{l}</span>
            ))}
          </span>
        </span>
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
  visibleCount,
  variant = 'card',
  onReset,
}) => {
  const gridId = useId();
  const [expanded, setExpanded] = useState(false);
  const shownCount =
    visibleCount === undefined ? members.length : Math.max(0, Math.min(members.length, visibleCount));
  const folded = members.slice(shownCount);
  const shown = expanded ? members : members.slice(0, shownCount);
  // Sized on every member, folded ones included, so unfolding them does not
  // move the labels already on screen.
  const labels = useMemo(() => members.map((m) => stripLabel(m, interactiveTitle(m))), [members]);
  const badgeColumn = members.some(stripShowsIcon);
  const activeCount = members.filter((m) => isMemberActive(filters, m)).length;
  const foldedActive = folded.filter((m) => isMemberActive(filters, m)).length;
  const canReset = Boolean(onReset) && activeCount > 0;

  return (
    // A plain element rather than a Mantine Paper: the viewer strips every
    // Paper's border and shadow inside the dashboard grid (tiles draw their own
    // frame), and the bar must keep its look there. See filterStrip.css.
    <div
      className="depictio-filter-strip"
      data-variant={variant}
      data-badges={badgeColumn}
      role="group"
      aria-label={label}
    >
      <div className="depictio-filter-strip__clip">
        <div className="depictio-filter-strip__grid" id={gridId}>
          {shown.map((m) => (
            <FilterStripItem
              key={m.index}
              metadata={m}
              filters={filters}
              onFilterChange={onFilterChange}
              actions={renderItemActions?.(m)}
              labels={labels}
              badgeColumn={badgeColumn}
            />
          ))}
        </div>
      </div>
      {/* The aside keeps one width whatever its state, so toggling the fold
          or setting a first filter never changes how many columns the grid
          gets: the labels swap in a cell sized for both, the count stays
          laid out when hidden, and Reset is only made invisible. */}
      {(folded.length > 0 || onReset) && (
        <div className="depictio-filter-strip__aside">
          {folded.length > 0 && (
            <Tooltip
              label={`${expanded ? 'Fold' : 'Show'} ${folded
                .map((m) => stripLabel(m, interactiveTitle(m)))
                .join(', ')}${
                !expanded && foldedActive > 0 ? `: ${foldedActive} of them set` : ''
              }`}
              withArrow
              multiline
              maw={260}
              openDelay={300}
            >
              <button
                type="button"
                className="depictio-filter-strip__more"
                aria-expanded={expanded}
                aria-controls={gridId}
                aria-label={
                  expanded
                    ? 'Fewer filters'
                    : `More filters: ${folded.length} hidden${
                        foldedActive > 0 ? `, ${foldedActive} active` : ''
                      }`
                }
                onClick={() => setExpanded((v) => !v)}
              >
                <Icon
                  icon={expanded ? 'mdi:chevron-up' : 'mdi:tune-variant'}
                  width={16}
                  height={16}
                />
                <span className="depictio-filter-strip__more-label">
                  <span data-shown={!expanded}>More filters</span>
                  <span data-shown={expanded}>Fewer filters</span>
                </span>
                <span className="depictio-filter-strip__count" data-hidden={expanded || undefined}>
                  {folded.length}
                </span>
                {/* Folded filters still filter: say how many, or a reader
                    would wonder why the figures disagree with the chips. */}
                {!expanded && foldedActive > 0 && (
                  <span className="depictio-filter-strip__active-count">{foldedActive}</span>
                )}
              </button>
            </Tooltip>
          )}
          {onReset && (
            <button
              type="button"
              className="depictio-filter-strip__reset"
              data-hidden={!canReset || undefined}
              onClick={onReset}
            >
              <Icon icon="mdi:filter-remove-outline" width={15} height={15} />
              <span>Reset</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export interface FilterStripSectionProps
  extends Omit<FilterStripProps, 'label' | 'visibleCount' | 'variant'> {
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
 * A grid section drawn as a filter bar (`display: 'strip'`), with whatever
 * else it holds below. No header and no fold for readers: the bar is the
 * section.
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
            Filter bar · filters the whole tab
          </Text>
        </Group>
        {actions}
      </div>
    )}
    {members.length > 0 ? (
      <FilterStrip
        members={members}
        label={name}
        visibleCount={visibleFilterCount(spec, members.length)}
        variant="card"
        {...stripProps}
      />
    ) : editMode ? (
      <EmptyBar sectionName={name} />
    ) : null}
    {rest ? <div className="depictio-strip-section__rest">{rest}</div> : null}
  </div>
);

/** Editor only: a bar with no filter yet, saying how to give it one. */
export const EmptyBar: React.FC<{ sectionName: string; variant?: FilterStripVariant }> = ({
  sectionName,
  variant = 'card',
}) => (
  <Paper
    withBorder
    radius="md"
    p="sm"
    bg="var(--mantine-color-default-hover)"
    className="depictio-filter-strip__empty"
    data-variant={variant}
  >
    <Group gap="xs" justify="center" wrap="nowrap">
      <Icon icon="mdi:tune-variant" width={16} color="var(--mantine-color-dimmed)" />
      <Text size="sm" c="dimmed">
        No filters in this bar yet. Move one here from its ⋮ menu, or pick “{sectionName}” as
        its section in the filter&apos;s Placement.
      </Text>
    </Group>
  </Paper>
);

export interface SectionFilterBarProps
  extends Omit<FilterStripProps, 'label' | 'visibleCount' | 'variant'> {
  spec?: FilterSectionSpec | null;
  name: string;
  editMode?: boolean;
}

/**
 * A section's own filter bar (`filter_bar`), drawn under its heading. Its
 * filters narrow this section only; the caller scopes them (`filterScope.ts`).
 */
export const SectionFilterBar: React.FC<SectionFilterBarProps> = ({
  spec,
  name,
  editMode,
  members,
  ...stripProps
}) =>
  members.length > 0 ? (
    <div className="depictio-section-filter-bar" data-section-bar={name}>
      <FilterStrip
        members={members}
        label={`Filters for ${name}`}
        visibleCount={visibleFilterCount(spec, members.length)}
        variant="section"
        {...stripProps}
      />
    </div>
  ) : editMode ? (
    <div className="depictio-section-filter-bar">
      <EmptyBar sectionName={name} variant="section" />
    </div>
  ) : null;

export default FilterStrip;
