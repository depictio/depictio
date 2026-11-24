// @vitest-environment node
/**
 * The figure modules Tool Studio ships into Pyodide (src/pyodide/figureModules.ts):
 * server files verbatim, the settings stub's defaults read from the real
 * PerformanceConfig, and every depictio import accounted for.
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { collectFigureModules, performanceDefaults } from '../pyodide/figureModules';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');
const files = collectFigureModules(repoRoot);

describe.skipIf(!files)('figure modules', () => {
  it('ships create_figure_from_data and its neighbours verbatim', () => {
    for (const rel of [
      'depictio/api/v1/services/figure/figure_builder.py',
      'depictio/api/v1/services/figure/aggregate.py',
      'depictio/api/v1/services/figure/style_presets.py',
      'depictio/cli/cli/utils/mantine_templates.py',
      'depictio/serverless/pyodide/modules.py',
      'depictio/api/v1/services/figure/overview_style.py',
      'depictio/models/palettes/__init__.py',
      'depictio/models/palettes/depictio_palettes.json',
    ]) {
      expect(files![rel]).toBe(readFileSync(resolve(repoRoot, rel), 'utf8'));
    }
    // groups.py is data for the bundler's extract(), outside the import path.
    expect(files!['depictio_studio_src/depictio/api/v1/services/figure/groups.py']).toContain('def tidy_facet_layout');
    expect(files!['depictio/api/v1/services/figure/groups.py']).toBeUndefined();
    // Never the recipes package init, which the recipe set ships with content.
    expect(files!['depictio/recipes/__init__.py']).toBeUndefined();
  });

  it('stubs settings with the real PerformanceConfig defaults', () => {
    const source = readFileSync(resolve(repoRoot, 'depictio/api/v1/configs/settings_models.py'), 'utf8');
    const defaults = performanceDefaults(source);
    expect(Object.keys(defaults).sort()).toEqual(['box_sample_max_groups', 'box_sample_rows_per_group', 'figure_max_points']);
    for (const [k, v] of Object.entries(defaults)) {
      expect(files!['depictio/api/v1/configs/config.py']).toContain(`    ${k} = ${v}`);
    }
  });

  it('refuses a PerformanceConfig without a literal default', () => {
    expect(() => performanceDefaults('class PerformanceConfig(BaseSettings):\n    pass\n')).toThrow(/figure_max_points/);
  });
});
