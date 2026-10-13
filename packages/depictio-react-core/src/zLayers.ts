/**
 * Stacking order for the surfaces that float over a dashboard.
 *
 * These used to be magic numbers spread across the components that set them,
 * which is how the map panel (250) ended up ABOVE every drawer: Mantine's
 * default `zIndex` for a Modal/Drawer is 200, so the card floated over the
 * drawer AND over its dimming overlay. Anything that leaves the document flow
 * on a dashboard picks its layer from here instead.
 *
 * Above these sit the walkthrough's spotlight backdrop (1000) and its popover
 * (1100), which must never be occluded — leave room below them.
 */
export const Z_LAYERS = {
  /** Fixed furniture pinned to the viewport: FABs, banners. */
  furniture: 200,
  /**
   * The draggable map card. Above the furniture on purpose — the card can be
   * dragged over the Notes FAB, and being punctured by it looks broken.
   */
  mapPanel: 250,
  /**
   * Drawers and modals opened over the dashboard. Above `mapPanel` so their
   * overlay dims the map like the rest of the dashboard rather than leaving
   * it lit and clickable on top.
   */
  overlay: 300,
  /** A modal opened from inside a drawer or another modal. */
  nestedOverlay: 400,
  /**
   * Tooltips and popovers that must clear whatever opened them. Mantine's
   * default for these is 300, which puts a tooltip raised from inside a
   * modal BEHIND that modal.
   */
  tooltip: 500,
} as const;
