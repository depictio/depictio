import React, { useCallback } from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';

type ExportKind = 'csv' | 'png' | 'none';

interface DownloadButtonProps {
  componentType: string;
  metadata: StoredMetadata;
  /** Tables: AG Grid api ref with at least exportDataAsCsv. */
  agGridApiRef?: React.RefObject<{ exportDataAsCsv: () => void } | null>;
  /** The chrome wrapper — Plotly is queried inside via `.js-plotly-plot`. */
  fullscreenRef?: React.RefObject<HTMLDivElement | null>;
}

function exportKindFor(componentType: string): ExportKind {
  if (componentType === 'table') return 'csv';
  if (componentType === 'figure' || componentType === 'map' || componentType === 'multiqc') {
    return 'png';
  }
  return 'none';
}

/**
 * Per-type download. Tables export CSV via AG Grid (mirroring
 * `depictio/dash/modules/table_component/callbacks/core.py`). Figures, maps
 * and MultiQC export PNGs via `window.Plotly.downloadImage` — Plotly is
 * located by querying for `.js-plotly-plot` inside the chrome wrapper, so
 * the individual renderers don't have to expose their internal refs.
 */
const DownloadButton: React.FC<DownloadButtonProps> = ({
  componentType,
  metadata,
  agGridApiRef,
  fullscreenRef,
}) => {
  const kind = exportKindFor(componentType);

  const onClick = useCallback(() => {
    if (kind === 'csv') {
      agGridApiRef?.current?.exportDataAsCsv();
      return;
    }
    if (kind === 'png') {
      const wrapper = fullscreenRef?.current;
      const div = wrapper?.querySelector<HTMLDivElement>('.js-plotly-plot') ?? null;
      const Plotly = (window as unknown as {
        Plotly?: {
          downloadImage: (
            gd: HTMLDivElement,
            opts: { format: string; filename: string },
          ) => void;
        };
      }).Plotly;
      if (!div || !Plotly?.downloadImage) {
        // eslint-disable-next-line no-console
        console.warn('[DownloadButton] Plotly not available or div not found yet');
        return;
      }
      const filename = (metadata.title as string | undefined) || metadata.index || 'figure';
      Plotly.downloadImage(div, { format: 'png', filename });
    }
  }, [kind, agGridApiRef, fullscreenRef, metadata]);

  const label =
    kind === 'csv' ? 'Download CSV' : kind === 'png' ? 'Download PNG' : 'Download';

  return (
    <Tooltip label={label} withArrow>
      <ActionIcon
        variant="light"
        color="green"
        size="sm"
        onClick={onClick}
        aria-label={label}
      >
        <Icon icon="mdi:download" width={16} height={16} />
      </ActionIcon>
    </Tooltip>
  );
};

export default DownloadButton;
