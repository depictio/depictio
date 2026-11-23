import React, { useEffect, useMemo, useState } from 'react';
import { Box, Loader, Center, Text } from '@mantine/core';
import {
  ComponentRenderer,
  bulkComputeCards,
  fetchDashboard,
} from 'depictio-react-core';
import type { InteractiveFilter, StoredMetadata } from 'depictio-react-core';

import GuideSandbox from '../guide/GuideSandbox';

/** The component types drawn live in the outline. The rest (filters, genome
 *  browsers, maps, MultiQC, advanced views) keep their type badge: they need
 *  dashboard state or heavy bundles a row in a list should not carry. */
export const LIVE_TYPES = new Set(['figure', 'table', 'card', 'text', 'image']);

// One dashboard fetch per tab, shared by every row of that tab.
const tabMetadata = new Map<string, Promise<StoredMetadata[]>>();

function loadTabMetadata(tabId: string): Promise<StoredMetadata[]> {
  let pending = tabMetadata.get(tabId);
  if (!pending) {
    pending = fetchDashboard(tabId).then((d) => d.stored_metadata ?? []);
    pending.catch(() => tabMetadata.delete(tabId));
    tabMetadata.set(tabId, pending);
  }
  return pending;
}

interface TileLiveProps {
  tabId: string;
  componentId: string;
  filters: InteractiveFilter[];
}

/** One tile, drawn by the viewer's own renderer with the report's filters. */
const TileLive: React.FC<TileLiveProps> = ({ tabId, componentId, filters }) => {
  const [metadata, setMetadata] = useState<StoredMetadata | null | undefined>(undefined);
  const [card, setCard] = useState<{
    value?: unknown;
    secondary?: Record<string, unknown>;
    loading: boolean;
  }>({ loading: false });

  useEffect(() => {
    let cancelled = false;
    loadTabMetadata(tabId)
      .then((list) => {
        if (!cancelled) setMetadata(list.find((m) => m.index === componentId) ?? null);
      })
      .catch(() => {
        if (!cancelled) setMetadata(null);
      });
    return () => {
      cancelled = true;
    };
  }, [tabId, componentId]);

  const isCard = metadata?.component_type === 'card';
  const filterKey = JSON.stringify(filters);
  useEffect(() => {
    if (!isCard) return;
    const ctrl = new AbortController();
    setCard((c) => ({ ...c, loading: true }));
    bulkComputeCards(tabId, filters, [componentId], undefined, ctrl.signal)
      .then((res) =>
        setCard({
          value: res.values?.[componentId],
          secondary: res.secondary_values?.[componentId],
          loading: false,
        }),
      )
      .catch((err) => {
        if (err?.name !== 'AbortError') setCard({ loading: false });
      });
    return () => ctrl.abort();
    // `filterKey` is the filters' identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabId, componentId, isCard, filterKey]);

  const list = useMemo(() => (metadata ? [metadata] : []), [metadata]);

  if (metadata === undefined) {
    return (
      <Center h={120}>
        <Loader size="sm" />
      </Center>
    );
  }
  if (!metadata) {
    return (
      <Text size="xs" c="dimmed">
        This tile could not be loaded.
      </Text>
    );
  }
  return (
    <Box h={isCard ? 130 : 280} data-testid="report-tile-live">
      <GuideSandbox metadata={list}>
        <ComponentRenderer
          metadata={metadata}
          dashboardId={tabId}
          filters={filters}
          cardValue={card.value}
          cardSecondaryValues={card.secondary}
          cardLoading={card.loading}
        />
      </GuideSandbox>
    </Box>
  );
};

export default TileLive;
