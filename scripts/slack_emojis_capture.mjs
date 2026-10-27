#!/usr/bin/env node
/* Capture the frames of the depictio rose animations for the Slack emoji pack.
 *
 * Called by scripts/generate_slack_emojis.py, which assembles the GIFs:
 *
 *     node scripts/slack_emojis_capture.mjs <jobs.json> <out-dir>
 *
 * The frames come from the real animation code, depictio-rose.js (the same file the
 * viewer's <DepictioRose> uses), played in Chromium with every Web Animation paused
 * and seeked frame by frame: the emojis move exactly as the app's mark does.
 *
 * A job is { name, mode, kind, speed, hold, bounce, fps, loops, px }:
 *   kind "still"  one frame of the logo shape.
 *   kind "loop"   one period of a mode that loops forever (loading, sweep, fan...),
 *                 taken once every wedge is in its steady loop, so the GIF is seamless.
 *   kind "story"  a mode that opens once then loops (pulse, live, wave): the opening,
 *                 `loops` periods, then the wedges ease back to the closed disc the
 *                 opening starts from, so this GIF loops seamlessly too.
 * Writes <out-dir>/<name>/NNNN.png (transparent) and <out-dir>/<name>/frames.json.
 */
import { createRequire } from 'node:module';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const roseJs = readFileSync(join(root, 'depictio/viewer/src/components/rose/depictio-rose.js'), 'utf8');

// Playwright from the e2e suite's install when there is one, else wherever node finds it.
function loadPlaywright() {
  for (const base of [join(root, 'depictio/tests/e2e-playwright/package.json'), import.meta.url]) {
    try { return createRequire(base)('playwright'); } catch { /* next */ }
  }
  throw new Error('playwright not found: run `npm ci` in depictio/tests/e2e-playwright');
}

const BOUNCE = { soft: 0.7, medium: 0.5, strong: 0.35 };

const [jobsPath, outDir] = process.argv.slice(2);
const jobs = JSON.parse(readFileSync(jobsPath, 'utf8'));
const { chromium } = loadPlaywright();
const browser = await chromium.launch();
const page = await browser.newPage();

for (const job of jobs) {
  const px = job.px ?? 512;
  await page.setViewportSize({ width: px, height: px });
  await page.setContent(
    `<style>html,body{margin:0;background:transparent}svg{width:${px}px;height:${px}px;display:block}</style>` +
    '<svg id="rose"></svg>');
  await page.addScriptTag({ content: roseJs });

  const plan = await page.evaluate(({ mode, kind, opts }) => {
    const R = window.DepictioRose;
    const svg = document.getElementById('rose');
    window.wedges = R.build(svg, 'r');
    if (kind === 'still') return { start: 0, end: 0, period: 0 };
    R.play(window.wedges, mode, opts);
    window.anims = document.getAnimations();
    window.anims.forEach(a => a.pause());
    let period = 0, steady = 0, onceEnd = 0;
    for (const a of window.anims) {
      const t = a.effect.getComputedTiming();
      if (t.iterations === Infinity) {
        period = Math.max(period, t.duration);
        steady = Math.max(steady, t.delay);
      } else {
        onceEnd = Math.max(onceEnd, t.delay + t.duration * t.iterations);
      }
    }
    steady = Math.max(steady, onceEnd);
    window.seek = ms => window.anims.forEach(a => { a.currentTime = ms; });
    return { steady: steady / 1000, period: period / 1000 };
  }, {
    mode: job.mode,
    kind: job.kind,
    opts: { speed: job.speed ?? 1, hold: job.hold ?? 1.2, zeta: BOUNCE[job.bounce ?? 'strong'], disc: 0.62 },
  });

  const dir = join(outDir, job.name);
  mkdirSync(dir, { recursive: true });
  const el = page.locator('#rose');
  const shots = [];
  const shoot = async () => {
    const path = join(dir, String(shots.length).padStart(4, '0') + '.png');
    await el.screenshot({ path, omitBackground: true });
    shots.push(path);
  };

  const step = 1 / (job.fps ?? 20);
  if (job.kind === 'still') {
    await shoot();
  } else {
    const start = job.kind === 'loop' ? plan.steady : 0;
    const end = job.kind === 'loop' ? plan.steady + plan.period : plan.steady + (job.loops ?? 1) * plan.period;
    for (let t = start; t < end - 1e-6; t += step) {
      await page.evaluate(ms => window.seek(ms), t * 1000);
      await shoot();
    }
    if (job.kind === 'story') {
      // Back to the closed disc: the wedges' current scale, eased down clockwise.
      const close = 0.6 / (job.speed ?? 1), hold = 0.25;
      await page.evaluate(() => {
        window.from = window.wedges.map(w => {
          const m = /^matrix\(([^,]+)/.exec(getComputedStyle(w).transform);
          return m ? parseFloat(m[1]) : 1;
        });
        window.anims.forEach(a => a.cancel());
      });
      for (let t = 0; t < close + hold - 1e-6; t += step) {
        await page.evaluate(({ t, close }) => {
          const ease = u => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
          window.wedges.forEach((w, i) => {
            const u = Math.min(1, Math.max(0, (t - i * close * 0.04) / (close * 0.72)));
            const s = window.from[i] + (0.62 - window.from[i]) * ease(u);
            w.style.transform = `scale(${s.toFixed(4)})`;
          });
        }, { t, close });
        await shoot();
      }
    }
  }
  writeFileSync(join(dir, 'frames.json'), JSON.stringify({ frames: shots, frame_ms: Math.round(step * 1000) }));
  console.log(`${job.name}: ${shots.length} frames`);
}

await browser.close();
