/**
 * Template variables (`GROUP_COL`, `SKIP_ANCOM`, ...) as the "From a run
 * folder" flow shows them: a label a reader can take in at a glance, and the
 * value the server resolved for the run folder written the way the rest of
 * the flow writes locations.
 *
 * The raw name stays on screen beside the label (it is what the template and
 * `--var` use); the label only spares the reader the UPPER_SNAKE.
 */

import { isS3Location, relativeToRunFolder } from './runFolderPaths';

/** Words kept in capitals. */
const ACRONYMS = new Set(['ID', 'IDS', 'URL', 'QC', 'FDR', 'GSEA', 'ASV', 'UMI', 'SNP', 'CSV', 'TSV', 'UCSC']);

/** Words spelled out. */
const WORDS: Record<string, string> = {
  COL: 'column',
  COLS: 'columns',
  DIR: 'folder',
  DIRS: 'folders',
};

/** A variable name as a label: `GROUP_COL` reads "Group column",
 *  `METADATA_ID_COL` "Metadata ID column", `SKIP_ANCOM` "Skip ancom",
 *  `IS_NANOPORE` "Nanopore" (the switch a flag turns on), `DATA_ROOT` "Run
 *  folder" (what the flow calls it). Sentence case, a few acronyms kept. */
export function humanizeVariableName(name: string): string {
  const raw = name.trim();
  if (!raw) return '';
  if (raw.toUpperCase() === 'DATA_ROOT') return 'Run folder';
  let words = raw.split(/[_\s]+/).filter(Boolean);
  if (words.length > 1 && words[0].toUpperCase() === 'IS') words = words.slice(1);
  const out = words.map((word) => {
    const upper = word.toUpperCase();
    if (ACRONYMS.has(upper)) return upper === 'IDS' ? 'IDs' : upper;
    return WORDS[upper] ?? word.toLowerCase();
  });
  const [first, ...rest] = out;
  const head = first === first.toLowerCase() ? first.charAt(0).toUpperCase() + first.slice(1) : first;
  return [head, ...rest].join(' ');
}

/** A resolved template setting, ready to be written:
 *  - `run-folder`: the run folder itself;
 *  - `run-path`: a location under the run folder, `relative` to it;
 *  - `path`: a location elsewhere (shortened where it is shown);
 *  - `list`: comma-separated values, the first `shown` and `more` hidden;
 *  - `empty`: no value;
 *  - `text`: anything else, as it is. */
export type TemplateSettingValue =
  | { kind: 'run-folder'; full: string }
  | { kind: 'run-path'; relative: string; full: string }
  | { kind: 'path'; full: string }
  | { kind: 'list'; items: string[]; shown: string[]; more: number }
  | { kind: 'empty' }
  | { kind: 'text'; text: string };

/** A location the server would read: absolute, under the home folder, or S3. */
function looksLikeLocation(value: string): boolean {
  return value.startsWith('/') || value === '~' || value.startsWith('~/') || isS3Location(value);
}

/** How to write `value`, a setting the server resolved for `runFolder`.
 *  Lists longer than `maxItems` (3 by default) keep their first items. */
export function templateSettingValue(
  value: string | null | undefined,
  runFolder: string,
  options: { maxItems?: number } = {},
): TemplateSettingValue {
  const text = (value ?? '').trim();
  if (!text) return { kind: 'empty' };
  if (looksLikeLocation(text)) {
    const relative = relativeToRunFolder(runFolder, text);
    if (relative === '') return { kind: 'run-folder', full: text };
    if (relative !== null) return { kind: 'run-path', relative, full: text };
    return { kind: 'path', full: text };
  }
  if (text.includes(',')) {
    const items = text
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
    if (items.length > 1) {
      const maxItems = Math.max(options.maxItems ?? 3, 1);
      const shown = items.slice(0, maxItems);
      return { kind: 'list', items, shown, more: items.length - shown.length };
    }
  }
  return { kind: 'text', text };
}
