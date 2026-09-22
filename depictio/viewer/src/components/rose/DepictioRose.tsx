import React, { useEffect, useRef } from 'react';
// Registers <depictio-rose> and publishes window.DepictioRose. Side-effect import:
// the mark is drawn from geometry in that file, so there is no SVG asset to ship
// and no id coupling between the markup and the CSS.
import './depictio-rose.js';

export type RoseMode = 'loading' | 'fan' | 'intro' | 'live' | 'sweep' | 'logo';

export interface DepictioRoseProps {
  /** loading never rests (use it for spinners); logo is the static mark. */
  mode?: RoseMode;
  /** Side of the square, in px. Omit to size it from CSS. */
  size?: number;
  speed?: number;
  /** Seconds the mark rests on the logo shape between cycles. */
  hold?: number;
  bounce?: 'soft' | 'medium' | 'strong' | number;
  paused?: boolean;
  /** Accessible name; '' makes it decorative. Defaults to "Loading" in loading mode. */
  label?: string;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * The Depictio mark, animated as a polar-area chart whose radii keep changing:
 * the same motion as the title of the Nextflow Summit talk, at any size.
 *
 * It honours `prefers-reduced-motion` by falling back to the static mark with a
 * slow opacity breathe, and it pauses itself when off-screen or in a hidden tab.
 */
const DepictioRose: React.FC<DepictioRoseProps> = ({
  mode = 'loading', size, speed, hold, bounce, paused, label, className, style,
}) => {
  const host = useRef<HTMLSpanElement>(null);
  const el = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const node = document.createElement('depictio-rose');
    el.current = node;
    host.current?.appendChild(node);
    return () => { node.remove(); el.current = null; };
  }, []);

  useEffect(() => {
    const node = el.current;
    if (!node) return;
    const set = (k: string, v: unknown) =>
      v === undefined || v === null ? node.removeAttribute(k) : node.setAttribute(k, String(v));
    set('mode', mode);
    set('size', size);
    set('speed', speed);
    set('hold', hold);
    set('bounce', bounce);
    set('label', label);
    node.toggleAttribute('paused', !!paused);
  }, [mode, size, speed, hold, bounce, paused, label]);

  return <span ref={host} className={className} style={{ display: 'inline-block', ...style }} />;
};

export default DepictioRose;
