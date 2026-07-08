/**
 * Build-time generator for the drift-sensitive inputs Catalog Studio reads:
 *
 *   public/kinds.json           ← `dev catalog kinds --json` (advanced_viz roles)
 *   public/figureParams.json    ← `dev catalog figure-params --json` (figure builder UI)
 *   public/catalog.schema.json  ← copy of depictio/catalog/catalog.schema.json
 *
 * All are also committed as snapshots. This script REGENERATES them from the
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

/** Regenerate one snapshot; keep the committed copy when Python is unavailable. */
function snapshot(command: string, filename: string): void {
  const dst = resolve(publicDir, filename);
  const generated = tryGen(command);
  if (generated) {
    writeFileSync(dst, generated);
    console.log(`[genKinds] regenerated ${filename} from source`);
  } else if (existsSync(dst)) {
    console.log(`[genKinds] Python/depictio unavailable — keeping committed ${filename}`);
  } else {
    console.error(`[genKinds] ERROR: cannot generate ${filename} and no snapshot exists`);
    process.exit(1);
  }
}

snapshot('kinds', 'kinds.json');
snapshot('figure-params', 'figureParams.json');
