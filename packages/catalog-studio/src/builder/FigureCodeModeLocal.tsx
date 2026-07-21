/**
 * catalog-studio's figure Code Mode. depictio's `FigureCodeMode` executes the
 * user's Python on the server (`previewFigure`), which a no-backend app can't
 * do — so this reimplements the same editor UX but runs the code in-browser via
 * Pyodide (`pyodideRunner`). On Execute the resulting figure is written to the
 * builder store's `lastCodeFigure`, which the left preview renders.
 */
import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Group, Stack, Text, useComputedColorScheme } from '@mantine/core';
import { Icon } from '@iconify/react';
import Editor from '@monaco-editor/react';
import { useBuilderStore } from 'depictio-builder/store/useBuilderStore';
import type { ParsedFixture } from '../types';
import { isPyodideReady, runCodeToFigure } from './pyodideRunner';

/** Seed a helpful pandas snippet from the fixture's columns. */
function defaultSnippet(fixture: ParsedFixture): string {
  const numeric = fixture.columns.filter((c) => c.dtype === 'Int64' || c.dtype === 'Float64').map((c) => c.name);
  const cat = fixture.columns.filter((c) => c.dtype === 'String').map((c) => c.name);
  const x = numeric[0] ?? fixture.columns[0]?.name ?? 'x';
  const y = numeric[1] ?? numeric[0] ?? fixture.columns[1]?.name ?? 'y';
  const color = cat[0];
  const colorArg = color ? `, color="${color}"` : '';
  return [
    '# df is a pandas DataFrame of your fixture.',
    '# Assign your Plotly figure to a variable named `fig`.',
    '# Available: df, px (plotly.express), go, pd (pandas), np (numpy).',
    '',
    `fig = px.scatter(df, x="${x}", y="${y}"${colorArg})`,
    '',
    '# Preprocess with pandas if you like, e.g.:',
    '# agg = df.groupby("group")["value"].mean().reset_index()',
    '# fig = px.bar(agg, x="group", y="value")',
  ].join('\n');
}

export default function FigureCodeModeLocal({ fixture }: { fixture: ParsedFixture }) {
  const scheme = useComputedColorScheme('light');
  const codeContent = useBuilderStore((s) => s.codeContent);
  const setCodeContent = useBuilderStore((s) => s.setCodeContent);
  const setLastCodeFigure = useBuilderStore((s) => s.setLastCodeFigure);

  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState<{ color: string; message: string } | null>(null);
  const seeded = useRef(false);

  // Seed a starter snippet once if the editor is empty.
  useEffect(() => {
    if (!seeded.current && !codeContent.trim()) {
      setCodeContent(defaultSnippet(fixture));
    }
    seeded.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const execute = async () => {
    setRunning(true);
    if (!isPyodideReady()) {
      setStatus({ color: 'blue', message: 'Loading the in-browser Python runtime (~20 MB, first use only)…' });
    }
    const result = await runCodeToFigure(codeContent, fixture);
    if (result.error) {
      setStatus({ color: 'red', message: result.error });
    } else if (result.figure) {
      setLastCodeFigure(result.figure);
      setStatus({ color: 'teal', message: 'Figure executed.' });
    }
    setRunning(false);
  };

  const clear = () => {
    setCodeContent('');
    setLastCodeFigure(null);
    setStatus(null);
  };

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Text fw={700} size="sm">
          <Icon icon="tabler:code" width={16} style={{ verticalAlign: 'middle', marginRight: 6 }} />
          Python (Plotly Express)
        </Text>
        <Group gap="xs">
          <Button size="xs" variant="default" onClick={clear} disabled={running}>
            Clear
          </Button>
          <Button size="xs" color="green" loading={running} leftSection={<Icon icon="mdi:play" />} onClick={execute}>
            Execute
          </Button>
        </Group>
      </Group>

      <div style={{ border: '1px solid var(--mantine-color-default-border)', borderRadius: 8, overflow: 'hidden' }}>
        <Editor
          height={320}
          defaultLanguage="python"
          theme={scheme === 'dark' ? 'vs-dark' : 'light'}
          value={codeContent}
          onChange={(v) => setCodeContent(v ?? '')}
          options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false, lineNumbers: 'on' }}
        />
      </div>

      {status && (
        <Alert color={status.color} variant="light" icon={<Icon icon={status.color === 'red' ? 'mdi:alert-circle' : 'mdi:information-outline'} />}>
          <Text size="xs" style={{ whiteSpace: 'pre-wrap', fontFamily: status.color === 'red' ? 'monospace' : undefined }}>
            {status.message}
          </Text>
        </Alert>
      )}

      <Text size="xs" c="dimmed">
        Runs in your browser (Pyodide). <code>df</code> is a pandas DataFrame; depictio's server runs
        the same code against Polars, so complex snippets may render slightly differently there.
      </Text>
    </Stack>
  );
}
