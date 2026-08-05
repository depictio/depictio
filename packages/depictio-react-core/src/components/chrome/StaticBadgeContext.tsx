/**
 * Liveness badges for the serverless static runtime (RFC §3.2 / errata #6).
 *
 * The static runtime wraps the app in `StaticBadgeProvider` with the bundle
 * manifest's per-component tier map; `ComponentChrome` renders the badge as
 * the first (always-visible) cell of its top-right action row on every
 * non-live component — never hover-gated, so degraded fidelity cannot be
 * missed, and never overlapping the component's own title/content (the action
 * row is a flex row/column, so the hover-revealed icons lay out AFTER the
 * badge instead of on top of it). The normal server build mounts no provider,
 * the context stays `null`, and nothing renders — zero cost and zero visual
 * change outside static bundles.
 *
 * The provider doubles as the "running inside a static bundle" signal:
 * `useIsStaticBundle()` lets chrome components hide affordances that cannot
 * work without a backend (edit buttons, management links, auth badges).
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

/** True when a `StaticBadgeProvider` is mounted above the caller — i.e. the
 *  app is running inside a serverless static bundle. Server builds mount no
 *  provider, so this is a zero-cost `false` there. Used to hide affordances
 *  that need a backend (edit / management navigation, auth chrome). */
export function useIsStaticBundle(): boolean {
  return useContext(StaticBadgeContext) !== null;
}

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

/**
 * Rendered by ComponentChrome as the first cell of its action row; null
 * outside a static bundle or for live tiers. The `depictio-static-tier-badge`
 * wrapper class exempts it from the row's hover-only opacity rule (see
 * chrome.css) so the badge stays visible without hover while the action icons
 * next to it keep their hover-reveal behavior.
 */
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
      style={{ textTransform: 'none', flexShrink: 0 }}
      data-static-tier={entry.tier}
    >
      {BADGE_LABEL[entry.tier] ?? entry.tier}
    </Badge>
  );
  const tooltip = entry.detail ?? entry.reason;
  return (
    <span
      className="depictio-static-tier-badge"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        // Hoverable (for the detail tooltip) even when the positioning
        // wrapper in ComponentChrome is pointer-events: none.
        pointerEvents: 'auto',
        // Opaque page-colored backdrop under the translucent light-variant
        // badge: on narrow components renderer content can run close to the
        // corner, and without this the two layers blend into each other.
        background: 'var(--mantine-color-body)',
        borderRadius: 'var(--mantine-radius-xl)',
      }}
    >
      {tooltip ? (
        <Tooltip label={tooltip} withArrow position="bottom-start">
          {badge}
        </Tooltip>
      ) : (
        badge
      )}
    </span>
  );
};
