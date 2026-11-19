import { useState } from 'react';
import {
  Stack,
  Title,
  Text,
  Group,
  Badge,
  Paper,
  Alert,
  Code,
  TextInput,
  Button,
  Divider,
  Anchor,
  Collapse,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import RecipePanel from './RecipePanel';
import { useStudioStore } from '../state/useStudioStore';
import { parseFixture, headerLooksLikeData } from '../catalog/parseFixture';
import { fetchFixtureText, TABULAR_EXT_RE } from '../catalog/fetchFixture';
import { readRawSample } from '../catalog/rawSample';
import { recipeTemplate } from '../catalog/yamlGen';
import TablePreviewLocal from '../builder/TablePreviewLocal';
import type { Dtype, ParsedFixture } from '../types';
import StepHead from '../components/StepHead';
import DropZone from '../components/DropZone';

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

/**
 * A file that looks like a tool's raw output rather than a bindable table:
 * an extension the fixture reader does not take, or a first row of data where
 * the header should be. Held until the author picks what to do with it.
 */
interface PendingRaw {
  file: File;
  reason: 'extension' | 'headerless';
  /** The parse, kept so "use it as is" does not read the file twice. */
  parsed?: ParsedFixture;
  bytes: number;
}

/** Columns, dtypes and the table preview of the current fixture. */
function FixtureDetails({ fixture }: { fixture: ParsedFixture }) {
  return (
    <Paper withBorder p="md" radius="md">
      <Group justify="space-between" mb="sm">
        <Title order={2} size="h5">Columns</Title>
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
  );
}

export default function FixtureDrop() {
  const fixture = useStudioStore((s) => s.fixture);
  const setFixture = useStudioStore((s) => s.setFixture);
  const output = useStudioStore((s) => s.output);
  const setOutput = useStudioStore((s) => s.setOutput);
  const tool = useStudioStore((s) => s.tool);
  const [url, setUrl] = useState('');
  const [fetching, setFetching] = useState(false);
  const [pending, setPending] = useState<PendingRaw | null>(null);
  const [showExpectedDrop, setShowExpectedDrop] = useState(false);

  /** Commit a parsed table as the fixture, with the notices worth showing. */
  const commit = (fileName: string, parsed: ParsedFixture, bytes: number) => {
    setPending(null);
    setFixture(parsed);
    if (bytes > LARGE_FIXTURE_BYTES) {
      notifications.show({
        color: 'yellow',
        message: `${fileName} is ${formatBytes(bytes)}, large for a committed fixture. A smaller sample reviews better.`,
      });
    }
    notifications.show({
      color: parsed.parseWarnings?.length ? 'yellow' : 'teal',
      message: parsed.parseWarnings?.length
        ? `${fileName}: parsed with ${parsed.parseWarnings.length} problem(s), see below.`
        : `${fileName}: ${parsed.columns.length} columns, ${parsed.rows.length} rows.`,
    });
  };

  /** Everything after the bytes are in hand, shared by the drop and the fetch:
   *  the size cap, the parse, and the checks worth warning about. `file` is
   *  set for a local file, so a raw-looking one can be handed to a recipe. */
  const accept = (fileName: string, raw: string, bytes: number, file?: File) => {
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
    // Nothing downstream can catch a header made of data: the numbers become
    // column names and every binding made against them is meaningless. Such a
    // file is the tool's raw output, which is what a recipe is for, so offer
    // that instead of committing it.
    if (headerLooksLikeData(parsed.columns.map((c) => c.name)) && !output.recipe) {
      if (file) {
        setPending({ file, reason: 'headerless', parsed, bytes });
        return;
      }
      notifications.show({
        color: 'yellow',
        autoClose: 14000,
        title: 'This file may have no header row',
        message:
          'The first line was read as the column names and several of them are numbers. ' +
          'Turn on "The file needs reshaping first (recipe)" on the Tool step and add it as a raw sample.',
      });
    }
    commit(fileName, parsed, bytes);
  };

  const ingest = async (file: File) => {
    // Without a recipe, a file the fixture reader does not take is almost
    // always the tool's raw output (.narrowPeak, .bed, .json, .log…): offer to
    // reshape it rather than refuse it.
    if (!TABULAR_EXT_RE.test(file.name) && !output.recipe) {
      setPending({ file, reason: 'extension', bytes: file.size });
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
    accept(file.name, raw, file.size, file);
  };

  /** Turn this output into a recipe output, with the pending file as its raw sample. */
  const reshapeWithRecipe = async (p: PendingRaw) => {
    try {
      const sample = await readRawSample(p.file);
      setOutput({
        recipe: {
          code: output.recipe?.code ?? recipeTemplate(tool.id || 'tool', output.slug || 'output', tool.name),
          ...output.recipe,
          inputs: [...(output.recipe?.inputs ?? []).filter((i) => i.fileName !== sample.fileName), sample],
        },
      });
      setPending(null);
      notifications.show({
        color: 'teal',
        message: `${p.file.name} is now the raw sample. Edit the recipe below and run it to produce the fixture.`,
      });
    } catch (e) {
      notifications.show({ color: 'red', message: `Could not read ${p.file.name}: ${(e as Error).message}` });
    }
  };

  /** Commit the pending file as the fixture anyway. */
  const useAsIs = async (p: PendingRaw) => {
    if (p.parsed) {
      commit(p.file.name, p.parsed, p.bytes);
      return;
    }
    try {
      const raw = await p.file.text();
      setPending(null);
      const parsed = parseFixture(p.file.name, raw);
      if (parsed.columns.length === 0) {
        notifications.show({ color: 'red', message: 'No columns detected. Is the header row present?' });
        return;
      }
      commit(p.file.name, parsed, p.bytes);
    } catch (e) {
      notifications.show({ color: 'red', message: `Could not read ${p.file.name}: ${(e as Error).message}` });
    }
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

  // Only flag an unambiguous contradiction: the glob names one tabular
  // extension and the fixture carries the other. A `.txt` output matches
  // nothing here, so it is left alone rather than reported as a mismatch.
  const globExt = output.path_glob.toLowerCase().match(/\.(csv|tsv)$/)?.[1];
  const fixtureExt = fixture?.fileName.toLowerCase().match(/\.(csv|tsv)$/)?.[1];
  const globMismatch = Boolean(fixture && globExt && fixtureExt && globExt !== fixtureExt);

  const loadedSummary = fixture
    ? { label: fixture.fileName, summary: `${fixture.rows.length} rows · ${fixture.columns.length} cols` }
    : null;

  const parseWarnings = fixture?.parseWarnings?.length ? (
    <Alert
      color="orange"
      variant="light"
      icon={<Icon icon="mdi:alert-outline" />}
      title="The file did not parse cleanly"
      data-testid="parse-warnings"
    >
      <Stack gap={4}>
        {fixture.parseWarnings.map((w) => (
          <Text size="sm" key={w}>
            {w}
          </Text>
        ))}
        <Text size="sm" c="dimmed">
          Rows that do not match the header are previewed as best they can be, but CI reads the
          file strictly. Fix the file and drop it again.
        </Text>
      </Stack>
    </Alert>
  ) : null;

  // ── With a recipe: the three-stage pipeline ────────────────────────────────
  if (output.recipe) {
    return (
      <Stack gap="lg">
        <StepHead
          step={1}
          title="Fixture"
          description="This output is reshaped by a recipe: add a sample of the raw file (①), run the recipe on it (②), and its result becomes the fixture (③). Files never leave your browser."
        />
        <RecipePanel
          fixtureBody={
            fixture ? (
              <Stack gap="sm">
                {parseWarnings}
                <FixtureDetails fixture={fixture} />
              </Stack>
            ) : null
          }
          fixtureDrop={
            <Stack gap={6}>
              <Anchor
                component="button"
                type="button"
                size="xs"
                c="dimmed"
                onClick={() => setShowExpectedDrop((v) => !v)}
                data-testid="expected-output-toggle"
              >
                {showExpectedDrop ? 'Hide' : 'Or drop the expected output directly instead of running the recipe'}
              </Anchor>
              <Collapse in={showExpectedDrop}>
                {showExpectedDrop && (
                  <DropZone
                    compact
                    onFiles={(f) => void ingest(f[0])}
                    emptyLabel="Drop the recipe's expected output (.csv / .tsv)"
                    loaded={null}
                    testId="expected-output-drop"
                  />
                )}
              </Collapse>
            </Stack>
          }
        />
      </Stack>
    );
  }

  // ── Without a recipe: the file is the fixture ──────────────────────────────
  return (
    <Stack gap="lg">
      <StepHead
        step={1}
        title="Fixture"
        description="Provide the tool's output file. It's bundled verbatim as the fixture and grounds your bindings in CI. A dropped file never leaves your browser."
      />

      <DropZone
        onFiles={(f) => void ingest(f[0])}
        emptyLabel="Drop the output file, or click to browse"
        emptyHint="A table with a header row (.csv, .tsv, .txt, .tab). Anything else can be reshaped with a recipe."
        loaded={loadedSummary}
        testId="fixture-drop"
      />

      {pending && (
        <Alert
          color="yellow"
          variant="light"
          icon={<Icon icon="mdi:file-alert-outline" />}
          title={
            pending.reason === 'extension'
              ? `${pending.file.name} looks like a raw output, not a table`
              : `${pending.file.name} may have no header row`
          }
          data-testid="raw-file-offer"
          withCloseButton
          onClose={() => setPending(null)}
        >
          <Stack gap="sm">
            <Text size="sm">
              {pending.reason === 'extension'
                ? 'Its extension is not one the fixture reader takes (.csv, .tsv, .txt, .tab). A file like this is usually reshaped at ingestion by a recipe, a small polars module you write and run here.'
                : 'The first line was read as the column names and several of them are numbers, so the file probably starts on data. An output with no header is not directly bindable: a recipe gives it its columns.'}
            </Text>
            <Group gap="sm">
              <Button
                size="xs"
                leftSection={<Icon icon="mdi:language-python" width={16} />}
                onClick={() => void reshapeWithRecipe(pending)}
                data-testid="raw-file-use-recipe"
              >
                Reshape it with a recipe
              </Button>
              <Button size="xs" variant="default" onClick={() => void useAsIs(pending)} data-testid="raw-file-as-is">
                Use it as is
              </Button>
            </Group>
          </Stack>
        </Alert>
      )}

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
        <Anchor size="xs" href="https://nf-co.re/pipelines" target="_blank" rel="noreferrer">
          nf-core megatests
        </Anchor>{' '}
        (each pipeline's <em>Results</em> tab browses its full-scale run, the closest thing to your
        own output),{' '}
        <Anchor size="xs" href="https://github.com/nf-core/test-datasets" target="_blank" rel="noreferrer">
          nf-core test-datasets
        </Anchor>{' '}
        (branch <Code fz="xs">modules</Code>, <Code fz="xs">data/genomics/…</Code>),{' '}
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
        (each tool's <Code fz="xs">test-data/</Code>).
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

      {parseWarnings}
      {fixture && <FixtureDetails fixture={fixture} />}
    </Stack>
  );
}
