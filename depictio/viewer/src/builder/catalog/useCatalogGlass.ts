import { useGlassPages } from '../../chrome/variants/glass/pages';

/**
 * How the catalog browser accents itself: violet in Classic (the catalog's own
 * hue), the instance's primary under Glass, where one accent is spent on what is
 * selected or actionable. `undefined` is Mantine's "use the primary colour".
 */
export function useCatalogGlass(): { glass: boolean; tone: string | undefined } {
  const glass = useGlassPages();
  return { glass, tone: glass ? undefined : 'violet' };
}
