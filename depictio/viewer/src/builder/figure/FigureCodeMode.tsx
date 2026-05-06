/**
 * Figure code mode panel — right-column controls only.
 *
 * Mirrors the structure Dash builds in figure_component/callbacks/design.py
 * for the code-mode interface: macOS-styled editor, Execute / Clear buttons,
 * and four info alerts (Status / Available Columns / Dataset & Figure Usage
 * / Code Examples). Preview goes to the left-column FigurePreview via the
 * `lastCodeFigure` slot in the builder store — there's no live debounce,
 * preview only updates when Execute is clicked.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Anchor,
  Button,
  Code,
  Collapse,
  Group,
  Stack,
  Text,
} from '@mantine/core';
import Editor from '@monaco-editor/react';
import { Icon } from '@iconify/react';
import { previewFigure } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import { useColorScheme } from '../../hooks/useColorScheme';
import { buildMetadata } from '../buildMetadata';

const SAMPLE_CODE = `# Enter your Python/Plotly code here...
# Available: df (DataFrame), px (plotly.express), pd (pandas), pl (polars)
#
# CONSTRAINT: Use 'df_modified' for data preprocessing (single line):
# df_modified = df.to_pandas().groupby('column').sum().reset_index()
# fig = px.pie(df_modified, values='value_col', names='name_col')
#
# Simple example (no preprocessing):
# fig = px.scatter(df, x='your_x_column', y='your_y_column', color='your_color_column')
`;

const EDITOR_FONT_FAMILY =
  "Fira Code, JetBrains Mono, Monaco, Consolas, 'Courier New', monospace";

const CODE_EXAMPLES: Array<{ title: string; code: string }> = [
  {
    title: 'Scatter Plot',
    code: "fig = px.scatter(df, x='sepal.length', y='sepal.width', color='variety', title='Sepal Dimensions')",
  },
  {
    title: 'Histogram',
    code: "fig = px.histogram(df, x='petal.length', color='variety', title='Petal Length Distribution')",
  },
  {
    title: 'Box Plot',
    code: "fig = px.box(df, x='variety', y='petal.width', title='Petal Width by Variety')",
  },
  {
    title: 'Pie Chart',
    code: "df_modified = df.to_pandas().groupby('variety')['sepal.length'].sum().reset_index()\nfig = px.pie(df_modified, values='sepal.length', names='variety', title='Sepal Length Distribution by Variety')",
  },
  {
    title: 'Pandas Processing',
    code: "df_modified = df.to_pandas().groupby('variety')['sepal.width'].mean().reset_index()\nfig = px.bar(df_modified, x='variety', y='sepal.width', color='variety', title='Average Sepal Width by Variety')",
  },
  {
    title: 'Polars Processing',
    code: "df_modified = df.group_by('variety').agg(pl.col('petal.length').mean())\nfig = px.bar(df_modified, x='variety', y='petal.length', color='variety', title='Average Petal Length by Variety')",
  },
  {
    title: 'Custom Styling',
    code: "fig = px.scatter(df, x='sepal.length', y='petal.length', color='variety', size='sepal.width', hover_data=['petal.width'])\nfig.update_layout(title='Sepal vs Petal Length', xaxis_title='Sepal Length (cm)', yaxis_title='Petal Length (cm)')",
  },
];

const FigureCodeMode: React.FC = () => {
  const state = useBuilderStore();
  const codeContent = state.codeContent;
  const setCodeContent = state.setCodeContent;
  const dictKwargs = state.dictKwargs;
  const visuType = state.visuType;
  const cols = state.cols;
  const codeStatus = state.codeStatus;
  const setCodeStatus = state.setCodeStatus;
  const setLastCodeFigure = state.setLastCodeFigure;
  const { colorScheme } = useColorScheme();

  const [executing, setExecuting] = useState(false);
  const [examplesOpen, setExamplesOpen] = useState(false);
  const initialised = useRef(false);

  // Seed the editor on first mount: prefer existing code; otherwise generate
  // a starter from current visu_type + dict_kwargs (matches Dash's
  // convert_ui_params_to_code), or fall back to the placeholder block.
  useEffect(() => {
    if (initialised.current) return;
    initialised.current = true;
    if (codeContent && codeContent.trim()) return;
    const hasUiKwargs = Object.values(dictKwargs).some(
      (v) => v != null && v !== '',
    );
    if (hasUiKwargs) {
      const args = Object.entries(dictKwargs)
        .filter(([, v]) => v != null && v !== '')
        .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
        .join(', ');
      setCodeContent(`fig = px.${visuType}(df, ${args})`);
    } else {
      setCodeContent(SAMPLE_CODE);
    }
  }, [codeContent, dictKwargs, visuType, setCodeContent]);

  const columnsListing = useMemo(() => {
    if (!cols.length) {
      return 'No columns loaded yet — pick a data collection in the Data Source step.';
    }
    return cols.map((c) => `${c.name} (${c.type})`).join(', ');
  }, [cols]);

  const handleExecute = () => {
    if (!state.wfId || !state.dcId) {
      setCodeStatus({
        title: 'Error',
        color: 'red',
        message: 'Pick a workflow + data collection first.',
      });
      return;
    }
    if (!codeContent.trim()) {
      setCodeStatus({
        title: 'Error',
        color: 'red',
        message: 'Editor is empty.',
      });
      return;
    }
    setExecuting(true);
    setCodeStatus({
      title: 'Running',
      color: 'blue',
      message: 'Executing your code…',
    });
    const meta = {
      ...buildMetadata(state),
      mode: 'code',
      code_content: codeContent,
    };
    previewFigure({ metadata: meta })
      .then((res) => {
        const fig = res.figure;
        if (!fig) {
          setCodeStatus({
            title: 'Error',
            color: 'red',
            message: 'No figure returned from the server.',
          });
          setLastCodeFigure(null);
          return;
        }
        setLastCodeFigure({
          data: (fig.data as unknown[]) ?? [],
          layout: (fig.layout as Record<string, unknown>) ?? {},
        });
        // The backend signals a code-execution failure by setting
        // `metadata.error` and returning an annotation-only "error figure".
        // Surface the actual Plotly message in the Status alert (red) instead
        // of the previous always-green "Success" claim.
        const errMsg = (res.metadata as { error?: string } | undefined)?.error;
        if (errMsg) {
          setCodeStatus({
            title: 'Error',
            color: 'red',
            message: errMsg,
          });
          return;
        }
        const traceCount = Array.isArray(fig.data) ? fig.data.length : 0;
        setCodeStatus({
          title: 'Success',
          color: 'green',
          message: `Code executed successfully! Preview shown on the left. (${traceCount} trace${
            traceCount === 1 ? '' : 's'
          })`,
        });
      })
      .catch((err) => {
        setLastCodeFigure(null);
        setCodeStatus({
          title: 'Error',
          color: 'red',
          message: err instanceof Error ? err.message : String(err),
        });
      })
      .finally(() => setExecuting(false));
  };

  const handleClear = () => {
    setCodeContent(SAMPLE_CODE);
    setLastCodeFigure(null);
    setCodeStatus({
      title: 'Ready',
      color: 'blue',
      message:
        "Enter code and click 'Execute Code' to see preview on the left.",
    });
  };

  return (
    <Stack gap="sm" style={{ padding: '0 4px' }}>
      <Group justify="space-between" align="center">
        <Text size="sm" fw={700} c="dimmed">
          Python Code:
        </Text>
        <Group gap="xs">
          <Button
            size="xs"
            color="green"
            variant="filled"
            leftSection={<Icon icon="mdi:play" width={14} />}
            onClick={handleExecute}
            loading={executing}
          >
            Execute Code
          </Button>
          <Button
            size="xs"
            color="gray"
            variant="outline"
            leftSection={<Icon icon="mdi:broom" width={14} />}
            onClick={handleClear}
          >
            Clear
          </Button>
        </Group>
      </Group>

      <div
        style={{
          border: '1px solid var(--mantine-color-default-border)',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '6px 10px',
            background: 'var(--mantine-color-gray-1)',
            borderBottom: '1px solid var(--mantine-color-default-border)',
            fontFamily: EDITOR_FONT_FAMILY,
            fontSize: 11,
          }}
        >
          <span
            style={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              background: '#ff5f57',
              display: 'inline-block',
            }}
          />
          <span
            style={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              background: '#ffbd2e',
              display: 'inline-block',
            }}
          />
          <span
            style={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              background: '#28ca42',
              display: 'inline-block',
            }}
          />
          <span style={{ marginLeft: 12, color: 'var(--mantine-color-gray-7)' }}>
            main.py
          </span>
          <span style={{ flex: 1 }} />
          <span style={{ color: 'var(--mantine-color-gray-6)' }}>Python</span>
          <span style={{ color: 'var(--mantine-color-gray-6)' }}>UTF-8</span>
        </div>
        <Editor
          height="200px"
          defaultLanguage="python"
          theme={colorScheme === 'dark' ? 'vs-dark' : 'vs-light'}
          value={codeContent}
          onChange={(v) => setCodeContent(v ?? '')}
          options={{
            minimap: { enabled: false },
            fontSize: 11,
            fontFamily: EDITOR_FONT_FAMILY,
            scrollBeyondLastLine: false,
            tabSize: 4,
            insertSpaces: true,
            wordWrap: 'on',
            renderLineHighlight: 'line',
          }}
        />
      </div>

      <Alert
        color={codeStatus.color}
        title={codeStatus.title}
        icon={<Icon icon="mdi:check-circle" width={16} />}
        variant="light"
      >
        {codeStatus.color === 'red' ? (
          <Code block>{codeStatus.message}</Code>
        ) : (
          <Text size="xs">{codeStatus.message}</Text>
        )}
      </Alert>

      <Alert
        color="teal"
        title="Available Columns"
        icon={<Icon icon="mdi:table" width={16} />}
        variant="light"
      >
        <Text size="xs" style={{ fontFamily: EDITOR_FONT_FAMILY }}>
          {columnsListing}
        </Text>
      </Alert>

      <Alert
        color="blue"
        title="Dataset & Figure Usage"
        icon={<Icon icon="mdi:database" width={16} />}
        variant="light"
      >
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
          <li>
            <code>df</code> — your dataset (Polars DataFrame) — READ ONLY
          </li>
          <li>
            <code>df_modified</code> — use for preprocessing (single line only)
          </li>
          <li>
            <code>fig</code> — your final Plotly figure (required)
          </li>
          <li>
            ✅ Valid: <code>fig = px.scatter(df, ...)</code> or{' '}
            <code>fig = px.pie(df_modified, ...)</code>
          </li>
          <li>
            ❌ Invalid: multiple preprocessing lines or wrong variable names
          </li>
        </ul>
      </Alert>

      <Alert
        color="teal"
        title="Code Examples (Iris Dataset)"
        icon={<Icon icon="mdi:code-tags" width={16} />}
        variant="light"
      >
        <Anchor
          component="button"
          type="button"
          size="xs"
          c="teal"
          onClick={() => setExamplesOpen((o) => !o)}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            marginBottom: 6,
          }}
        >
          <Icon icon="mdi:code-braces" width={14} />
          {examplesOpen ? 'Hide Code Examples' : 'Show Code Examples'}
        </Anchor>
        <Collapse in={examplesOpen}>
          <Stack gap="xs">
            {CODE_EXAMPLES.map((ex) => (
              <div key={ex.title}>
                <Text size="xs" fw={700} c="teal">
                  {ex.title}
                </Text>
                <Code
                  block
                  style={{ fontFamily: EDITOR_FONT_FAMILY, fontSize: 11 }}
                >
                  {ex.code}
                </Code>
              </div>
            ))}
          </Stack>
        </Collapse>
      </Alert>
    </Stack>
  );
};

export default FigureCodeMode;
