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
import React, { createContext, useContext, useState } from 'react';
import { Anchor, Badge, HoverCard, Stack, Text } from '@mantine/core';
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

/** A component the manifest never classified. Not a manifest tier: the runtime
 *  invents it when `tiers` carries no entry for a component the dashboard
 *  renders, so the tile says "I cannot vouch for this" instead of passing for
 *  a normal live one. */
const UNKNOWN_TIER = 'unknown';

/** Badge vocabulary as rendered, i.e. the exported manifest tiers plus the
 *  runtime's own `unknown`. The exported maps stay a mirror of the manifest. */
const TIER_LABEL: Record<string, string> = { ...BADGE_LABEL, [UNKNOWN_TIER]: 'Unverified' };
const TIER_COLOR: Record<string, string> = { ...BADGE_COLOR, [UNKNOWN_TIER]: 'gray' };

/**
 * The headline a viewer needs before the fine print — what the tier means for
 * the tile they are looking at, not what the exporter had to do.
 *
 * `frozen` is stated in terms of FILTERS on purpose. Frozen means the payload
 * was computed once at export time and shipped verbatim, so moving a filter
 * cannot change it — which, on a dashboard whose whole idiom is "filter and
 * watch everything follow", is the only thing a reader can get wrong without
 * being told. Every frozen tile says it, whatever the reason underneath.
 *
 * `partial` deliberately does NOT promise a sample: the tier covers both a
 * build-time downsample and a bound figure that refills every selected row
 * while the live dashboard samples. What holds in both is that the detail
 * differs from the server view.
 */
const TIER_HEADLINE: Record<string, string> = {
  partial: 'Approximate: some detail differs from the live dashboard',
  frozen: 'Filters do not affect this view',
  omitted: 'Not included in this export',
  [UNKNOWN_TIER]: 'Not covered by this export',
};

/** Small glyph carrying the same message as the headline, for a corner where
 *  there is no room for words. */
const TIER_ICON: Record<string, string> = {
  partial: 'mdi:approximately-equal',
  frozen: 'mdi:filter-off-outline',
  omitted: 'mdi:eye-off-outline',
  [UNKNOWN_TIER]: 'mdi:help-circle-outline',
};

/**
 * `TierReason` (see the bundle manifest contract) as a sentence a reader can
 * act on: what the tile is showing them, and what they lose compared with the
 * live dashboard.
 *
 * This is the PRIMARY fine print, not a fallback. The producer's `detail` is a
 * build note written for whoever debugs the exporter — it names RFC sections,
 * roadmap phases and, when a payload fails, the raw exception — so it is
 * demoted to the collapsible "technical details" line below, and only when it
 * reads as prose (see `technicalDetail`).
 *
 * Written for the tier that actually emits each reason, which is "the tile is
 * showing a snapshot" for everything but the omitted-only reasons. Where the
 * same reason also lands on `omitted` (nothing to show at all), the sentence
 * flips — see REASON_TEXT_OMITTED.
 */
const REASON_TEXT: Record<string, string> = {
  multiqc:
    'Shows the MultiQC report as the server rendered it when the dashboard was exported. The dashboard filters no longer reach it.',
  celery_compute:
    'This view comes from a heavy computation that ran once, over the whole dataset, when the dashboard was exported. Filtering cannot re-run it.',
  code_mode:
    'This chart is produced by a Python script, which needs a server to run. It shows the result over the whole dataset.',
  binding_miss:
    'The export could not tell which columns each part of this chart comes from, so it ships as a snapshot of the whole dataset instead of being redrawn in your browser.',
  max_points:
    'The points drawn here are not the same selection the live dashboard makes, so density and rare points can look different.',
  link_table_too_big:
    'Filters from a linked data collection cannot reach this view: the table that translates between the two collections was too large to include.',
  map_tiles:
    'Shows the map as it was when the dashboard was exported, without its online background tiles: a standalone file cannot reach the tile service.',
  jbrowse:
    'The genome browser streams its tracks from a Depictio server, so this panel could not be included.',
  image:
    'The pictures live in storage that a standalone file cannot reach, so the gallery could not be included.',
  whole_frame_viz:
    'This view is computed over the whole table at once, so your browser cannot rebuild it for a filtered subset.',
  filter_expr_window:
    'This view uses a filter that compares each row against the rest of its group, which the in-browser engine cannot evaluate.',
  unsupported:
    'This view cannot be rebuilt in your browser, so it shows the result over the whole dataset as it was when the dashboard was exported.',
};

