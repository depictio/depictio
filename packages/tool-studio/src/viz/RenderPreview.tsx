/**
 * Preview one catalog render with depictio's own `ComponentRenderer` — the same
 * component the dashboard grid mounts, reading the same `StoredMetadata`, and
 * getting its data from the offline api shim instead of FastAPI.
 *
 * This replaces the Studio's parallel preview dispatch, which drew its own
 * Plotly figures, its own Mantine table and a static placeholder where an
 * interactive control should be — so a render looked one way here and another
 * way in depictio. Whatever this shows is what depictio shows, modulo the
 * limits the shim states out loud (see `src/api/studioApi.ts`).
 */
import { useEffect, useMemo, useState } from 'react';
import { Alert, Box, Center, Group, Loader, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  ComponentRenderer,
  bulkComputeCards,
  defaultLayoutForType,
  gridBoxHeight,
} from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';
import { registerComponent, unregisterComponent } from '../api/fixtureRegistry';
import type { ParsedFixture, RenderSpec } from '../types';
import { STUDIO_DASHBOARD_ID, metadataFromRender } from './renderMetadata';
import { usePreviewFilters } from './previewFilters';
import { requestExactFigures, useExactFigures } from './exactFigures';

/** How depictio frames a component that is NOT sitting in a dashboard grid.
 *
 *  Two of the types are never full-width anywhere: a card is 2 of the grid's 8
 *  columns, and an interactive control lives in the filter panel, which is
 *  300px by default and stacks its members at their own height (`ROW_HEIGHT`
 *  there is 40, not the grid's 100). depictio's own builder previews settle
 *  both — `builder/card/CardPreview.tsx` centres a card in 280px,
 *  `builder/interactive/InteractiveBuilder.tsx` an interactive in 320px, each
 *  at natural height — so those are the numbers used here, and the Studio's
 *  design surface and render list end up framing a component identically
 *  because both are now depictio's framing.
 *
 *  Everything else does fill its row on a dashboard (a figure is 4 columns of
 *  8, a table all 8), so it gets the panel's width and the grid box's height. */
const NARROW_PREVIEW_WIDTH: Record<string, number> = {
  card: 280,
  interactive: 320,
};

interface Props {
  fixture: ParsedFixture;
  render: RenderSpec;
  /** The render's catalog index (`<output-id>-<n>`), which is also the key the
   *  shim's component-addressed endpoints look it up by. */
  index: string;
  /** Position in the output, used only to vary the card accent colour. */
  position?: number;
}

