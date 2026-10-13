/**
 * Build-time generator for the drift-sensitive inputs Tool Studio reads:
 *
 *   public/kinds.json           ← `dev catalog kinds --json` (advanced_viz roles)
 *   public/figureParams.json    ← `dev catalog figure-params --json` (figure builder UI)
 *   public/catalog.json         ← `dev catalog manifest --json` (existing tools/renders)
 *   public/catalog.schema.json  ← copy of depictio/catalog/catalog.schema.json
 *   src/catalog/generated/cardSpec.ts ← card layouts/fields, derived from that schema
 *   src/test/generated/cardMetricsGolden.json ← the real card_metrics /
 *       card_breakdown output for e2e/golden/card_metrics.csv, which pins the
 *       TypeScript port in src/api/cardMetrics.ts to the server's numbers
 *
 * All are also committed as snapshots. This script REGENERATES them from the
 * in-repo Python source when a depictio-capable Python is reachable (CI, dev
 * machines), and otherwise leaves the committed snapshots untouched so a
 * pure-JS `pnpm build` (e.g. the GitHub Pages runner without Python) still
 * works. A separate CI "drift" job regenerates and `git diff --exit-code`s to
 * keep the snapshots honest.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, copyFileSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, '..');
const repoRoot = resolve(pkgRoot, '..', '..'); // packages/tool-studio → repo root
const publicDir = resolve(pkgRoot, 'public');
const schemaSrc = resolve(repoRoot, 'depictio', 'catalog', 'catalog.schema.json');
const schemaDst = resolve(publicDir, 'catalog.schema.json');

mkdirSync(publicDir, { recursive: true });

/** Copy an in-repo file into public/, keeping the committed snapshot when the
 *  source is missing (a Python-free build) unless STRICT_GEN demands the real
 *  thing. Used for the plain-file inputs — the JSON snapshots below come from
 *  CLI commands instead. */
function copySnapshot(src: string, dst: string, label: string): void {
  if (existsSync(src)) {
    copyFileSync(src, dst);
    console.log(`[genKinds] copied ${label}`);
  } else if (existsSync(dst) && !process.env.TOOL_STUDIO_STRICT_GEN) {
    console.log(`[genKinds] ${label} source absent, keeping committed snapshot`);
  } else {
    console.warn(`[genKinds] WARNING: no ${label} source or snapshot`);
  }
}

// 1. Schema + the MultiQC advisory index: straight copies from the in-repo
//    sources of truth. The MultiQC list is what the Tool step warns against
//    (`catalog refresh-index` regenerates it from the MultiQC repo).
copySnapshot(schemaSrc, schemaDst, 'catalog.schema.json');
copySnapshot(
  resolve(repoRoot, 'depictio', 'catalog', '_index', 'multiqc_modules.txt'),
  resolve(publicDir, 'multiqc_modules.txt'),
  'multiqc_modules.txt',
);

// 2. JSON snapshots from CLI commands. Try the installed `depictio` binary
//    first, then a Python invocation of the isolated Typer sub-app. Any success
//    overwrites the snapshot; total failure leaves the committed one in place.
function pyInvoke(command: string): string[] {
  return [
    '-c',
    [
      'import sys',
      'from typer.testing import CliRunner',
      'from depictio.cli.cli.commands.catalog import dev_app',
      `r = CliRunner().invoke(dev_app, ['${command}', '--json'])`,
      'sys.exit(r.exit_code) if r.exit_code else sys.stdout.write(r.stdout)',
    ].join('; '),
  ];
}

/** Run `dev catalog <command> --json`, returning the JSON text or null. */
function tryGen(command: string): string | null {
  const attempts: Array<{ cmd: string; args: string[] }> = [
    { cmd: 'depictio', args: ['dev', 'catalog', command, '--json'] },
    { cmd: 'python', args: pyInvoke(command) },
    { cmd: 'python3', args: pyInvoke(command) },
  ];
  for (const { cmd, args } of attempts) {
    try {
      const out = execFileSync(cmd, args, {
        cwd: repoRoot,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
        // execFileSync buffers stdout and its default cap is 1 MB. The catalog
        // manifest passed that as the catalog grew (it embeds each output's raw
        // YAML and a sample of its fixture), and the overflow surfaces as an
        // ENOBUFS the catch below swallows, so the build failed with "could not
        // regenerate" and no reason. Give it room the manifest cannot plausibly
        // reach.
        maxBuffer: 128 * 1024 * 1024,
      });
      const trimmed = out.trim();
      if (trimmed.startsWith('{')) {
        JSON.parse(trimmed); // validate
        return trimmed + '\n';
      }
    } catch {
      // try next candidate
    }
  }
  return null;
}

/** In CI the drift check is only meaningful if regeneration actually happened:
 *  falling back to the committed snapshot would make `git diff --exit-code`
 *  pass for the wrong reason. Locally (and on the Python-less Pages runner) the
 *  fallback is the intended behaviour. */
const STRICT = process.env.TOOL_STUDIO_STRICT_GEN === '1';

