import { useRef, useState } from 'react';
import {
  Stack,
  Title,
  Text,
  Center,
  Group,
  Badge,
  Paper,
  Alert,
  Code,
  TextInput,
  Button,
  Divider,
  Anchor,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { useStudioStore } from '../state/useStudioStore';
import { parseFixture, headerLooksLikeData } from '../catalog/parseFixture';
import { fetchFixtureText, TABULAR_EXT_RE } from '../catalog/fetchFixture';
import TablePreviewLocal from '../builder/TablePreviewLocal';
import type { Dtype } from '../types';
import { HEADING_FONT } from '../theme';

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
  const [url, setUrl] = useState('');
  const [fetching, setFetching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  /** Everything after the bytes are in hand, shared by the drop and the fetch:
   *  the size cap, the parse, and the checks worth warning about. */
  const accept = (fileName: string, raw: string, bytes: number) => {
    // A fixture is a committed *sample*, not the run's output: the largest one
    // in the catalog today is ~900 KB. Above the hard cap the tab freezes on
    // parse and the GitHub blob API fails with an opaque error, so refuse early
    // and say what to do instead.
    if (bytes > MAX_FIXTURE_BYTES) {
      notifications.show({
        color: 'red',
        autoClose: 12000,
        title: `${fileName} is ${formatBytes(bytes)}`,
        message:
          `Fixtures are capped at ${formatBytes(MAX_FIXTURE_BYTES)}; they are committed samples ` +
          'that ground the bindings, not full outputs. Take a head/sample of the file (keep the ' +
          'header and enough rows to be representative) and drop that.',
      });
      return;
    }
    const parsed = parseFixture(fileName, raw);
    if (parsed.columns.length === 0) {
      notifications.show({ color: 'red', message: 'No columns detected. Is the header row present?' });
      return;
    }
    if (parsed.columns.length === 1 && parsed.rows.length > 1) {
      // A .csv/.tsv is parsed on its extension, so the other delimiter yields
      // one wide column instead of failing outright. Any other extension was
      // sniffed, so one column there means the file really has one.
      const stated = /\.(csv|tsv)$/i.test(fileName);
      notifications.show({
        color: 'yellow',
        autoClose: 10000,
        title: 'Only one column detected',
        message: stated
          ? `The delimiter is taken from the extension (${parsed.delimiter === ',' ? 'comma for .csv' : 'tab for .tsv'}). ` +
            'If the file uses the other one, rename it so the extension matches.'
          : 'The delimiter was sniffed from the header line. If this file is not one column, its header may be further down.',
      });
    }
    if (headerLooksLikeData(parsed.columns.map((c) => c.name))) {
      // Nothing downstream can catch this: the numbers become column names and
      // every binding made against them is meaningless.
      notifications.show({
        color: 'yellow',
        autoClose: 14000,
        title: 'This file may have no header row',
        message:
          'The first line was read as the column names and several of them are numbers. ' +
          'An output with no header is not directly bindable, so its catalog entry needs a ' +
          'recipe, which this Studio does not author.',
      });
    }
    setFixture(parsed);
    if (bytes > LARGE_FIXTURE_BYTES) {
      notifications.show({
        color: 'yellow',
        message: `${fileName} is ${formatBytes(bytes)}, large for a committed fixture. A smaller sample reviews better.`,
      });
    }
    notifications.show({
      color: 'accent',
      message: `${fileName}: ${parsed.columns.length} columns, ${parsed.rows.length} rows.`,
    });
  };

  const ingest = async (file: File) => {
    if (!TABULAR_EXT_RE.test(file.name)) {
      notifications.show({ color: 'red', message: 'Drop a .csv, .tsv, .txt or .tab file.' });
      return;
    }
    let raw: string;
    try {
      raw = await file.text();
    } catch (e) {
      // `file.text()` rejects if the file moved mid-drag; this used to be an
      // unhandled rejection with no feedback at all.
      notifications.show({
        color: 'red',
        message: `Could not read ${file.name}: ${(e as Error).message}`,
      });
      return;
    }
    accept(file.name, raw, file.size);
  };

  const ingestUrl = async () => {
    if (!url.trim()) return;
    setFetching(true);
    try {
      const { fileName, text, bytes } = await fetchFixtureText(url);
      accept(fileName, text, bytes);
    } catch (e) {
      notifications.show({ color: 'red', autoClose: 12000, message: (e as Error).message });
    } finally {
      setFetching(false);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    // `ingest` reports its own failures, so nothing escapes this promise.
    if (file) void ingest(file);
  };

  // Only flag an unambiguous contradiction: the glob names one tabular
  // extension and the fixture carries the other. A `.txt` output matches
  // nothing here, so it is left alone rather than reported as a mismatch.
  const globExt = output.path_glob.toLowerCase().match(/\.(csv|tsv)$/)?.[1];
  const fixtureExt = fixture?.fileName.toLowerCase().match(/\.(csv|tsv)$/)?.[1];
  const globMismatch = Boolean(fixture && globExt && fixtureExt && globExt !== fixtureExt);

  return (
    <Stack gap="lg">
      <div>
        <Title order={3} style={{ fontFamily: HEADING_FONT, fontWeight: 600 }}>
          Fixture
        </Title>
        <Text c="dimmed" size="sm">
          Provide the tool's output file. It's bundled verbatim as the fixture and grounds your
          bindings in CI. A dropped file never leaves your browser.
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
          borderColor: dragActive ? 'var(--mantine-primary-color-filled)' : 'var(--mantine-color-default-border)',
          padding: '40px 20px',
          cursor: 'pointer',
          background: dragActive ? 'var(--mantine-primary-color-light)' : 'transparent',
          color: 'inherit',
          transition: 'border-color 120ms, background-color 120ms',
        }}
      >
        <Center>
          <Stack align="center" gap={4}>
            <Icon icon="mdi:file-upload-outline" width={40} />
            <Text fw={600}>
              {fixture ? fixture.fileName : 'Drop a .csv, .tsv, .txt or .tab file, or click to browse'}
            </Text>
            <Text size="xs" c="dimmed">
              Delimiter from the extension for .csv and .tsv, sniffed otherwise
            </Text>
          </Stack>
        </Center>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.tsv,.txt,.tab"
        style={{ display: 'none' }}
        onChange={(e) => {
          const f = e.currentTarget.files?.[0];
          if (f) void ingest(f);
        }}
      />

      {/* Fetch from a URL. The path glob is a pattern rather than an address,
          so there is nothing to pull from the tool source itself; what this is
          for is the corpora of real outputs that do exist, linked directly. */}
      <Divider label="or fetch from a URL" labelPosition="center" />
      <Group align="flex-end" gap="sm" wrap="nowrap">
        <TextInput
          style={{ flex: 1 }}
          label="Output file URL"
          description="Needs a host that allows cross-origin requests. The nf-core megatests bucket and raw.githubusercontent.com both do, and a github.com blob link is rewritten to raw."
          placeholder="https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/<pipeline>/results-<sha>/<file>"
          value={url}
          onChange={(e) => setUrl(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void ingestUrl();
          }}
        />
        <Button
          variant="light"
          loading={fetching}
          leftSection={<Icon icon="mdi:cloud-download-outline" />}
          onClick={() => void ingestUrl()}
        >
          Fetch
        </Button>
      </Group>
      <Text size="xs" c="dimmed" mt={-8}>
        Where to find real outputs:{' '}
        <Anchor
          size="xs"
          href="https://nf-co.re/pipelines"
          target="_blank"
          rel="noreferrer"
        >
          nf-core megatests
        </Anchor>{' '}
        (each pipeline's <em>Results</em> tab browses its full-scale run, the closest thing to your
        own output),{' '}
        <Anchor
          size="xs"
          href="https://github.com/MultiQC/test-data/tree/main/data/modules"
          target="_blank"
          rel="noreferrer"
        >
          MultiQC test-data
        </Anchor>{' '}
        (one directory per tool) and{' '}
        <Anchor
          size="xs"
          href="https://github.com/galaxyproject/tools-iuc/tree/main/tools"
          target="_blank"
          rel="noreferrer"
        >
          Galaxy tools-iuc
        </Anchor>{' '}
        (each tool's <Code fz="xs">test-data/</Code>). nf-core module tests are no help: they hold
        checksums, not output files.
      </Text>

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
              ? ' Those extensions do not match. Make sure this really is that output, not a stand-in table.'
              : ' Make sure it really is that output, not a stand-in table.'}
          </Text>
          {fixture.renamedFrom && (
            <Text size="sm" mt="xs">
              Committed as <Code>{fixture.fileName}</Code>, not{' '}
              <Code>{fixture.renamedFrom}</Code>: this file is tab-delimited, and depictio only
              reads a fixture as tab-delimited when it is named <Code>.tsv</Code>. The contents are
              untouched.
            </Text>
          )}
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
