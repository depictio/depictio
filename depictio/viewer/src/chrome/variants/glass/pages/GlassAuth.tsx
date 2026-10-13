/**
 * The sign-in page under Glass: one paper card over a field of triangles,
 * the petals of the depictio rose drifting away from it, while the rose on
 * the card keeps moving its petals.
 */
import React from 'react';
import { useReducedMotion } from 'motion/react';
import { Moon, Sun } from 'lucide-react';

import DepictioRose from '../../../../components/rose/DepictioRose';
import BrandLogo from '../../../BrandLogo';
import PoweredBy from '../../../PoweredBy';
import { useBrandLogoMode } from '../../../useBrandLogoMode';
import { useColorScheme } from '../../../../hooks/useColorScheme';
import { STROKE } from './GlassPage';
import './auth.css';

/* ------------------------------------------------------------------ card */

export interface GlassAuthCardProps {
  title: string;
  lede?: React.ReactNode;
  /** A footer row under a hairline (switch between sign in and register). */
  foot?: React.ReactNode;
  children: React.ReactNode;
}

/** The brand: the real depictio logo, or the instance's own logo with the
 *  depictio credit under it. */
const AuthBrand: React.FC = () => {
  const mode = useBrandLogoMode();
  if (mode === 'none') return null;
  if (mode === 'custom') {
    return (
      <div className="gp-auth-brand gp-auth-brand--custom">
        <BrandLogo height={96} />
        <PoweredBy />
      </div>
    );
  }
  return (
    <div className="gp-auth-brand">
      <BrandLogo height={72} width="auto" live />
    </div>
  );
};

export const GlassAuthCard: React.FC<GlassAuthCardProps> = ({ title, lede, foot, children }) => (
  <section className="gp-auth-card" data-testid="modal-content" aria-labelledby="gp-auth-title">
    <AuthBrand />
    <header className="gp-auth-head">
      <h1 id="gp-auth-title" className="gp-auth-title">
        {title}
      </h1>
      {lede && <p className="gp-auth-lede">{lede}</p>}
    </header>
    <div className="gp-auth-body">{children}</div>
    {foot && <footer className="gp-auth-foot">{foot}</footer>}
  </section>
);

/** Waiting: the rose turning, one line of what is happening. */
export const GlassAuthWait: React.FC<{ text: string }> = ({ text }) => (
  <div className="gp-auth-wait" role="status">
    <DepictioRose mode="loading" size={44} label="" />
    <span>{text}</span>
  </div>
);

/** The page's theme switch, top right. No tooltip: the page sits above
 *  Mantine's portal layer, so the label is the button's own. */
export const AuthThemeKey: React.FC = () => {
  const { colorScheme, toggle } = useColorScheme();
  const dark = colorScheme === 'dark';
  const label = dark ? 'Switch to light theme' : 'Switch to dark theme';
  const I = dark ? Sun : Moon;
  return (
    <button type="button" className="gp-auth-theme" aria-label={label} title={label} onClick={toggle} data-testid="theme-toggle">
      <I size={18} strokeWidth={STROKE} aria-hidden />
    </button>
  );
};

/* ------------------------------------------------------------ background */

/** The rose's own hues: the instance's three brand roles first, then the
 *  petals the logo adds. */
const HUES = [
  'var(--depictio-brand-primary)',
  'var(--mantine-color-violet-5)',
  'var(--depictio-brand-secondary)',
  'var(--mantine-color-pink-5)',
  'var(--depictio-brand-tertiary)',
  'var(--mantine-color-blue-5)',
  'var(--mantine-color-green-5)',
  'var(--mantine-color-grape-5)',
];

const COUNT = 26;
const W = 1600;
const H = 1000;
const GOLDEN = 137.508;

/** A deterministic 0..1 from an index, so the field is the same on every
 *  load (and in screenshots). */