/** Regenerate one snapshot; keep the committed copy when Python is unavailable. */
function snapshot(command: string, filename: string): void {
  const dst = resolve(publicDir, filename);
  const generated = tryGen(command);
  if (generated) {
    writeFileSync(dst, generated);
    console.log(`[genKinds] regenerated ${filename} from source`);
    return;
  }
  if (STRICT) {
    console.error(
      `[genKinds] ERROR: could not regenerate ${filename} from source ` +
        `(TOOL_STUDIO_STRICT_GEN=1). Check that \`depictio dev catalog ${command} --json\` ` +
        `runs and prints JSON on stdout with nothing in front of it.`,
    );
    process.exit(1);
  }
  if (existsSync(dst)) {
    console.log(`[genKinds] Python/depictio unavailable — keeping committed ${filename}`);
  } else {
    console.error(`[genKinds] ERROR: cannot generate ${filename} and no snapshot exists`);
    process.exit(1);
  }
}

snapshot('kinds', 'kinds.json');
snapshot('figure-params', 'figureParams.json');
snapshot('manifest', 'catalog.json');

// 2b. The card-metrics golden. Not a CLI command: `card_metrics` and
//     `card_breakdown` are pure-polars service modules, so the script imports
//     them directly and prints their output for the committed fixture. The
//     browser port has to reproduce it exactly (src/test/cardMetrics.test.ts).
function cardMetricsGolden(): void {
  const script = resolve(here, 'card_metrics_golden.py');
  const dst = resolve(pkgRoot, 'src', 'test', 'generated', 'cardMetricsGolden.json');
  for (const cmd of ['python', 'python3']) {
    try {
      const out = execFileSync(cmd, [script], {
        cwd: repoRoot,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      });
      const trimmed = out.trim();
      if (trimmed.startsWith('{')) {
        JSON.parse(trimmed); // validate
        mkdirSync(dirname(dst), { recursive: true });
        writeFileSync(dst, trimmed + '\n');
        console.log('[genKinds] regenerated cardMetricsGolden.json from card_metrics.py');
        return;
      }
    } catch {
      // try next candidate
    }
  }
  if (STRICT) {
    console.error(
      '[genKinds] ERROR: could not regenerate cardMetricsGolden.json ' +
        '(TOOL_STUDIO_STRICT_GEN=1). Check that `python scripts/card_metrics_golden.py` ' +
        'runs from the repo root and prints JSON.',
    );
    process.exit(1);
  }
  if (existsSync(dst)) {
    console.log('[genKinds] Python/depictio unavailable — keeping committed cardMetricsGolden.json');
  } else {
    console.error('[genKinds] ERROR: cannot generate cardMetricsGolden.json and no snapshot exists');
    process.exit(1);
  }
}

cardMetricsGolden();

// 3. Card spec: the enums the exporter must stay in step with, derived from the
//    schema we just copied. They live in TS (not JSON) so a layout added on the
//    depictio side becomes a *compile* error in `cardRules.ts`'s exhaustive
//    Record rather than a silently-dropped field in the generated YAML.
function enumOf(prop: Record<string, unknown> | undefined, what: string): string[] {
  const branches = (prop?.anyOf as Array<Record<string, unknown>> | undefined) ?? [prop ?? {}];
  for (const branch of branches) {
    if (Array.isArray(branch?.enum)) return branch.enum as string[];
  }
  throw new Error(`[genKinds] no enum found for ${what} in catalog.schema.json`);
}

const schema = JSON.parse(readFileSync(schemaDst, 'utf8')) as {
  $defs: { Render: { properties: Record<string, Record<string, unknown>> } };
};
const renderProps = schema.$defs.Render.properties;

const asList = (values: string[]) => values.map((v) => `  '${v}',`).join('\n');
const cardSpec = `/**
 * GENERATED by scripts/genKinds.ts from depictio/catalog/catalog.schema.json.
 * Do not edit by hand — run \`pnpm --filter tool-studio genkinds\`.
 *
 * These enums used to be hand-copied into src/types.ts and drifted behind
 * depictio (a card layout added upstream was silently unexportable). Deriving
 * them here means the CI drift check catches the divergence, and the exhaustive
 * Record in src/catalog/cardRules.ts turns a new layout into a compile error.
 */

export const SECONDARY_LAYOUTS = [
${asList(enumOf(renderProps.secondary_layout, 'secondary_layout'))}
] as const;
export type SecondaryLayout = (typeof SECONDARY_LAYOUTS)[number];

export const AGGREGATIONS = [
${asList(enumOf(renderProps.aggregation, 'aggregation'))}
] as const;
export type Aggregation = (typeof AGGREGATIONS)[number];

export const THRESHOLD_DIRECTIONS = [
${asList(enumOf(renderProps.threshold_direction, 'threshold_direction'))}
] as const;
export type ThresholdDirection = (typeof THRESHOLD_DIRECTIONS)[number];
`;

const cardSpecDst = resolve(pkgRoot, 'src', 'catalog', 'generated', 'cardSpec.ts');
mkdirSync(dirname(cardSpecDst), { recursive: true });
writeFileSync(cardSpecDst, cardSpec);
console.log('[genKinds] regenerated src/catalog/generated/cardSpec.ts from the schema');
