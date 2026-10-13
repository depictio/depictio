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
import { Alert, Box, Center } from '@mantine/core';
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
  const [card, setCard] = useState<{
    value?: unknown;
    secondary?: Record<string, unknown>;
  } | null>(null);
  useEffect(() => {
    if (metadata.component_type !== 'card' || !registered) return;
    let cancelled = false;
    bulkComputeCards(STUDIO_DASHBOARD_ID, [], [metadata.index])
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
  }, [metadata, registered]);

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
          filters={[]}
          cardValue={card?.value}
          cardSecondaryValues={card?.secondary}
          cardLoading={metadata.component_type === 'card' && card === null}
          showDragHandle={false}
        />
      )}
    </Box>
  );

  // A component narrower than the frame is centred in it rather than left in a
  // corner of empty background — the same framing depictio's own card builder
  // gives its preview.
  return previewWidth ? <Center>{preview}</Center> : preview;
}
