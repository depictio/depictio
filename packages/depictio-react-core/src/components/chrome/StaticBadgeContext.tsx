/**
 * Liveness badges for the serverless static runtime (RFC §3.2 / errata #6).
 *
 * The static runtime wraps the app in `StaticBadgeProvider` with the bundle
 * manifest's per-component tier map; `ComponentChrome` reads the context and
 * pins a badge top-left on every non-live component — always visible, never
 * hover-gated, so degraded fidelity cannot be missed. The normal server build
 * mounts no provider, the context stays `null`, and nothing renders — zero
 * cost and zero visual change outside static bundles.
 *
 * A context (read inside `ComponentChrome`, a real component) rather than a
 * `wrapWithChrome` opt: one of the ten chrome call sites lives in the
 * separately lazy-loaded `AdvancedVizDispatch` chunk, which prop-threading
 * would miss, and the public `wrapWithChrome` signature stays untouched.
 */
import React, { createContext, useContext } from 'react';
import { Badge, Tooltip } from '@mantine/core';

/** Mirrors `TierEntry` in the bundle manifest (depictio-static-core). */
export interface StaticTierEntry {
  tier: 'live' | 'partial' | 'frozen' | 'omitted';
  reason?: string | null;
  detail?: string | null;
}

/** component index (StoredMetadata.index) -> liveness verdict. */
export type StaticTierMap = Record<string, StaticTierEntry>;

const StaticBadgeContext = createContext<StaticTierMap | null>(null);

export const StaticBadgeProvider: React.FC<{
  tiers: StaticTierMap;
  children: React.ReactNode;
}> = ({ tiers, children }) => (
  <StaticBadgeContext.Provider value={tiers}>{children}</StaticBadgeContext.Provider>
);

const BADGE_LABEL: Record<string, string> = {
  partial: 'Partial',
  frozen: 'Frozen',
  omitted: 'Omitted',
};

const BADGE_COLOR: Record<string, string> = {
  partial: 'yellow',
  frozen: 'blue',
  omitted: 'gray',
};

/** Rendered by ComponentChrome; null outside a static bundle or for live tiers. */
export const StaticTierBadge: React.FC<{ componentIndex: string | undefined }> = ({
  componentIndex,
}) => {
  const tiers = useContext(StaticBadgeContext);
  if (!tiers || !componentIndex) return null;
  const entry = tiers[componentIndex];
  if (!entry || entry.tier === 'live') return null;
  const badge = (
    <Badge
      size="xs"
      variant="light"
      color={BADGE_COLOR[entry.tier] ?? 'gray'}
      style={{
        position: 'absolute',
        top: 4,
        left: 4,
        zIndex: 5,
        pointerEvents: 'auto',
        textTransform: 'none',
      }}
      data-static-tier={entry.tier}
    >
      {BADGE_LABEL[entry.tier] ?? entry.tier}
    </Badge>
  );
  const tooltip = entry.detail ?? entry.reason;
  return tooltip ? (
    <Tooltip label={tooltip} withArrow position="bottom-start">
      {badge}
    </Tooltip>
  ) : (
    badge
  );
};