/** Same reasons, for the tier where the component is absent rather than
 *  snapshotted. Only the reasons that reach `omitted` need an entry; the rest
 *  fall through to REASON_TEXT. */
const REASON_TEXT_OMITTED: Record<string, string> = {
  multiqc: 'Rendering a MultiQC report needs a Depictio server, so none could be included here.',
  celery_compute:
    'This view needs a heavy computation that only a Depictio server can run, and no result could be computed for this export.',
  code_mode:
    'This chart is produced by a Python script that could not be run for this export, so nothing is shown here.',
  binding_miss:
    'The export could neither redraw this chart in your browser nor fall back to a snapshot, so nothing is shown here.',
  map_tiles:
    'Maps need background tiles from an online service that a standalone file cannot reach, so this map is not part of the export.',
  unsupported:
    'This view could not be built for the export: the data it needs, or the renderer behind it, is only available on a Depictio server.',
};

/** Last resort when a non-live entry carries no reason at all — the tier is
 *  still worth spelling out, in the same voice. */
const TIER_TEXT: Record<string, string> = {
  partial: 'Some of the detail in this view differs from the live dashboard.',
  frozen:
    'Shows the result over the whole dataset, exactly as it was when the dashboard was exported.',
  omitted: 'This view could not be included in the export, so nothing is shown here.',
  [UNKNOWN_TIER]:
    'This view was not part of the export, so it may show nothing or content that is out of date.',
};

/**
 * The curated sentence for one verdict, or null for a live component.
 *
 * Exported (as `staticTierExplanation`) so the viewer's Export-static preflight
 * modal explains a verdict with the same words the bundle will show once it is
 * built — the modal is a promise about the badges, so the two must not drift.
 */
export function staticTierExplanation(tier: string, reason?: string | null): string | null {
  if (tier === 'live') return null;
  if (reason) {
    const omitted = tier === 'omitted' ? REASON_TEXT_OMITTED[reason] : undefined;
    const text = omitted ?? REASON_TEXT[reason];
    if (text) return text;
  }
  return TIER_TEXT[tier] ?? null;
}

/**
 * Markers that make a producer `detail` unfit for a reader: design-document
 * cross-references, internal roadmap numbering, the manifest's own machine
 * tokens, and anything that smells like an exception the exporter caught and
 * passed through verbatim (a real bundle ships
 * "frozen payload could not be computed: 404: ...").
 *
 * The producers are free to write build notes for themselves; this is the
 * gate that keeps such a note out of the UI. A rejected detail is simply not
 * offered — the curated sentence above already carries the meaning, and half
 * an engineering trace explains less than nothing.
 */
const INTERNAL_MARKERS: RegExp[] = [
  /\bRFC\b|§/i,
  /\bphases?\s*\d/i,
  /↔/,
  /\b[45]\d{2}:/,
  /\b(?:traceback|exception|error)\b/i,
  /could not be computed/i,
  /\b(?:binding_miss|celery_compute|code_mode|max_points|link_table_too_big|whole_frame_viz|filter_expr_window|unsupported)\b/,
  // SHOUTING_CONSTANT (a settings name like FIGURE_MAX_POINTS). Requires the
  // underscore, so bioinformatics acronyms — QUAST, ANCOM, FastQC — pass.
  /[A-Z]{2,}_[A-Z_]+/,
];

/** The producer's build note when it reads as prose, else null. */
function technicalDetail(detail: string | null | undefined): string | null {
  if (!detail) return null;
  const trimmed = detail.trim();
  if (!trimmed) return null;
  return INTERNAL_MARKERS.some((re) => re.test(trimmed)) ? null : trimmed;
}

