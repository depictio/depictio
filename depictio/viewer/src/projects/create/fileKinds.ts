/**
 * What a dropped file is, from its extension and its content: the content
 * decides where the two disagree, so a `.parquet` holding a MultiQC report is
 * a report and a `.csv` separated by tabs is read with tabs.
 */
import { baseName } from './tableFiles';

/** A collection type, or `unknown` for a file Depictio cannot take. */
export type FileKind = 'table' | 'multiqc' | 'phylogeny' | 'geojson' | 'image' | 'unknown';

export interface FileGuess {
  kind: FileKind;
  /** "A table, CSV": what the row of the file says. */
  label: string;
  /** How a table is read; absent for the other kinds. */
  table?: { fileFormat: string; separator: string; compression: string };
}

const HEAD_BYTES = 64 * 1024;
/** More footer than a report's schema needs. */
const MAX_FOOTER_BYTES = 4 * 1024 * 1024;

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'tif', 'tiff']);
const TREE_EXTENSIONS = new Set(['nwk', 'newick', 'tree', 'treefile', 'tre', 'nex', 'nexus']);

/** Every extension the picker offers; a dropped file may have any other. */
export const ACCEPTED_EXTENSIONS = [
  'csv', 'tsv', 'tab', 'txt', 'gz', 'parquet', 'pq', 'feather', 'arrow',
  'geojson', 'json', ...TREE_EXTENSIONS, ...IMAGE_EXTENSIONS,
];

const unknown = (label: string): FileGuess => ({ kind: 'unknown', label });

const asTable = (format: 'csv' | 'tsv', compression = 'none'): FileGuess => ({
  kind: 'table',
  label: `Table, ${format.toUpperCase()}${compression === 'gzip' ? ' (gzip)' : ''}`,
  table: { fileFormat: format, separator: format === 'tsv' ? '\t' : ',', compression },
});

/** The separator of delimited text: the one each of the first lines has, the
 *  same number of times; null for text that is not a table. */
function sniffSeparator(text: string): 'csv' | 'tsv' | null {
  const lines = text.split(/\r?\n/).filter(Boolean).slice(0, 5);
  // One line of prose may well hold a comma.
  if (lines.length < 2) return null;
  for (const [sep, format] of [['\t', 'tsv'], [',', 'csv']] as const) {
    const counts = lines.map((l) => l.split(sep).length);
    if (counts[0] > 1 && counts.every((c) => c === counts[0])) return format;
  }
  return null;
}

/** Whether a Parquet file's schema is the one MultiQC writes. */
async function isMultiqcParquet(file: File): Promise<boolean> {
  if (file.size < 12) return false;
  const tail = new DataView(await file.slice(file.size - 8).arrayBuffer());
  const footer = Math.min(tail.getUint32(0, true), MAX_FOOTER_BYTES);
  const schema = await file.slice(Math.max(0, file.size - 8 - footer), file.size - 8).arrayBuffer();
  return new TextDecoder('latin1').decode(schema).includes('plot_input_data');
}

const looksLikeNewick = (text: string, whole: boolean): boolean => {
  const body = text.trim();
  return body.startsWith('(') && body.includes(',') && (!whole || body.endsWith(';'));
};

async function identify(file: File): Promise<FileGuess> {
  const name = baseName(file.name).toLowerCase();
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.') + 1) : '';

  if (IMAGE_EXTENSIONS.has(ext)) return { kind: 'image', label: `Image, ${ext.toUpperCase()}` };
  if (ext === 'parquet' || ext === 'pq') {
    const report = name === 'multiqc.parquet' || (await isMultiqcParquet(file));
    if (report) return { kind: 'multiqc', label: 'MultiQC report' };
    return {
      kind: 'table',
      label: 'Table, Parquet',
      table: { fileFormat: 'parquet', separator: ',', compression: 'none' },
    };
  }
  if (ext === 'feather' || ext === 'arrow') {
    return {
      kind: 'table',
      label: 'Table, Feather',
      table: { fileFormat: 'feather', separator: ',', compression: 'none' },
    };
  }
  if (ext === 'gz') {
    const inner = name.slice(0, -3).split('.').pop();
    if (inner === 'csv') return asTable('csv', 'gzip');
    if (inner === 'tsv' || inner === 'tab') return asTable('tsv', 'gzip');
    return unknown('Compressed file of an unknown kind');
  }

  // A JSON file may name its type after its features: read all of it.
  const isJson = ext === 'geojson' || ext === 'json';
  const text = await (isJson ? file : file.slice(0, HEAD_BYTES)).text();
  const whole = isJson || file.size <= HEAD_BYTES;

  if (/^\s*#nexus/i.test(text)) return { kind: 'phylogeny', label: 'Tree, Nexus' };
  if (looksLikeNewick(text, whole)) return { kind: 'phylogeny', label: 'Tree, Newick' };
  if (TREE_EXTENSIONS.has(ext)) return unknown('No tree in this file');
  if (isJson) {
    return /"type"\s*:\s*"FeatureCollection"/.test(text)
      ? { kind: 'geojson', label: 'Map, GeoJSON' }
      : unknown(ext === 'geojson' ? 'Not a FeatureCollection' : 'JSON that is not GeoJSON');
  }

  const separated = sniffSeparator(text);
  if (ext === 'csv' || ext === 'tsv' || ext === 'tab') {
    return asTable(separated ?? (ext === 'csv' ? 'csv' : 'tsv'));
  }
  return separated ? asTable(separated) : unknown('Not a format Depictio reads');
}

const known = new WeakMap<File, Promise<FileGuess>>();

/** What `file` is, read once. A file that cannot be read is `unknown`. */
export function identifyFile(file: File): Promise<FileGuess> {
  let guess = known.get(file);
  if (!guess) {
    guess = identify(file).catch(() => unknown('This file could not be read'));
    known.set(file, guess);
  }
  return guess;
}

/** "3 tables, 1 MultiQC report, 2 images". */
export function kindsText(guesses: FileGuess[]): string {
  const words: Array<[FileKind, string, string]> = [
    ['table', 'table', 'tables'],
    ['multiqc', 'MultiQC report', 'MultiQC reports'],
    ['phylogeny', 'tree', 'trees'],
    ['geojson', 'map', 'maps'],
    ['image', 'image', 'images'],
  ];
  return words
    .map(([kind, one, many]) => {
      const n = guesses.filter((g) => g.kind === kind).length;
      return n === 0 ? '' : `${n} ${n === 1 ? one : many}`;
    })
    .filter(Boolean)
    .join(', ');
}
