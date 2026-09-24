import React from 'react';
import { Icon } from '@iconify/react';

import type { FilterSectionSpec } from '../api';

/**
 * A section's icon, tinted with the section's colour.
 *
 * Shared by the filter panel and the dashboard grid on purpose: a section named
 * "QC" should look the same wherever it is rendered, and the two headers used to
 * disagree on icon size *and* on which side of the title the icon landed on —
 * the grid passed it through `Accordion.Control`'s `icon` prop, which Mantine
 * renders *after* the label with a `spacing-lg` inline-start margin.
 *
 * A bare glyph rather than a `ThemeIcon`: the tinted square read as a button in
 * a header row that already holds a chevron, and shrank the icon to whatever fit
 * inside its box. The colour alone carries the section identity.
 *
 * Renders nothing when the section declares no icon, so a header without one
 * keeps its title flush against the chevron. Authoring UIs — where a row must
 * stay aligned whether or not an icon has been picked yet — pass `fallbackIcon`
 * to get a placeholder instead.
 */
export const SectionIcon: React.FC<{
  spec?: Pick<FilterSectionSpec, 'icon' | 'color'>;
  size?: number;
  fallbackIcon?: string;
}> = ({ spec, size = 22, fallbackIcon }) => {
  const icon = spec?.icon || fallbackIcon;
  if (!icon) return null;
  return (
    <Icon
      icon={icon}
      width={size}
      height={size}
      style={{ color: sectionColorVar(spec?.color), flexShrink: 0 }}
    />
  );
};

/**
 * A section's `color` is a Mantine palette *name* (`teal`), so it can't be used
 * as a CSS colour directly. Unset, sections stay neutral — the dimmed token
 * rather than a picked hue, so an undecorated dashboard doesn't look like every
 * section chose grey on purpose.
 */
export function sectionColorVar(color?: string | null): string {
  if (!color) return 'var(--mantine-color-dimmed)';
  return `var(--mantine-color-${color}-6)`;
}

/**
 * The palette a section falls back to when its spec names no colour. Kept to
 * four calm Mantine hues on purpose: enough to tell neighbouring sections
 * apart, few enough that an undecorated dashboard does not turn into a
 * rainbow.
 */
export const DEFAULT_SECTION_PALETTE = ['blue', 'teal', 'violet', 'orange'] as const;

/**
 * The palette name a section is drawn with: its declared `color`, else one
 * picked from `DEFAULT_SECTION_PALETTE` by hashing the section's name. Keyed
 * on the name rather than the position so the same section keeps its colour
 * in the grid, the filter panel and on every tab it is pinned to.
 */
export function resolveSectionColor(
  color?: string | null,
  name?: string | null,
): string | null {
  if (color) return color;
  if (!name) return null;
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return DEFAULT_SECTION_PALETTE[hash % DEFAULT_SECTION_PALETTE.length];
}

/**
 * The resolved palette name of the section a component is rendered in, or
 * null outside any section. Cards read it to tint their icon (and secondary
 * strip) when their own `icon_color` is unset, so a section's cards share its
 * colour without every YAML spelling it out.
 */
export const SectionColorContext = React.createContext<string | null>(null);

export default SectionIcon;