/**
 * Rendered by ComponentChrome as the first cell of its action row; null
 * outside a static bundle or for live tiles. The `depictio-static-tier-badge`
 * wrapper class exempts it from the row's hover-only opacity rule (see
 * chrome.css) so the badge stays visible without hover while the action icons
 * next to it keep their hover-reveal behavior.
 *
 * The badge itself stays a bare word plus a glyph — a tile corner has no room
 * for a sentence — and the hover card carries the meaning: the tier headline,
 * then the curated sentence for the reason underneath. The producer's own
 * `detail` is a build note, so it sits one click away behind "Technical
 * details" (a HoverCard rather than a Tooltip precisely so that line can be
 * clicked), and only when it reads as prose.
 *
 * A component the manifest never classified is badged too, as `Unverified`:
 * inside a bundle, silence would read as "this tile is fine".
 */
export const StaticTierBadge: React.FC<{ componentIndex: string | undefined }> = ({
  componentIndex,
}) => {
  const tiers = useContext(StaticBadgeContext);
  const [detailOpen, setDetailOpen] = useState(false);
  if (!tiers || !componentIndex) return null;
  const entry = tiers[componentIndex];
  if (entry?.tier === 'live') return null;
  const tier = entry ? entry.tier : UNKNOWN_TIER;

  const icon = TIER_ICON[tier];
  const badge = (
    <Badge
      size="xs"
      variant="light"
      color={TIER_COLOR[tier] ?? 'gray'}
      style={{ textTransform: 'none', flexShrink: 0 }}
      data-static-tier={tier}
      data-static-reason={entry?.reason ?? undefined}
      leftSection={icon ? <Icon icon={icon} width={11} height={11} /> : undefined}
    >
      {TIER_LABEL[tier] ?? tier}
    </Badge>
  );

  const headline = TIER_HEADLINE[tier];
  const explanation = staticTierExplanation(tier, entry?.reason);
  const detail = technicalDetail(entry?.detail);

  return (
    <span
      className="depictio-static-tier-badge"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        // Hoverable (for the explanation card) even when the positioning
        // wrapper in ComponentChrome is pointer-events: none.
        pointerEvents: 'auto',
        // Opaque page-colored backdrop under the translucent light-variant
        // badge: on narrow components renderer content can run close to the
        // corner, and without this the two layers blend into each other.
        background: 'var(--mantine-color-body)',
        borderRadius: 'var(--mantine-radius-xl)',
      }}
    >
      <HoverCard
        width={280}
        shadow="md"
        withArrow
        position="bottom-start"
        openDelay={120}
        closeDelay={120}
        onClose={() => setDetailOpen(false)}
      >
        <HoverCard.Target>{badge}</HoverCard.Target>
        <HoverCard.Dropdown p="xs">
          <Stack gap={4}>
            {headline && (
              <Text size="xs" fw={600} lh={1.3}>
                {headline}
              </Text>
            )}
            {explanation && (
              <Text size="xs" lh={1.35}>
                {explanation}
              </Text>
            )}
            {detail && (
              <>
                <Anchor
                  component="button"
                  type="button"
                  size="xs"
                  ta="left"
                  onClick={() => setDetailOpen((open) => !open)}
                  data-testid="static-tier-detail-toggle"
                >
                  {detailOpen ? 'Hide technical details' : 'Technical details'}
                </Anchor>
                {/* Mounted only when opened, not hidden with a Collapse: a
                    build note clipped to zero height is still text sitting in
                    the page, and this line exists precisely to keep it out of
                    the reader's way until they ask for it. */}
                {detailOpen && (
                  <Text size="xs" c="dimmed" lh={1.3} data-testid="static-tier-detail">
                    {detail}
                  </Text>
                )}
              </>
            )}
          </Stack>
        </HoverCard.Dropdown>
      </HoverCard>
    </span>
  );
};
