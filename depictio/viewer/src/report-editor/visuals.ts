import { componentTypeVisual } from 'depictio-react-core';
import type { ComponentTypeVisual } from 'depictio-react-core';

const ICONIFY_ID = /^[a-z0-9][a-z0-9-]*:[a-z0-9][a-z0-9-]*$/i;

/** A tab's Iconify id as the outline gives it; a plain tab icon when it names
 *  none (an image path, nothing). */
export function tabIconId(icon: string | null | undefined): string {
  return icon && ICONIFY_ID.test(icon) ? icon : 'mdi:tab';
}

/** The tab's accent for its icon: the outline's own colour, else a theme one. */
export function tabTint(color: string | null | undefined): string {
  return color || 'var(--mantine-color-dimmed)';
}

/** Icon, label and accent of a component type, the dashboard's own. */
export function typeVisual(type: string | null | undefined): ComponentTypeVisual {
  return componentTypeVisual(type ?? '');
}
