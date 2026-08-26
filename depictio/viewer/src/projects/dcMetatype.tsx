import React from 'react';
import { Badge, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DcClassifiable } from './dcTypeIcon';

/** The metatype axis of a data collection: what the table IS within its
 *  project, independent of the type axis (dcTypeIcon.tsx) that says what it
 *  holds. A geomap can be a metadata table or an aggregate one, so the two
 *  are never rendered as alternatives to each other.
 *
 *  Metadata blue, Aggregate orange, in the manager row, the DC viewer and the
 *  Collection Types stat card alike. */

export const METADATA_COLOR = 'blue';
export const AGGREGATE_COLOR = 'orange';

export interface MetatypeMeta {
  label: string;
  color: string;
  icon: string;
}

/** Resolve the metatype axis to one consistent descriptor. An aggregate table
 *  looks the same whether the backend stamped metatype="Aggregated" or left it
 *  null (inferred from an advanced project's table DC), so both land on the
 *  same badge. */
export function dcMetatypeMeta(
  dc: DcClassifiable,
  projectType: 'basic' | 'advanced',
): MetatypeMeta | null {
  const type = (dc.config?.type as string | undefined)?.toLowerCase();
  const metatype = (dc.config?.metatype as string | undefined) || '';
  if (metatype.toLowerCase().startsWith('metadat')) {
    return { label: 'Metadata', color: METADATA_COLOR, icon: 'mdi:tag-outline' };
  }
  if (projectType === 'advanced' && type === 'table') {
    return {
      label: 'Aggregate',
      color: AGGREGATE_COLOR,
      icon: 'mdi:layers-triple-outline',
    };
  }
  return null;
}

/** Metadata / Aggregate badge. Renders nothing when the axis doesn't apply
 *  (an image DC in a basic project has no meaningful metatype). */
export const DcMetatypeBadge: React.FC<{
  dc: DcClassifiable;
  projectType: 'basic' | 'advanced';
}> = ({ dc, projectType }) => {
  const meta = dcMetatypeMeta(dc, projectType);
  if (!meta) return null;
  return (
    <Tooltip
      label={
        meta.label === 'Metadata'
          ? 'Metadata table: describes the samples other collections aggregate'
          : 'Aggregate table: rows fanned in from the project run'
      }
      withArrow
      withinPortal
    >
      <Badge
        color={meta.color}
        variant="light"
        size="sm"
        radius="sm"
        leftSection={<Icon icon={meta.icon} width={12} />}
      >
        {meta.label}
      </Badge>
    </Tooltip>
  );
};
