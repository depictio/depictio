import { useEffect, useRef, useState } from 'react';

import { resolveBrandTheme } from '../../api';
import type { BrandTheme } from '../../brandTheme';

/**
 * The resolved form of a draft brand theme, for live preview.
 *
 * Derivation (figure colorway, continuous scale) is deliberately server-side
 * so the render path and the SPA can't drift, which means an unsaved draft has
 * to ask the server what it resolves to. Debounced, because the source is a
 * row of color pickers.
 *
 * Falls back to the unresolved draft if the request fails: a preview missing
 * its derived swatches is better than a preview that vanishes.
 */
export function useResolvedBrandTheme(theme: BrandTheme, delayMs = 350): BrandTheme {
  const [resolved, setResolved] = useState<BrandTheme>(theme);
  // Only the latest request may write: color pickers fire fast enough that an
  // earlier, slower response would otherwise overwrite a newer one.
  const requestId = useRef(0);

  useEffect(() => {
    const id = ++requestId.current;
    const timer = setTimeout(() => {
      resolveBrandTheme(theme)
        .then((next) => {
          if (id === requestId.current) setResolved(next);
        })
        .catch(() => {
          if (id === requestId.current) setResolved(theme);
        });
    }, delayMs);
    return () => clearTimeout(timer);
    // Serialised so a new object with identical content doesn't refetch.
  }, [JSON.stringify(theme), delayMs]); // eslint-disable-line react-hooks/exhaustive-deps

  return resolved;
}
