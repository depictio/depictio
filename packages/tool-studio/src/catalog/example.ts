/**
 * The example entry offered on the start screen: mosdepth's per-contig summary,
 * read from the committed catalog at build time (so it is always a valid,
 * current entry and needs no network). It shows every part a new author has to
 * produce: identity, a glob, a recipe, its fixture and three visualizations.
 */
import moduleYaml from '../../../../depictio/catalog/mosdepth/module.yaml?raw';
import outputYaml from '../../../../depictio/catalog/mosdepth/summary.yaml?raw';
import fixtureTsv from '../../../../depictio/catalog/mosdepth/summary.tsv?raw';
import recipePy from '../../../../depictio/catalog/mosdepth/summary.py?raw';

export const EXAMPLE_LABEL = 'mosdepth · per-contig coverage summary';

export const EXAMPLE_FILES: Record<string, string> = {
  'mosdepth/module.yaml': moduleYaml,
  'mosdepth/summary.yaml': outputYaml,
  'mosdepth/summary.tsv': fixtureTsv,
  'mosdepth/summary.py': recipePy,
};
