/**
 * The two ways to start a component: build one, or take one the catalog offers.
 *
 * Both surfaces of the Add-component flow name these paths at the same time on
 * the same screen, the two-tile chooser and the header band above it, and they
 * had drifted onto separate glyphs for the same concept. The tiles are what a
 * user meets first, so their vocabulary is the reference and this is where it
 * lives.
 *
 * The catalog carries an `image` as well as an icon: the pinwheel-with-a-hammer
 * mark is the catalog's own branding, and no glyph stands in for it as well as
 * it stands for itself. The icon is what surfaces too small for the mark use.
 */

/** Served from depictio/viewer/public/logos under the SPA base (/dashboard/). */
export const TOOLS_CATALOG_LOGO = '/dashboard/logos/tools_catalog_logo.png';

export interface ComponentSourceVisual {
  label: string;
  /** Iconify id. A literal so the bundled icon subset picks it up. */
  icon: string;
  /** Image src, preferred over `icon` where there is room for it. */
  image?: string;
  /** Mantine colour name, used for the tile accent and badge. */
  accent: string;
}

export const COMPONENT_SOURCE: Record<'manual' | 'catalog', ComponentSourceVisual> = {
  manual: { label: 'New component', icon: 'mdi:puzzle-plus', accent: 'blue' },
  catalog: {
    label: 'Pick from catalog',
    icon: 'mdi:hammer',
    image: TOOLS_CATALOG_LOGO,
    accent: 'violet',
  },
};
