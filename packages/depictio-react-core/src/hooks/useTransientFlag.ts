import { useEffect, useRef, useState } from 'react';

/**
 * Returns a boolean that flips to ``true`` whenever ``triggerKey`` changes
 * (after the initial render) and back to ``false`` after ``durationMs``.
 *
 * Used to drive transient visual states — e.g. the "new item glow" on
 * scatter / table / image renderers when a realtime ``data_collection_updated``
 * event arrives. Skipping the initial render keeps it from firing on first
 * mount: there's nothing visually to flag the first time the user opens a
 * dashboard.
 */
export function useTransientFlag(
  triggerKey: number | string | undefined,
  durationMs: number = 3000,
): boolean {
  const [active, setActive] = useState(false);
  const initialRef = useRef(true);

  useEffect(() => {
    if (initialRef.current) {
      initialRef.current = false;
      return;
    }
    if (triggerKey === undefined) return;
    setActive(true);
    const timer = window.setTimeout(() => setActive(false), durationMs);
    return () => window.clearTimeout(timer);
  }, [triggerKey, durationMs]);

  return active;
}

export default useTransientFlag;
