import { useMemo } from 'react';

const TRIANGLE_COLORS = [
  '#8B5CF6', '#A855F7', '#3B82F6', '#14B8A6',
  '#10B981', '#F59E0B', '#F97316', '#EC4899', '#EF4444',
];

const TRIANGLE_SIZES = [
  { key: 'small',  weight: 0.35, w: 12, h: 12 },
  { key: 'medium', weight: 0.30, w: 18, h: 18 },
  { key: 'large',  weight: 0.25, w: 24, h: 24 },
  { key: 'xlarge', weight: 0.10, w: 32, h: 32 },
] as const;

const ANIM_CLASSES = [
  'triangle-anim-1', 'triangle-anim-2', 'triangle-anim-3',
  'triangle-anim-4', 'triangle-anim-5', 'triangle-anim-6',
];

function selectSize(index: number): (typeof TRIANGLE_SIZES)[number] {
  const r = (index * 0.37) % 1;
  let cum = 0;
  for (const s of TRIANGLE_SIZES) {
    cum += s.weight;
    if (r <= cum) return s;
  }
  return TRIANGLE_SIZES[0];
}

// Mirrors users_management.py:_calculate_particle_position so the layout matches
// the prior Dash implementation pixel-for-pixel.
function particlePosition(index: number, cols: number, rows: number): [number, number] {
  const cellW = 85 / cols;
  const cellH = 70 / rows;
  const cellX = index % cols;
  const cellY = Math.floor(index / cols) % rows;
  const baseX = cellX * cellW + cellW / 2;
  const baseY = cellY * cellH + cellH / 2;
  const offX = (((index * 37 + index * index * 13) % 100) - 50) / 100 * cellW * 0.8;
  const offY = (((index * 41 + index * index * 19) % 100) - 50) / 100 * cellH * 0.8;
  const x = Math.max(5, Math.min(90, baseX + offX + 7.5));
  const y = Math.max(10, Math.min(80, baseY + offY + 15));
  return [x, y];
}

function triangleSvgUrl(w: number, h: number, color: string): string {
  const path = `M${w / 2} ${h * 0.05} L${w * 0.8} ${h * 0.9} Q${w / 2} ${h * 0.95} ${w * 0.2} ${h * 0.9} Z`;
  const enc = color.replace('#', '%23');
  const svg = `<svg width='${w}' height='${h}' viewBox='0 0 ${w} ${h}' xmlns='http://www.w3.org/2000/svg'><path d='${path}' fill='${enc}' /></svg>`;
  return `url("data:image/svg+xml,${svg}")`;
}

const NUM_PARTICLES = 40;
const GRID_COLS = 8;
const GRID_ROWS = 5;

interface Particle {
  left: string;
  top: string;
  background: string;
  transform: string;
  className: string;
  animationDelay: string;
  initialRotation: string;
}

export default function AuthBackground() {
  const particles = useMemo<Particle[]>(() => {
    const out: Particle[] = [];
    for (let i = 0; i < NUM_PARTICLES; i++) {
      const size = selectSize(i);
      const color = TRIANGLE_COLORS[i % TRIANGLE_COLORS.length];
      const cls = ANIM_CLASSES[i % ANIM_CLASSES.length];
      const [x, y] = particlePosition(i, GRID_COLS, GRID_ROWS);
      const rot = (i * 73) % 360;
      // Negative delay starts mid-cycle so motion is visible immediately.
      const delay = -((i * 1.7) % 8);
      out.push({
        left: `${x}%`,
        top: `${y}%`,
        background: triangleSvgUrl(size.w, size.h, color),
        transform: `rotate(${rot}deg) translateZ(0)`,
        className: `triangle-particle triangle-${size.key} ${cls}`,
        animationDelay: `${delay}s`,
        initialRotation: `${rot}deg`,
      });
    }
    return out;
  }, []);

  return (
    <div className="auth-background" aria-hidden>
      <div className="triangle-particles">
        {particles.map((p, i) => (
          <div
            key={i}
            className={p.className}
            style={
              {
                left: p.left,
                top: p.top,
                background: p.background,
                transform: p.transform,
                animationDelay: p.animationDelay,
                ['--initial-rotation' as string]: p.initialRotation,
              } as React.CSSProperties
            }
          />
        ))}
      </div>
    </div>
  );
}
