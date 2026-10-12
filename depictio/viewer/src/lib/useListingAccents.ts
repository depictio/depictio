import { useMemo } from 'react';
import { useBrandAccents } from 'depictio-react-core';

import { useGlassPages } from '../chrome/variants/glass/pages';
import { useSectionPalettes } from '../chrome/variants/glass/pages/GlassPage';

/**
 * `useBrandAccents` for the Dashboards and Projects listings. On a Glass page
 * the page wears its section palette (the logo's orange / teal, or the
 * instance brand's own), so the accents the listing reaches for (tertiary on
 * Dashboards, secondary on Projects, either of them in code shared between the
 * two) resolve to that one palette rather than Mantine's stock orange / teal.
 * Classic keeps the brand accents untouched.
 */
export function useListingAccents(
  section: 'dashboards' | 'projects',
): ReturnType<typeof useBrandAccents> {
  const accents = useBrandAccents();
  const glass = useGlassPages();
  const palettes = useSectionPalettes();
  return useMemo(
    () =>
      glass
        ? { ...accents, tertiary: palettes[section], secondary: palettes[section] }
        : accents,
    [accents, glass, palettes, section],
  );
}
