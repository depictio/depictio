/**
 * Build-time (Node) collector of the depictio Python that builds a UI-mode
 * figure, shipped into Tool Studio's Pyodide engine so a figure preview is the
 * figure depictio serves, not a lookalike. Same approach as the serverless
 * bundle (depictio/serverless/pyodide/modules.py): the server's own files,
 * copied, never a second implementation.
 *
 *   verbatim     figure_builder.py (create_figure_from_data), aggregate.py (the
 *                scan-level fast path for box/histogram/bar/density),
 *                style_presets.py (apply_figure_style, figure_style_payload),
 *                the mantine templates (services/figure/mantine_templates.py,
 *                multiqc/themes.py, cli/cli/utils/mantine_templates.py),
 *                error_figure.py, heatmap.py, definitions.py + models.py +
 *                parameter_discovery.py (ALLOWED_VISUALIZATIONS),
 *                overview_style.py (the default figure look),
 *                models/models/branding.py (pydantic only), and the plot
 *                palette package models/palettes/ with its JSON source.
 *   extracted    `tidy_facet_layout` out of services/figure/groups.py, whose
 *                module imports deltatables_utils. Cut in the browser by the
 *                serverless bundler's own `extract()` (modules.py, shipped
 *                verbatim), so the rule that refuses a depictio import the
 *                bundle does not ship is the bundle's rule.
 *   stubbed      the three server-only modules the figure path reaches:
 *                - configs/logging_init.py → a `logging.getLogger` (the stub
 *                  the serverless bundle uses);
 *                - configs/config.py → `settings.performance` with the
 *                  PerformanceConfig defaults read out of settings_models.py
 *                  (figure_max_points, box_sample_*), and `settings.branding`
 *                  a stock deployment's (no branding);
 *                - services/branding.py → `resolve_effective_brand_theme()` of
 *                  a stock deployment: `resolve_brand_theme(BrandTheme())`,
 *                  which leaves the mantine templates as the CLI module builds
 *                  them (what an unbranded depictio instance serves).
 *
 * The recipe modules (depictioModules.ts) are loaded first and provide
 * depictio.recipes.lib.contigs, which aggregate.py imports. Every
 * `from depictio… import` in a shipped file must resolve to a shipped or
 * stubbed module, or be listed in UNREACHED, or the collection throws — so a
 * server change that drags a new dependency into the figure path fails the
 * build (and the tests) instead of the preview.
 */
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const FIG = 'depictio/api/v1/services/figure';

/** Whole server files shipped as they are, relative to the repo root. */
const VERBATIM = [
  `${FIG}/figure_builder.py`,
  `${FIG}/aggregate.py`,
  `${FIG}/error_figure.py`,
  `${FIG}/heatmap.py`,
  `${FIG}/mantine_templates.py`,
  `${FIG}/definitions.py`,
  `${FIG}/models.py`,
  `${FIG}/parameter_discovery.py`,
  `${FIG}/style_presets.py`,
  `${FIG}/overview_style.py`,
  'depictio/api/v1/services/multiqc/themes.py',
  'depictio/cli/cli/utils/mantine_templates.py',
  'depictio/models/models/branding.py',
  // The shared plot palette (colours, CVD helpers, UI hues) and its JSON source,
  // read by palettes/__init__.py through importlib.resources.
  'depictio/models/palettes/__init__.py',
  'depictio/models/palettes/cvd.py',
  'depictio/models/palettes/ui_hues.py',
  'depictio/models/palettes/depictio_palettes.json',
  // The serverless bundler's extractor, run inside Pyodide on EXTRACT below.
  'depictio/serverless/pyodide/modules.py',
];

/** Server files the engine cuts single functions out of (with modules.extract).
 *  Shipped as data under SOURCE_DIR, outside the import path. */
export const EXTRACT: Record<string, { module: string; roots: string[] }> = {
  [`${FIG}/groups.py`]: { module: 'depictio.api.v1.services.figure.groups', roots: ['tidy_facet_layout'] },
};
export const SOURCE_DIR = 'depictio_studio_src';

const SETTINGS_MODELS = 'depictio/api/v1/configs/settings_models.py';
/** PerformanceConfig fields the shipped figure path reads. */
const PERFORMANCE_FIELDS = ['figure_max_points', 'box_sample_rows_per_group', 'box_sample_max_groups'];

/** depictio modules satisfied by a stub below. */
const STUBBED = [
  'depictio.api.v1.configs.logging_init',
  'depictio.api.v1.configs.config',
  'depictio.api.v1.services.branding',
];
/** Modules provided by the recipe set (depictioModules.ts). */
const FROM_RECIPE_SET = ['depictio.recipes.lib.contigs'];
/** Lazy imports on paths a UI-mode preview never takes (code mode). */
const UNREACHED = ['depictio.api.v1.services.figure.code_executor', 'depictio.api.v1.services.figure.code_mode'];

