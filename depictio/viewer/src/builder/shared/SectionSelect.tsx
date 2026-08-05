/**
 * The section a component joins, offered by every builder.
 *
 * Mounted once in `StepDesign` rather than per builder: `section` lives on the
 * base component model, so it means the same thing for a card as for a filter,
 * and duplicating the control into nine builders would guarantee they drift.
 *
 * Which list is offered depends on the component's type, exactly as the two
 * render paths are fed: interactive components join the filter panel's sections,
 * everything else joins the grid's.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Group, Select, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchDashboard, SectionIcon } from 'depictio-react-core';
import type { DashboardData, FilterSectionSpec } from 'depictio-react-core';

import { useBuilderStore } from '../store/useBuilderStore';
import { implicitNames, sectionsFor } from '../../components/sections/sectionMutations';
import type { SectionKind } from '../../components/sections/sectionMutations';

const SectionSelect: React.FC = () => {
  const componentType = useBuilderStore((s) => s.componentType);
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const config = useBuilderStore((s) => s.config) as {
    section?: string;
    group?: string;
    placement?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  useEffect(() => {
    if (!dashboardId) return;
    let cancelled = false;
    fetchDashboard(dashboardId)
      .then((dash) => {
        if (!cancelled) setDashboard(dash);
      })
      .catch((err) => {
        // Degrades to "no sections offered" rather than blocking authoring.
        console.warn('[SectionSelect] section list unavailable:', err);
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId]);

  const kind: SectionKind = componentType === 'interactive' ? 'filter' : 'grid';

  const specs = useMemo<FilterSectionSpec[]>(() => {
    if (!dashboard) return [];
    // Include sections that only exist because a component names them: the
    // manager materialises those, but a dashboard authored purely in YAML may
    // not have been through it yet.
    return [
      ...sectionsFor(dashboard, kind),
      ...implicitNames(dashboard, kind).map((name) => ({ name })),
    ];
  }, [dashboard, kind]);

  const current = config.section ?? '';
  // A section the dashboard no longer declares must still show, or saving an
  // unrelated field would silently drop it.
  const options = useMemo(() => {
    const names = specs.map((s) => s.name);
    if (current && !names.includes(current)) names.unshift(current);
    return names.map((name) => ({ value: name, label: name }));
  }, [specs, current]);

  const specByName = useMemo(
    () => new Map(specs.map((s) => [s.name, s])),
    [specs],
  );

  // `placement: 'top'` controls render in the footer strip, which has no
  // sections at all.
  const disabled = componentType === 'interactive' && config.placement === 'top';

  return (
    <Select
      label="Section"
      description={
        disabled
          ? 'Footer controls are not grouped into sections.'
          : kind === 'filter'
            ? config.group
              ? 'Groups this filter under a collapsible header. Changing it clears the group, which cannot span two sections.'
              : 'Groups this filter under a collapsible header in the filter panel.'
            : 'Groups this component under a collapsible header in the dashboard.'
      }
      placeholder={options.length === 0 ? 'No sections yet' : 'No section'}
      data={options}
      value={current || null}
      onChange={(v) => {
        const next = v ?? '';
        // A group may not span two sections (validate_interactive_groups in
        // depictio/models/models/dashboards.py). That rule is only enforced on
        // the YAML model, not on the document the save endpoint validates, so
        // moving one member of a group would save happily and only blow up
        // later on export. Clearing the group here is what keeps that
        // impossible — and it matches the group picker, which only ever offers
        // the chosen section's groups anyway.
        patchConfig(
          kind === 'filter' && config.group && next !== current
            ? { section: next, group: '' }
            : { section: next },
        );
      }}
      clearable
      searchable
      disabled={disabled || options.length === 0}
      comboboxProps={{ withinPortal: false }}
      leftSection={<Icon icon="mdi:format-list-group" width={14} />}
      renderOption={({ option }) => (
        <Group gap="xs" wrap="nowrap">
          <SectionIcon
            spec={specByName.get(option.value)}
            size={12}
            fallbackIcon="mdi:shape-outline"
          />
          <Text size="sm">{option.label}</Text>
        </Group>
      )}
    />
  );
};

export default SectionSelect;
