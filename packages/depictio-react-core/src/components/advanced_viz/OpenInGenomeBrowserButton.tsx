import React, { useCallback, useState } from 'react';
import { ActionIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { InteractiveFilter } from '../../api';
import { regionFromFilters } from '../../selection';
import { useGenomeBrowserTarget } from '../jbrowse/browserTarget';
import {
  genomeSelectionRegion,
  locusForAction,
  type OpenLocusReader,
} from '../jbrowse/locusForAction';
import {
  OPEN_IN_BROWSER_ACTION,
  openActionState,
  openInGenomeBrowser,
} from '../jbrowse/openAction';
import { genomicRoles } from './genomicAxis';

interface Props {
  /** Reads where the tile is looking; absent on a tile that is not genomic. */
  reader: OpenLocusReader | undefined;
  vizKind: string;
  config: unknown;
  index: string;
  filters: InteractiveFilter[];
}

/**
 * The locus of the tile: its last clicked point, else the genome region in
 * force (read through the tile's own columns first, then from the filters
 * alone), else its visible window.
 */
export function resolveActionLocus(
  reader: OpenLocusReader | undefined,
  vizKind: string,
  config: unknown,
  filters: InteractiveFilter[],
): string | null {
  if (!reader) return null;
  const source = reader() ?? {};
  const roles = genomicRoles(vizKind, config);
  const region = (roles ? regionFromFilters(filters, roles) : null) ?? genomeSelectionRegion(filters);
  return locusForAction({ point: source.point, region, window: source.window });
}

/**
 * "Open in genome browser", in the tile's hover row. Hidden when the family has
 * no browser or the tile is not genomic. The locus is read when the pointer
 * reaches the button and again on click, since a click on a point changes no
 * render of its own.
 */
const OpenInGenomeBrowserButton: React.FC<Props> = ({ reader, vizKind, config, index, filters }) => {
  const target = useGenomeBrowserTarget();
  const [, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const locus = resolveActionLocus(reader, vizKind, config, filters);
  const state = openActionState({ target, reader: Boolean(reader), selfIndex: index, locus });
  if (state === 'hidden' || !target) return null;
  const label =
    state === 'disabled'
      ? `${OPEN_IN_BROWSER_ACTION.label} (click a point or select a region first)`
      : OPEN_IN_BROWSER_ACTION.label;
  return (
    // A disabled button gets no pointer events: the wrapper is what notices
    // the pointer and re-reads the tile.
    <span onPointerEnter={refresh} onFocus={refresh} style={{ display: 'inline-flex' }}>
      <ActionIcon
        variant="subtle"
        size="sm"
        aria-label={OPEN_IN_BROWSER_ACTION.label}
        title={label}
        data-tile-action="open-genome-browser"
        disabled={state === 'disabled'}
        onClick={() => {
          const now = resolveActionLocus(reader, vizKind, config, filters);
          if (now) openInGenomeBrowser(target, now);
        }}
      >
        <Icon icon={OPEN_IN_BROWSER_ACTION.icon} width={16} height={16} />
      </ActionIcon>
    </span>
  );
};

export default OpenInGenomeBrowserButton;
