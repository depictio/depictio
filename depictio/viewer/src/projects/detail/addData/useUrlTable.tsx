/**
 * One table read from a URL (`https://` or `s3://`), the third way into a
 * project beside dropped files and a folder: the server fetches the file, so
 * it never travels through the browser. The URL is checked as it is typed
 * (`remoteUrlProblem`), then the server reads its first rows
 * (`RemoteUrlPreview`), which also runs its own policy, before anything is
 * made. The format follows the file's extension and can be corrected.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Group, Select, Stack, TextInput } from '@mantine/core';
import { createDataCollectionFromUrl } from 'depictio-react-core';

import { RemoteUrlPreview, remoteUrlProblem } from '../RemoteUrlPreview';

type Format = 'csv' | 'tsv' | 'parquet' | 'feather';

const FORMATS: Array<{ value: Format; label: string }> = [
  { value: 'csv', label: 'CSV' },
  { value: 'tsv', label: 'TSV' },
  { value: 'parquet', label: 'Parquet' },
  { value: 'feather', label: 'Feather' },
];

/** The last path segment of a URL, query left out. */
export function urlFileName(url: string): string {
  return decodeURIComponent(url.trim().split('?')[0].split('#')[0].split('/').pop() ?? '');
}

function guessed(name: string): { format: Format | null; gzip: boolean } {
  const gzip = /\.gz$/i.test(name);
  const ext = (gzip ? name.slice(0, -3) : name).split('.').pop()?.toLowerCase() ?? '';
  const byExt: Record<string, Format> = {
    csv: 'csv',
    tsv: 'tsv',
    tab: 'tsv',
    txt: 'tsv',
    parquet: 'parquet',
    feather: 'feather',
    arrow: 'feather',
    ipc: 'feather',
  };
  return { format: byExt[ext] ?? null, gzip };
}

/** A collection name out of a file name: no extension, no odd characters. */
function nameOf(fileName: string): string {
  return fileName
    .replace(/\.gz$/i, '')
    .replace(/\.[^.]+$/, '')
    .replace(/[^A-Za-z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

export interface UrlTableResult {
  name: string;
  error: string | null;
  dataCollectionId: string | null;
}

export function useUrlTable({ opened }: { opened: boolean }) {
  const [url, setUrl] = useState('');
  const [name, setName] = useState('');
  const [format, setFormat] = useState<Format | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<UrlTableResult | null>(null);
  // The name follows the URL until the user types one of their own.
  const autoName = useRef('');

  useEffect(() => {
    if (opened) return;
    setUrl('');
    setName('');
    setFormat(null);
    setResult(null);
    autoName.current = '';
  }, [opened]);

  const trimmed = url.trim();
  const problem = trimmed ? remoteUrlProblem(trimmed) : null;
  const fileName = urlFileName(trimmed);
  const gzip = guessed(fileName).gzip;

  useEffect(() => {
    const guess = guessed(fileName);
    if (guess.format) setFormat(guess.format);
    const next = nameOf(fileName);
    if (name === autoName.current) {
      setName(next);
      autoName.current = next;
    }
    // Only the URL drives the guesses; `name` is read to keep a typed one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileName]);

  let reason: string | null = null;
  if (!trimmed) reason = 'Enter the URL of one table file.';
  else if (problem) reason = problem;
  else if (!format) reason = 'Pick the format of the file.';
  else if (!name.trim()) reason = 'Name the table.';

  /** Add the table to `projectId`; the outcome is also kept as `result`. */
  const submit = async (projectId: string): Promise<UrlTableResult | null> => {
    if (reason || !format) return null;
    setSubmitting(true);
    let outcome: UrlTableResult;
    try {
      const made = await createDataCollectionFromUrl({
        projectId,
        name: name.trim(),
        dataType: 'table',
        fileFormat: format,
        separator: format === 'tsv' ? '\t' : ',',
        customSeparator: null,
        compression: gzip ? 'gzip' : 'none',
        hasHeader: true,
        url: trimmed,
      });
      outcome = { name: name.trim(), error: null, dataCollectionId: made.data_collection_id ?? null };
    } catch (err) {
      outcome = {
        name: name.trim(),
        error: (err as Error).message || 'The table could not be added.',
        dataCollectionId: null,
      };
    }
    setResult(outcome);
    setSubmitting(false);
    return outcome;
  };

  const field = (
    <Stack gap={6} data-testid="url-table">
      <TextInput
        placeholder="https://example.org/data.csv or s3://bucket/path/data.tsv"
        aria-label="File URL"
        value={url}
        onChange={(e) => setUrl(e.currentTarget.value)}
        error={problem}
        disabled={submitting}
        data-testid="url-table-input"
      />
      {trimmed && !problem && (
        <Group gap="xs" grow wrap="nowrap">
          <TextInput
            size="xs"
            label="Name"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            disabled={submitting}
            data-testid="url-table-name"
          />
          <Select
            size="xs"
            label={gzip ? 'Format (gzipped)' : 'Format'}
            data={FORMATS}
            value={format}
            onChange={(v) => setFormat((v as Format) ?? null)}
            allowDeselect={false}
            disabled={submitting}
            data-testid="url-table-format"
          />
        </Group>
      )}
    </Stack>
  );

  return {
    field,
    preview: <RemoteUrlPreview url={url} />,
    reason,
    submit,
    submitting,
    result,
    hasUrl: trimmed.length > 0,
    url: trimmed,
    name: name.trim(),
    setUrl,
  };
}