function hash(i: number, salt: number): number {
  const x = Math.sin(i * 12.9898 + salt * 78.233) * 43758.5453;
  return x - Math.floor(x);
}

interface Petal {
  x: number;
  y: number;
  size: number;
  rot: number;
  hue: string;
  outline: boolean;
  /** Swing on each axis (px) and its half period (s). */
  ax: number;
  ay: number;
  tx: number;
  ty: number;
  /** Tilt each way (deg), carried by the vertical swing. */
  spin: number;
  delay: number;
  enter: number;
}

function petals(): Petal[] {
  const cx = W / 2;
  const cy = H / 2;
  const out: Petal[] = [];
  for (let i = 0; i < COUNT; i++) {
    const a = ((i * GOLDEN) % 360) * (Math.PI / 180);
    // Out past the card (an ellipse around the centre), thinning towards the
    // edges.
    const t = 0.15 + 0.85 * Math.sqrt(hash(i, 1));
    const rx = 330 + t * 470;
    const ry = 330 + t * 190;
    const x = cx + Math.cos(a) * rx;
    const y = cy + Math.sin(a) * ry;
    const size = 12 + Math.round(hash(i, 2) * 26);

    out.push({
      x,
      y,
      size,
      // Each petal points away from the card, as if shed by the rose.
      rot: (a * 180) / Math.PI + 90 + (hash(i, 4) - 0.5) * 40,
      hue: HUES[i % HUES.length],
      outline: i % 3 === 1,
      // Two slow swings, one per axis and each at its own pace: together they
      // trace a smooth, never-repeating float with no stops.
      ax: 14 + hash(i, 3) * 18,
      ay: 14 + hash(i, 8) * 18,
      tx: 6 + hash(i, 6) * 5,
      ty: 7.5 + hash(i, 9) * 5,
      spin: 4 + hash(i, 5) * 8,
      delay: -hash(i, 7) * 12,
      enter: 120 + i * 28,
    });
  }
  return out;
}

/** The logo's petal: a tall triangle with a softened base. */
function petalPath(s: number): string {
  const h = s;
  const w = s * 0.82;
  return `M0 ${-h / 2} L${w / 2} ${h / 2 - h * 0.06} Q0 ${h / 2 + h * 0.04} ${-w / 2} ${h / 2 - h * 0.06} Z`;
}

export const GlassAuthBackground: React.FC = () => {
  const reduce = useReducedMotion();
  const field = React.useMemo(petals, []);
  return (
    <div className="gp-auth-bg" aria-hidden data-motion={reduce ? 'off' : 'on'}>
      <svg className="gp-auth-field" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid slice">
        {field.map((p, i) => (
          <g key={i} transform={`translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`}>
            <g
              className="gp-petal-enter"
              style={{ animationDelay: `${p.enter}ms` } as React.CSSProperties}
            >
              <g
                className="gp-petal-x"
                style={
                  {
                    '--ax': `${p.ax.toFixed(1)}px`,
                    animationDuration: `${p.tx.toFixed(2)}s`,
                    animationDelay: `${p.delay.toFixed(2)}s`,
                  } as React.CSSProperties
                }
              >
                <g
                  className="gp-petal-y"
                  style={
                    {
                      '--ay': `${p.ay.toFixed(1)}px`,
                      '--spin': `${p.spin.toFixed(1)}deg`,
                      animationDuration: `${p.ty.toFixed(2)}s`,
                      animationDelay: `${(p.delay * 0.7).toFixed(2)}s`,
                    } as React.CSSProperties
                  }
                >
                  <path
                    d={petalPath(p.size)}
                    transform={`rotate(${p.rot.toFixed(1)})`}
                    className={p.outline ? 'gp-petal-line' : 'gp-petal-fill'}
                    style={{ ['--hue' as string]: p.hue } as React.CSSProperties}
                  />
                </g>
              </g>
            </g>
          </g>
        ))}
      </svg>
    </div>
  );
};
