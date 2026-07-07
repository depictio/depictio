/**
 * Build-time generator for the two drift-sensitive inputs Catalog Studio reads:
 *
 *   public/kinds.json           ← `dev catalog kinds --json` (advanced_viz roles)
 *   public/catalog.schema.json  ← copy of depictio/catalog/catalog.schema.json
 *
 * Both are also committed as snapshots. This script REGENERATES them from the
 * in-repo Python source when a depictio-capable Python is reachable (CI, dev
 * machines), and otherwise leaves the committed snapshots untouched so a
 * pure-JS `pnpm build` (e.g. the GitHub Pages runner without Python) still
 * works. A separate CI "drift" job regenerates and `git diff --exit-code`s to
 * keep the snapshots honest.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, copyFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, '..');
const repoRoot = resolve(pkgRoot, '..', '..'); // packages/catalog-studio → repo root
const publicDir = resolve(pkgRoot, 'public');
const schemaSrc = resolve(repoRoot, 'depictio', 'catalog', 'catalog.schema.json');
const schemaDst = resolve(publicDir, 'catalog.schema.json');
const kindsDst = resolve(publicDir, 'kinds.json');

mkdirSync(publicDir, { recursive: true });

// 1. Schema: straight copy from the in-repo source of truth.
if (existsSync(schemaSrc)) {
  copyFileSync(schemaSrc, schemaDst);
  console.log(`[genKinds] copied catalog.schema.json`);
} else if (existsSync(schemaDst)) {
  console.log(`[genKinds] schema source absent — keeping committed snapshot`);
} else {
  console.warn(`[genKinds] WARNING: no catalog.schema.json source or snapshot`);
}

// 2. kinds.json: run the CLI command. Try the installed `depictio` binary
//    first, then a Python invocation of the isolated Typer sub-app (needs only
//    typer + pydantic, not the full CLI dep tree). Any success overwrites the
//    snapshot; total failure leaves it in place.
const PY_INVOKE = [
  '-c',
  [
    'import sys',
    'from typer.testing import CliRunner',
    'from depictio.cli.cli.commands.catalog import dev_app',
    "r = CliRunner().invoke(dev_app, ['kinds', '--json'])",
    'sys.exit(r.exit_code) if r.exit_code else sys.stdout.write(r.stdout)',
  ].join('; '),
];

function tryGen(): string | null {
  const attempts: Array<{ cmd: string; args: string[] }> = [
    { cmd: 'depictio', args: ['dev', 'catalog', 'kinds', '--json'] },
    { cmd: 'python', args: PY_INVOKE },
    { cmd: 'python3', args: PY_INVOKE },
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

const generated = tryGen();
if (generated) {
  writeFileSync(kindsDst, generated);
  console.log(`[genKinds] regenerated kinds.json from source`);
} else if (existsSync(kindsDst)) {
  console.log(`[genKinds] Python/depictio unavailable — keeping committed kinds.json`);
} else {
  console.error(`[genKinds] ERROR: cannot generate kinds.json and no snapshot exists`);
  process.exit(1);
}
