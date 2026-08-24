import { useRef, useState } from 'react';
import { Stack, Title, Text, Center, Group, Badge, Paper, Alert, Code } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { useStudioStore } from '../state/useStudioStore';
import { parseFixture } from '../catalog/parseFixture';
import TablePreviewLocal from '../builder/TablePreviewLocal';
import type { Dtype, ParsedFixture } from '../types';

const DTYPE_COLOR: Record<Dtype, string> = {
  String: 'gray',
  Int64: 'blue',
  Float64: 'cyan',
  Boolean: 'grape',
  Datetime: 'orange',
};

/** Hard cap. Above this the browser stalls on parse and the GitHub blob API
 *  fails opaquely; the biggest fixture in the catalog today is ~900 KB. */
const MAX_FIXTURE_BYTES = 5 * 1024 * 1024;
/** Above this we still accept it, but say it is unusually large for a sample. */
const LARGE_FIXTURE_BYTES = 1024 * 1024;

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FixtureDrop() {
  const fixture = useStudioStore((s) => s.fixture);
  const setFixture = useStudioStore((s) => s.setFixture);
  const output = useStudioStore((s) => s.output);
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const ingest = async (file: File) => {
    const lower = file.name.toLowerCase();
    if (!lower.endsWith('.csv') && !lower.endsWith('.tsv')) {
      notifications.show({ color: 'red', message: 'Drop a .csv or .tsv file.' });
      return;
    }
    // A fixture is a committed *sample*, not the run's output: the largest one
    // in the catalog today is ~900 KB. Above the hard cap the tab freezes on
    // parse and the GitHub blob API fails with an opaque error, so refuse early
    // and say what to do instead.
    if (file.size > MAX_FIXTURE_BYTES) {
      notifications.show({
        color: 'red',
        autoClose: 12000,
        title: `${file.name} is ${formatBytes(file.size)}`,
        message:
          `Fixtures are capped at ${formatBytes(MAX_FIXTURE_BYTES)} — they are committed samples ` +
          'that ground the bindings, not full outputs. Take a head/sample of the file (keep the ' +
          'header and enough rows to be representative) and drop that.',
      });
      return;
    }
    let parsed: ParsedFixture;
    try {
      const raw = await file.text();
      parsed = parseFixture(file.name, raw);
    } catch (e) {
      // `file.text()` rejects if the file moved mid-drag; this used to be an
      // unhandled rejection with no feedback at all.
      notifications.show({ color: 'red', message: `Could not read ${file.name}: ${(e as Error).message}` });
      return;
    }
    if (parsed.columns.length === 0) {
      notifications.show({ color: 'red', message: 'No columns detected — is the header row present?' });
      return;
    }
    if (parsed.columns.length === 1 && parsed.rows.length > 1) {
      // The delimiter comes from the extension, so a comma-delimited .tsv (or
      // vice versa) parses as one wide column instead of failing outright.
      notifications.show({
        color: 'yellow',
        autoClose: 10000,
        title: 'Only one column detected',
        message:
          `The delimiter is taken from the extension (${parsed.delimiter === ',' ? 'comma for .csv' : 'tab for .tsv'}). ` +
          'If the file uses the other one, rename it so the extension matches.',
      });
    }
    setFixture(parsed);
    if (file.size > LARGE_FIXTURE_BYTES) {
      notifications.show({
        color: 'yellow',
        message: `${file.name} is ${formatBytes(file.size)} — large for a committed fixture; a smaller sample reviews better.`,
      });
    }
    notifications.show({
      color: 'teal',
      message: `${file.name}: ${parsed.columns.length} columns, ${parsed.rows.length} rows.`,
    });
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    // `ingest` reports its own failures, so nothing escapes this promise.
    if (file) void ingest(file);
  };

  // Only flag an unambiguous contradiction: the glob names a tabular extension
  // and the dropped file is the other one. A `.txt` output legitimately arrives
  // here as `.tsv` (the dropzone only takes csv/tsv), so that is not a mismatch.
  const globExt = output.path_glob.toLowerCase().match(/\.(csv|tsv)$/)?.[1];
  const fixtureExt = fixture?.fileName.toLowerCase().endsWith('.tsv') ? 'tsv' : 'csv';
  const globMismatch = Boolean(fixture && globExt && globExt !== fixtureExt);

  return (
    <Stack gap="lg">
      <div>
        <Title order={3} style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
          Fixture
        </Title>
        <Text c="dimmed" size="sm">
          Drop the tool's output file. It's bundled verbatim as the fixture and grounds your
          bindings in CI. Nothing leaves your browser.
        </Text>
      </div>

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
        style={{
          width: '100%',
          borderWidth: 2,
          borderStyle: 'dashed',
          borderRadius: 8,
          borderColor: dragActive ? 'var(--mantine-color-blue-filled)' : 'var(--mantine-color-default-border)',
          padding: '40px 20px',
          cursor: 'pointer',
          background: dragActive ? 'var(--mantine-color-blue-light)' : 'transparent',
          color: 'inherit',
          transition: 'border-color 120ms, background-color 120ms',
        }}
      >
        <Center>
          <Stack align="center" gap={4}>
            <Icon icon="mdi:file-upload-outline" width={40} />
            <Text fw={600}>{fixture ? fixture.fileName : 'Drop CSV/TSV or click to browse'}</Text>
            <Text size="xs" c="dimmed">
              Delimiter auto-detected (.tsv → tab, else comma)
            </Text>
          </Stack>
        </Center>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.tsv"
        style={{ display: 'none' }}
        onChange={(e) => {
          const f = e.currentTarget.files?.[0];
          if (f) void ingest(f);
        }}
      />

      {fixture && output.path_glob && (
        // The single check nothing else makes: is this file actually a sample of
        // the output being declared? Grounding happily validates any table, so a
        // demo dataset dropped here passes CI while describing nothing. Naming
        // the glob next to the file name is what makes the mismatch obvious.
        <Alert
          color={globMismatch ? 'yellow' : 'gray'}
          variant="light"
          icon={<Icon icon={globMismatch ? 'mdi:alert-outline' : 'mdi:information-outline'} />}
        >
          <Text size="sm">
            <Code>{fixture.fileName}</Code> will be committed as the sample for{' '}
            <Code>{output.path_glob}</Code>.
            {globMismatch
              ? ' Those extensions do not match — make sure this really is that output, not a stand-in table.'
              : ' Make sure it really is that output, not a stand-in table.'}
          </Text>
        </Alert>
      )}

      {fixture && (
        <Paper withBorder p="md" radius="md">
          <Group justify="space-between" mb="sm">
            <Title order={5}>Columns</Title>
            <Group gap="xs">
              <Badge variant="light">{fixture.columns.length} cols</Badge>
              <Badge variant="light" color="gray">
                {fixture.rows.length} rows
              </Badge>
              <Badge variant="light" color={fixture.delimiter === '\t' ? 'orange' : 'blue'}>
                {fixture.delimiter === '\t' ? 'TSV' : 'CSV'}
              </Badge>
            </Group>
          </Group>
          <Group gap="xs" mb="md">
            {fixture.columns.map((c) => (
              <Badge key={c.name} color={DTYPE_COLOR[c.dtype]} variant="light" radius="sm">
                {c.name} · {c.dtype}
              </Badge>
            ))}
          </Group>
          <TablePreviewLocal fixture={fixture} height={360} />
        </Paper>
      )}
    </Stack>
  );
}