export default function RenderPreview({ fixture, render, index, position = 0 }: Props) {
  const metadata = useMemo(
    () => metadataFromRender(render, index, fixture, position),
    [render, index, fixture, position],
  );

  // The shim's component-addressed endpoints (renderFigure / renderTable) read
  // the registry, so a component has to be in it before it renders.
  const [registered, setRegistered] = useState(false);
  useEffect(() => {
    registerComponent(metadata);
    setRegistered(true);
    return () => unregisterComponent(metadata.index);
  }, [metadata]);

  // Cards are the one type whose value the parent owns rather than the
  // renderer fetching it — same contract as the dashboard's bulk compute.
  // Controls in the list filter every other preview, as on a dashboard; the
  // shim applies them through depictio-static-core like the exported bundle.
  const filters = usePreviewFilters((s) => s.filters);
  const upsertFilter = usePreviewFilters((s) => s.upsert);

  // A UI-mode figure is drawn by depictio's own figure code once the Pyodide
  // engine is loaded; showing one is what starts that load (in the
  // background — the approximation answers meanwhile). `epoch` moves when the
  // engine is ready, and as the renderer's refreshTick it refetches the figure.
  const exactCandidate = metadata.component_type === 'figure' && metadata.mode !== 'code';
  useEffect(() => {
    if (exactCandidate && fixture.rows.length) requestExactFigures();
  }, [exactCandidate, fixture.rows.length]);
  const exactEpoch = useExactFigures((s) => s.epoch);

  const [card, setCard] = useState<{
    value?: unknown;
    secondary?: Record<string, unknown>;
  } | null>(null);
  useEffect(() => {
    if (metadata.component_type !== 'card' || !registered) return;
    let cancelled = false;
    bulkComputeCards(STUDIO_DASHBOARD_ID, filters, [metadata.index])
      .then((res) => {
        if (cancelled) return;
        setCard({
          value: res.values?.[metadata.index],
          secondary: res.secondary_values?.[metadata.index],
        });
      })
      .catch(() => {
        if (!cancelled) setCard({});
      });
    return () => {
      cancelled = true;
    };
  }, [metadata, registered, filters]);

  // A dashboard box's height for the types that get one; depictio's own
  // preview width — and its natural height — for the two that never do.
  const { previewHeight, previewWidth } = useMemo(() => {
    const type = String(metadata.component_type);
    const width = NARROW_PREVIEW_WIDTH[type];
    if (width) return { previewHeight: undefined, previewWidth: width };
    return {
      previewHeight: gridBoxHeight(defaultLayoutForType(type, 'right', 0).h),
      previewWidth: undefined,
    };
  }, [metadata.component_type]);

  if (!fixture.rows.length) {
    return (
      <Alert color="gray" variant="light" icon={<Icon icon="mdi:table-off" />}>
        This output's fixture has no rows to preview — the render still exports
        and is checked against the fixture in CI.
      </Alert>
    );
  }

  const preview = (
    <Box
      data-studio-preview={metadata.component_type}
      style={{
        height: previewHeight,
        minHeight: previewHeight,
        maxWidth: previewWidth,
        width: '100%',
        position: 'relative',
      }}
    >
      {registered && (
        <ComponentRenderer
          dashboardId={STUDIO_DASHBOARD_ID}
          metadata={metadata as StoredMetadata}
          filters={filters}
          onFilterChange={upsertFilter}
          cardValue={card?.value}
          cardSecondaryValues={card?.secondary}
          cardLoading={metadata.component_type === 'card' && card === null}
          showDragHandle={false}
          refreshTick={exactCandidate ? exactEpoch : undefined}
        />
      )}
    </Box>
  );

  if (exactCandidate) {
    return (
      <>
        {preview}
        <FigureFidelity index={String(metadata.index)} />
      </>
    );
  }

  // A component narrower than the frame is centred in it rather than left in a
  // corner of empty background — the same framing depictio's own card builder
  // gives its preview.
  return previewWidth ? <Center>{preview}</Center> : preview;
}

/** One line under a UI-mode figure while it is not depictio's own rendering:
 *  the exact renderer is loading, could not load, or could not draw this one
 *  (the approximation is shown instead). Nothing once it is exact. */
function FigureFidelity({ index }: { index: string }) {
  const status = useExactFigures((s) => s.status);
  const error = useExactFigures((s) => s.error);
  const entry = useExactFigures((s) => s.fidelity[index]);
  if (entry?.fidelity === 'exact') return null;
  let text: string;
  let title: string | undefined;
  let state: string;
  if (status === 'failed') {
    state = 'unavailable';
    text = 'Approximate preview — exact rendering unavailable';
    title = error;
  } else if (status === 'ready' && entry && entry.reason !== 'loading') {
    state = 'fallback';
    text = "Approximate preview — depictio's renderer could not draw this figure here";
    title = entry.reason;
  } else {
    state = 'loading';
    text = 'Approximate preview — exact rendering loading…';
  }
  return (
    <Group gap={6} mt={4} wrap="nowrap" data-testid="figure-fidelity" data-state={state} title={title}>
      {state === 'loading' && <Loader size={10} />}
      <Text fz="xs" c="dimmed">
        {text}
      </Text>
    </Group>
  );
}