const LOGGER_STUB = `"""Stub of depictio.api.v1.configs.logging_init for Tool Studio's figure engine
(the serverless bundle's stub)."""
import logging

logger = logging.getLogger("depictio.studio")
`;

const BRANDING_STUB = `"""Stub of depictio.api.v1.services.branding for Tool Studio's figure engine.

The server merges env defaults, admin overrides (Mongo) and the dashboard's own
theme. A catalog render is previewed as a stock, unbranded deployment draws
it: an empty BrandTheme, which leaves the mantine templates untouched."""
from depictio.models.models.branding import BrandTheme, resolve_brand_theme


def resolve_effective_brand_theme(use_cache: bool = True) -> BrandTheme:
    return resolve_brand_theme(BrandTheme())
`;

function settingsStub(defaults: Record<string, string>): string {
  const perf = Object.entries(defaults)
    .map(([k, v]) => `    ${k} = ${v}`)
    .join('\n');
  return `"""Stub of depictio.api.v1.configs.config for Tool Studio's figure engine.

Only what the shipped figure path reads: the PerformanceConfig defaults (read
out of ${SETTINGS_MODELS} at build time) and a stock deployment's branding."""
from depictio.models.models.branding import BrandTheme


class _Performance:
${perf}


class _Branding:
    @staticmethod
    def as_brand_theme() -> BrandTheme:
        return BrandTheme()


class _Settings:
    performance = _Performance()
    branding = _Branding()


settings = _Settings()
`;
}

/** `default=` of each PerformanceConfig field, as Python literals. */
export function performanceDefaults(source: string): Record<string, string> {
  const start = source.indexOf('class PerformanceConfig(');
  if (start < 0) throw new Error(`${SETTINGS_MODELS} defines no PerformanceConfig`);
  const next = source.slice(start + 1).search(/\nclass \w+/);
  const body = next < 0 ? source.slice(start) : source.slice(start, start + 1 + next);
  const out: Record<string, string> = {};
  for (const field of PERFORMANCE_FIELDS) {
    const m = new RegExp(`\\n    ${field}: int = Field\\(\\s*default=([0-9_]+)`).exec(body);
    if (!m) throw new Error(`PerformanceConfig.${field} has no int literal default; extend figureModules.ts`);
    out[field] = m[1];
  }
  return out;
}

function moduleOf(path: string): string {
  return path.replace(/\.py$/, '').replace(/\/__init__$/, '').split('/').join('.');
}

/** Every `from depictio.x import` / `import depictio.x` in a source. */
function depictioImports(source: string): string[] {
  const names = new Set<string>();
  for (const m of source.matchAll(/^\s*from (depictio[\w.]*) import/gm)) names.add(m[1]);
  for (const m of source.matchAll(/^\s*import (depictio[\w.]*)/gm)) names.add(m[1]);
  return [...names];
}

/** `{path in the Pyodide FS: source}`, or null when the depictio tree is absent. */
export function collectFigureModules(repoRoot: string): Record<string, string> | null {
  const at = (rel: string) => resolve(repoRoot, rel);
  if (!existsSync(at(`${FIG}/figure_builder.py`)) || !existsSync(at(SETTINGS_MODELS))) return null;
  const files: Record<string, string> = {};
  for (const rel of VERBATIM) files[rel] = readFileSync(at(rel), 'utf8');
  files['depictio/api/v1/configs/logging_init.py'] = LOGGER_STUB;
  files['depictio/api/v1/services/branding.py'] = BRANDING_STUB;
  files['depictio/api/v1/configs/config.py'] = settingsStub(performanceDefaults(readFileSync(at(SETTINGS_MODELS), 'utf8')));
  for (const rel of Object.keys(EXTRACT)) files[`${SOURCE_DIR}/${rel}`] = readFileSync(at(rel), 'utf8');

  // Every depictio import of a shipped file must land somewhere.
  const shipped = new Set(Object.keys(files).map(moduleOf));
  const known = new Set([...shipped, ...STUBBED, ...FROM_RECIPE_SET, ...UNREACHED]);
  for (const rel of VERBATIM) {
    for (const name of depictioImports(files[rel])) {
      // `from depictio.models import palettes` names the package, whose shipped
      // submodule is what the import resolves to.
      const isPackage = [...shipped].some((m) => m.startsWith(`${name}.`));
      if (!known.has(name) && !isPackage) {
        throw new Error(`${rel} imports ${name}, which Tool Studio's figure engine does not ship (figureModules.ts)`);
      }
    }
  }

  for (const path of Object.keys(files)) {
    if (path.startsWith(`${SOURCE_DIR}/`)) continue;
    const parts = path.split('/').slice(0, -1);
    for (let i = 1; i <= parts.length; i++) {
      const init = `${parts.slice(0, i).join('/')}/__init__.py`;
      if (!(init in files)) files[init] = '';
    }
  }
  return Object.fromEntries(Object.entries(files).sort(([a], [b]) => a.localeCompare(b)));
}
