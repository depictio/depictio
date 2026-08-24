/**
 * Build-time generator for the drift-sensitive inputs Catalog Studio reads:
 *
 *   public/kinds.json           ← `dev catalog kinds --json` (advanced_viz roles)
 *   public/figureParams.json    ← `dev catalog figure-params --json` (figure builder UI)
 *   public/catalog.json         ← `dev catalog manifest --json` (existing tools/renders)
 *   public/catalog.schema.json  ← copy of depictio/catalog/catalog.schema.json
 *   src/catalog/generated/cardSpec.ts ← card layouts/fields, derived from that schema
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
const repoRoot = resolve(pkgRoot, '..', '..'); // packages/catalog-studio → repo root
const publicDir = resolve(pkgRoot, 'public');
const schemaSrc = resolve(repoRoot, 'depictio', 'catalog', 'catalog.schema.json');
const schemaDst = resolve(publicDir, 'catalog.schema.json');

mkdirSync(publicDir, { recursive: true });

// 1. Schema: straight copy from the in-repo source of truth.
if (existsSync(schemaSrc)) {
  copyFileSync(schemaSrc, schemaDst);
  console.log(`[genKinds] copied catalog.schema.json`);
} else if (existsSync(schemaDst) && !process.env.CATALOG_STUDIO_STRICT_GEN) {
  console.log(`[genKinds] schema source absent — keeping committed snapshot`);
} else {
  console.warn(`[genKinds] WARNING: no catalog.schema.json source or snapshot`);
}

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
const STRICT = process.env.CATALOG_STUDIO_STRICT_GEN === '1';

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
        `(CATALOG_STUDIO_STRICT_GEN=1). Check that \`depictio dev catalog ${command} --json\` ` +
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
 * Do not edit by hand — run \`pnpm --filter catalog-studio genkinds\`.
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
