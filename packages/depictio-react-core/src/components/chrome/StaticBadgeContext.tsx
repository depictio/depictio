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
import { Badge, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

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

/** Shared tier badge label/color maps. Exported (as STATIC_TIER_BADGE_* from
 *  the package barrel) so the viewer's Export-static preflight modal renders
 *  the same vocabulary as the in-bundle badges. 'live' is deliberately absent
 *  — the in-bundle badge only renders non-live tiers; callers that need to
 *  show live rows supply their own 'Live'/'green' entry. */
export const BADGE_LABEL: Record<string, string> = {
  partial: 'Partial',
  frozen: 'Frozen',
  omitted: 'Omitted',
};

export const BADGE_COLOR: Record<string, string> = {
  partial: 'yellow',
  frozen: 'blue',
  omitted: 'gray',
};

/**
 * The headline a viewer needs before the fine print — what the tier means for
 * the tile they are looking at, not what the exporter had to do.
 *
 * `frozen` is stated in terms of FILTERS on purpose. Frozen means the payload
 * was computed once at export time and shipped verbatim, so moving a filter
 * cannot change it — which, on a dashboard whose whole idiom is "filter and
 * watch everything follow", is the only thing a reader can get wrong without
 * being told. Every frozen tile says it, whatever the reason underneath.
 */
const TIER_HEADLINE: Record<string, string> = {
  partial: 'Approximate — built from a sample of the data',
  frozen: 'Filters do not affect this view',
  omitted: 'Not included in this export',
};

/** Small glyph carrying the same message as the headline, for a corner where
 *  there is no room for words. */
const TIER_ICON: Record<string, string> = {
  partial: 'mdi:approximately-equal',
  frozen: 'mdi:filter-off-outline',
  omitted: 'mdi:eye-off-outline',
};

/** `TierReason` (see the bundle manifest contract) in plain language. Used as
 *  the tooltip's second line when the producer wrote no `detail`. */
const REASON_TEXT: Record<string, string> = {
  multiqc: 'MultiQC reports are shipped as rendered output.',
  celery_compute: 'This view is computed by a background worker, which a bundle has no way to run.',
  code_mode: 'The figure is produced by user code that needs a Python runtime.',
  binding_miss: 'The export could not map this figure back onto its source columns.',
  max_points: 'The underlying data is larger than the bundle point budget.',
  link_table_too_big: 'The cross-collection link table was too large to bundle.',
  map_tiles: 'Map tiles come from a tile server this bundle may not reach.',
  jbrowse: 'JBrowse needs a genome-browser backend.',
  image: 'Images are shipped as they were rendered at export time.',
  whole_frame_viz: 'This view is computed over the whole table at once.',
  filter_expr_window: 'The filter expression uses a window function the in-browser engine has no equivalent for.',
  unsupported: 'Not supported by the in-browser engine.',
};

/**
 * Rendered by ComponentChrome as the first cell of its action row; null
 * outside a static bundle or for live tiles. The `depictio-static-tier-badge`
 * wrapper class exempts it from the row's hover-only opacity rule (see
 * chrome.css) so the badge stays visible without hover while the action icons
 * next to it keep their hover-reveal behavior.
 *
 * The badge itself stays a bare word plus a glyph — a tile corner has no room
 * for a sentence — and the tooltip carries the meaning: headline first, then
 * the producer's `detail` (or the reason spelled out) underneath.
 */
export const StaticTierBadge: React.FC<{ componentIndex: string | undefined }> = ({
  componentIndex,
}) => {
  const tiers = useContext(StaticBadgeContext);
  if (!tiers || !componentIndex) return null;
  const entry = tiers[componentIndex];
  if (!entry || entry.tier === 'live') return null;

  const icon = TIER_ICON[entry.tier];
  const badge = (
    <Badge
      size="xs"
      variant="light"
      color={BADGE_COLOR[entry.tier] ?? 'gray'}
      style={{ textTransform: 'none', flexShrink: 0 }}
      data-static-tier={entry.tier}
      data-static-reason={entry.reason ?? undefined}
      leftSection={icon ? <Icon icon={icon} width={11} height={11} /> : undefined}
    >
      {BADGE_LABEL[entry.tier] ?? entry.tier}
    </Badge>
  );

  const headline = TIER_HEADLINE[entry.tier];
  const finePrint = entry.detail ?? (entry.reason ? REASON_TEXT[entry.reason] : null);
  const tooltip =
    headline || finePrint ? (
      <Stack gap={2}>
        {headline && (
          <Text size="xs" fw={600} lh={1.3}>
            {headline}
          </Text>
        )}
        {finePrint && (
          <Text size="xs" lh={1.3}>
            {finePrint}
          </Text>
        )}
      </Stack>
    ) : null;

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
        <Tooltip label={tooltip} withArrow position="bottom-start" multiline w={260}>
          {badge}
        </Tooltip>
      ) : (
        badge
      )}
    </span>
  );
};
