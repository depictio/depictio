/**
 * Recipe authoring for an output whose raw file is not directly bindable.
 *
 * The recipe is the same Python module depictio runs at ingestion (SOURCES,
 * OUTPUT_SCHEMA, transform). Here it runs in the browser, in the Pyodide +
 * polars runtime the serverless bundle ships, over a sample of the raw file;
 * its result becomes the committed fixture, so the renders are bound to what
 * the recipe really returns. Nothing loads until "Run" is pressed.
 *
 * The step is laid out as the pipeline it is, three stages in order:
 *   ① raw sample(s)  the tool's own file, any extension; stays in the browser
 *   ② recipe         the Python module; exported as <tool>/<slug>.py
 *   ③ fixture        the recipe's result; exported as <tool>/<slug>.tsv
 * Each stage shows its own state, so it is clear which file goes where and
 * what is left to do. The fixture stage's body (columns, preview) and the
 * secondary "drop the expected output" path come from FixtureDrop.
 */
import { useState, type ReactNode } from 'react';
import { Alert, Badge, Button, Code, Group, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import Editor from '@monaco-editor/react';
// Bundles Monaco locally instead of fetching it from a CDN (as depictio's own Code Mode does).
import 'depictio-builder/figure/monacoSetup';
import { useComputedColorScheme } from '@mantine/core';
import { useStudioStore } from '../state/useStudioStore';
import { parseFixture } from '../catalog/parseFixture';
import { recipeOutputColumns } from '../catalog/diagnostics';
import { recipeRefOf } from '../catalog/yamlGen';
import { readRawSample } from '../catalog/rawSample';
import DropZone from '../components/DropZone';
import PipelineStage, { PipelineArrow, type StageStatus } from '../components/PipelineStage';
import { STUDIO_TONE } from '../theme';

type RunState =
  | { status: 'idle' }
  | { status: 'running'; phase: string }
  | { status: 'ok'; rows: number; columns: Array<{ name: string; dtype: string }>; stdout: string }
  | { status: 'error'; message: string; stdout?: string };

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export default function RecipePanel({
  fixtureBody,
  fixtureDrop,
}: {
  /** Columns and preview of the current fixture (stage ③), when there is one. */
  fixtureBody?: ReactNode;
  /** The secondary path: drop the recipe's expected output directly. */
  fixtureDrop?: ReactNode;
}) {
  const output = useStudioStore((s) => s.output);
  const setOutput = useStudioStore((s) => s.setOutput);
  const setFixtureAt = useStudioStore((s) => s.setFixtureAt);
  const fixture = useStudioStore((s) => s.fixture);
  const toolId = useStudioStore((s) => s.tool.id);
  const scheme = useComputedColorScheme('light');
  const [run, setRun] = useState<RunState>({ status: 'idle' });
  const recipe = output.recipe;
  if (!recipe) return null;

  const inputs = recipe.inputs ?? [];
  const declared = recipeOutputColumns(recipe.code);
  const recipeRef = recipeRefOf(toolId || '<tool>', output);

  const addInputs = async (files: File[]) => {
    try {
      const read = await Promise.all(files.map(readRawSample));
      setOutput({ recipe: { ...recipe, inputs: [...inputs.filter((i) => !read.some((r) => r.fileName === i.fileName)), ...read] } });
    } catch (e) {
      setRun({ status: 'error', message: `Could not read the sample: ${(e as Error).message}` });
    }
  };

  const execute = async () => {
    // The output this run is for: the author can switch outputs while Python
    // loads, and the result must land on the output that asked for it.
    const { activeIndex: runIndex, output: runOutput } = useStudioStore.getState();
    const runSlug = runOutput.slug;
    // Pressing Run on an imported recipe, with the notice above it, is the
    // author's consent to running it; from here on it is theirs.
    if (recipe._untrusted) setOutput({ recipe: { ...recipe, _untrusted: undefined } });
    setRun({ status: 'running', phase: 'Loading Python (first run only)…' });
    try {
      const engine = await import('../pyodide/engine');
      await engine.ensureEngine((p: { phase: string; detail?: string }) => setRun({ status: 'running', phase: p.detail ? `${p.phase}: ${p.detail}` : p.phase }));
      setRun({ status: 'running', phase: 'Running transform()…' });
      const res = await engine.runRecipe(recipe.code, inputs);
      if (!res.ok) {
        setRun({ status: 'error', message: res.error ?? 'The recipe failed.', stdout: res.stdout });
        return;
      }
      // The recipe's output IS the fixture: what the renders bind, and what CI grounds against.
      const applied = setFixtureAt(runIndex, runSlug, parseFixture(`${runSlug || 'output'}.tsv`, res.tsv));
      if (!applied) {
        setRun({
          status: 'error',
          message: `The output this run was for (${runSlug || 'unnamed'}) was removed or renamed while it ran, so its result was discarded. Run it again.`,
          stdout: res.stdout,
        });
        return;
      }
      setRun({ status: 'ok', rows: res.rowCount, columns: res.columns, stdout: res.stdout });
    } catch (e) {
      setRun({ status: 'error', message: (e as Error).message });
    }
  };

  // Stage states. The fixture is checked against OUTPUT_SCHEMA: a fixture that
  // lacks a declared column is the recipe's result from an older version of
  // the code, or a hand-dropped file that is not its output.
  const fixtureCols = new Set(fixture?.columns.map((c) => c.name) ?? []);
  const missing = fixture && declared ? declared.filter((c) => !fixtureCols.has(c)) : [];
  const rawStatus: StageStatus = inputs.length ? 'ready' : 'empty';
  const recipeStatus: StageStatus =
    run.status === 'running'
      ? 'running'
      : run.status === 'error'
        ? 'error'
        : run.status === 'ok' || (fixture && !missing.length)
          ? 'ready'
          : 'empty';
  const fixtureStatus: StageStatus = !fixture ? 'empty' : missing.length ? 'error' : 'ready';

  return (
    <Stack gap="sm" data-testid="recipe-panel">
      {/* ① Raw sample(s) */}
      <PipelineStage
        index={1}
        title="Raw sample"
        status={rawStatus}
        statusText={inputs.length ? `${inputs.length} file${inputs.length > 1 ? 's' : ''}` : undefined}
        exportNote="Stays in your browser: not exported, shared in links or saved with the draft (add it again after a reload)."
        testId="stage-raw"
      >
        <Text size="sm" c="dimmed">
          The tool's own output file, as it comes out of a run: any extension, compressed or not. Add
          several to check the recipe across samples.
        </Text>
        <DropZone
          multiple
          compact={inputs.length > 0}
          onFiles={(f) => void addInputs(f)}
          emptyLabel="Drop the raw file(s) here, or click to browse"
          emptyHint="Any text file: .narrowPeak, .bed, .xls, .json, .log, .tsv.gz…"
          loaded={null}
          testId="recipe-add-input"
        />
        {inputs.length > 0 && (
          <Stack gap={4} data-testid="recipe-inputs">
            {inputs.map((i) => (
              <Group key={i.fileName} gap="xs" wrap="nowrap">
                <Icon icon="mdi:file-check-outline" width={16} color={`var(--mantine-color-${STUDIO_TONE}-6)`} />
                <Text size="sm" style={{ flex: 1, minWidth: 0 }} truncate>
                  {i.sourcePath ?? i.fileName}
                </Text>
                <Text size="xs" c="dimmed">
                  {formatBytes(new Blob([i.text]).size)}
                </Text>
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color="gray"
                  aria-label={`Remove ${i.fileName}`}
                  onClick={() => setOutput({ recipe: { ...recipe, inputs: inputs.filter((x) => x !== i) } })}
                >
                  <Icon icon="mdi:close" width={14} />
                </Button>
              </Group>
            ))}
          </Stack>
        )}
      </PipelineStage>

      <PipelineArrow />

      {/* ② Recipe */}
      <PipelineStage
        index={2}
        title="Recipe"
        status={recipeStatus}
        statusText={run.status === 'running' ? 'running' : undefined}
        exportNote={
          <>
            Exported as <Code fz="xs">{recipeRef}</Code>, referenced by <Code fz="xs">recipe:</Code> in the output YAML.
          </>
        }
        testId="stage-recipe"
      >
        <Text size="sm" c="dimmed">
          A polars module (<Code fz="xs">SOURCES</Code>, <Code fz="xs">OUTPUT_SCHEMA</Code>,{' '}
          <Code fz="xs">transform</Code>) that depictio runs at ingestion. Run it here on the raw
          sample: its result becomes the fixture below.
        </Text>
        {declared && (
          <Group gap={4} data-testid="recipe-output-schema">
            <Text size="xs" c="dimmed" mr={2}>
              Columns it returns (OUTPUT_SCHEMA):
            </Text>
            {declared.length ? (
              declared.map((c) => (
                <Badge key={c} size="xs" variant="light" color={fixture && !fixtureCols.has(c) ? 'red' : STUDIO_TONE}>
                  {c}
                </Badge>
              ))
            ) : (
              <Text size="xs" c="orange">
                none declared
              </Text>
            )}
          </Group>
        )}

        {recipe._untrusted && (
          <Alert
            color="yellow"
            variant="light"
            icon={<Icon icon="mdi:shield-alert-outline" />}
            title="Recipe from a link or an imported file"
            data-testid="recipe-untrusted"
          >
            You did not write this recipe in this session. Running it executes its Python in this
            page, with access to everything the page can reach. Read it below before you run it.
          </Alert>
        )}

        <div style={{ border: '1px solid var(--app-border-color, var(--mantine-color-default-border))', borderRadius: 8, overflow: 'hidden' }}>
          <Editor
            height="340px"
            language="python"
            theme={scheme === 'dark' ? 'vs-dark' : 'vs'}
            value={recipe.code}
            onChange={(v) => setOutput({ recipe: { ...recipe, code: v ?? '' } })}
            options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false, tabSize: 4 }}
          />
        </div>

        <Group gap="sm">
          <Button
            leftSection={<Icon icon="mdi:play" width={16} />}
            onClick={execute}
            loading={run.status === 'running'}
            disabled={!inputs.length}
            data-testid="recipe-run"
          >
            {recipe._untrusted ? 'Run this code' : 'Run in the browser'}
          </Button>
          <Text size="xs" c="dimmed">
            {run.status === 'running'
              ? run.phase
              : !inputs.length
                ? 'Add a raw sample in ① first.'
                : 'Python + polars in your browser (Pyodide); the first run downloads it.'}
          </Text>
        </Group>

        {run.status === 'error' && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />} title="The recipe failed" data-testid="recipe-error">
            <Code block style={{ whiteSpace: 'pre-wrap', maxHeight: 220, overflow: 'auto' }}>
              {run.message}
            </Code>
          </Alert>
        )}
        {(run.status === 'ok' || run.status === 'error') && run.stdout ? (
          <Code block style={{ maxHeight: 140, overflow: 'auto' }}>
            {run.stdout}
          </Code>
        ) : null}
      </PipelineStage>

      <PipelineArrow />

      {/* ③ Fixture: the recipe's result */}
      <PipelineStage
        index={3}
        title="Fixture (the recipe's result)"
        status={fixtureStatus}
        statusText={fixture ? `${fixture.rows.length} rows · ${fixture.columns.length} cols` : undefined}
        exportNote={
          fixture ? (
            <>
              Exported as <Code fz="xs">{`${toolId || '<tool>'}/${fixture.fileName}`}</Code>: the sample
              CI checks the renders against.
            </>
          ) : undefined
        }
        testId="stage-fixture"
      >
        {run.status === 'ok' && (
          <Text size="sm" c="dimmed" data-testid="recipe-ok">
            From the last run of the recipe: {run.rows} row(s).
          </Text>
        )}
        {missing.length > 0 && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />} data-testid="fixture-schema-mismatch">
            This fixture lacks {missing.join(', ')} from <Code fz="xs">OUTPUT_SCHEMA</Code>. Run the
            recipe again so the fixture is its current output.
          </Alert>
        )}
        {!fixture && (
          <Text size="sm" c="dimmed">
            Run the recipe in ② to produce the fixture. Its columns and rows show here.
          </Text>
        )}
        {fixtureBody}
        {fixtureDrop}
      </PipelineStage>
    </Stack>
  );
}
