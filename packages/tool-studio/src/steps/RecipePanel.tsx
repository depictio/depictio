/**
 * Recipe authoring for an output whose raw file is not directly bindable.
 *
 * The recipe is the same Python module depictio runs at ingestion (SOURCES,
 * OUTPUT_SCHEMA, transform). Here it runs in the browser, in the Pyodide +
 * polars runtime the serverless bundle ships, over a sample of the raw file;
 * its result becomes the committed fixture, so the renders are bound to what
 * the recipe really returns. Nothing loads until "Run" is pressed.
 */
import { useState } from 'react';
import { Alert, Badge, Button, Code, FileButton, Group, Paper, Stack, Text, Title } from '@mantine/core';
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


type RunState =
  | { status: 'idle' }
  | { status: 'running'; phase: string }
  | { status: 'ok'; rows: number; columns: Array<{ name: string; dtype: string }>; stdout: string }
  | { status: 'error'; message: string; stdout?: string };

export default function RecipePanel() {
  const output = useStudioStore((s) => s.output);
  const setOutput = useStudioStore((s) => s.setOutput);
  const setFixtureAt = useStudioStore((s) => s.setFixtureAt);
  const toolId = useStudioStore((s) => s.tool.id);
  const scheme = useComputedColorScheme('light');
  const [run, setRun] = useState<RunState>({ status: 'idle' });
  const recipe = output.recipe;
  if (!recipe) return null;

  const inputs = recipe.inputs ?? [];
  const declared = recipeOutputColumns(recipe.code);

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

  return (
    <Paper withBorder radius="md" p="md" data-testid="recipe-panel">
      <Stack gap="sm">
        <Group justify="space-between">
          <Group gap="xs">
            <Icon icon="mdi:language-python" width={20} />
            <Title order={2} size="h5">
              Recipe <Code>{recipeRefOf(toolId || '<tool>', output).split('/').pop()}</Code>
            </Title>
          </Group>
          {declared && (
            <Group gap={4}>
              <Text size="xs" c="dimmed">
                OUTPUT_SCHEMA:
              </Text>
              {declared.length ? declared.map((c) => <Badge key={c} size="xs" variant="light">{c}</Badge>) : <Text size="xs" c="orange">empty</Text>}
            </Group>
          )}
        </Group>
        <Text size="sm" c="dimmed">
          The raw file is reshaped at ingestion by this module. Drop a sample of the raw file, then run
          the recipe here: its result becomes the committed fixture the renders bind against. The raw
          sample stays in this tab: it is not exported, shared in links or saved with the draft, so add
          it again after a reload.
        </Text>

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

        <Group gap="xs">
          <FileButton onChange={(f) => f.length && void addInputs(f)} multiple accept=".csv,.tsv,.txt,.tab,.tsv.gz">
            {(props) => (
              <Button {...props} size="xs" variant="default" leftSection={<Icon icon="mdi:file-upload-outline" width={14} />} data-testid="recipe-add-input">
                Add raw sample
              </Button>
            )}
          </FileButton>
          {inputs.map((i) => (
            <Badge
              key={i.fileName}
              variant="light"
              rightSection={
                <Icon
                  icon="mdi:close"
                  width={12}
                  style={{ cursor: 'pointer' }}
                  aria-label={`Remove ${i.fileName}`}
                  onClick={() => setOutput({ recipe: { ...recipe, inputs: inputs.filter((x) => x !== i) } })}
                />
              }
            >
              {i.fileName}
            </Badge>
          ))}
        </Group>

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
                ? 'Add a raw sample first, or drop the expected output below as the fixture.'
                : 'Python + polars in your browser (Pyodide); the first run downloads it.'}
          </Text>
        </Group>

        {run.status === 'ok' && (
          <Alert color="teal" variant="light" icon={<Icon icon="mdi:check-circle-outline" />} data-testid="recipe-ok">
            {run.rows} row(s) returned; the fixture now holds them ({run.columns.map((c) => `${c.name} · ${c.dtype}`).join(', ')}).
          </Alert>
        )}
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
      </Stack>
    </Paper>
  );
}
