/**
 * Figure code mode panel — right-column controls only.
 *
 * Mirrors the structure Dash builds in figure_component/callbacks/design.py
 * for the code-mode interface: macOS-styled editor, Execute / Clear buttons,
 * and info sections. Preview goes to the left-column FigurePreview via the
 * `lastCodeFigure` slot in the builder store — there's no live debounce,
 * preview only updates when Execute is clicked.
 *
 * Help is grouped into a single collapsible Accordion below the editor so
 * the panel stays compact when users are mid-code. The status alert stays
 * always-visible because it surfaces the last execution result.
 *
 * Editor height + font size persist in localStorage so a user's preferred
 * setup survives page reloads without bloating the builder store.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Accordion,
  Alert,
  Anchor,
  Badge,
  Button,
  Code,
  Group,
  ScrollArea,
  Stack,
  Table,
  Text,
  Tooltip,
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

// localStorage keys + sane defaults / bounds. Kept private to this file; if
// other builders want the same pattern, lift to a shared hook later.
const LS_FONT_SIZE = 'depictio.code_mode.font_size';
const LS_EDITOR_HEIGHT = 'depictio.code_mode.editor_height';
const FONT_MIN = 9;
const FONT_MAX = 22;
const FONT_DEFAULT = 11;
const HEIGHT_MIN = 180;
const HEIGHT_MAX = 800;
const HEIGHT_DEFAULT = 280;

function readNumberPref(key: string, fallback: number, min: number, max: number): number {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (raw == null) return fallback;
    const n = Number(raw);
    if (!Number.isFinite(n)) return fallback;
    return Math.min(max, Math.max(min, Math.round(n)));
  } catch {
    return fallback;
  }
}

function writeNumberPref(key: string, value: number) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, String(value));
  } catch {
    // ignore quota / private mode
  }
}

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
  const initialised = useRef(false);

  // Editor preferences — initialised from localStorage on mount so a user's
  // last setup is preserved across reloads. The setters write straight back
  // through `writeNumberPref` so updates persist without a separate effect.
  const [fontSize, setFontSizeState] = useState<number>(() =>
    readNumberPref(LS_FONT_SIZE, FONT_DEFAULT, FONT_MIN, FONT_MAX),
  );
  const [editorHeight, setEditorHeightState] = useState<number>(() =>
    readNumberPref(LS_EDITOR_HEIGHT, HEIGHT_DEFAULT, HEIGHT_MIN, HEIGHT_MAX),
  );
  const setFontSize = (next: number) => {
    const clamped = Math.min(FONT_MAX, Math.max(FONT_MIN, next));
    setFontSizeState(clamped);
    writeNumberPref(LS_FONT_SIZE, clamped);
  };
  const setEditorHeight = (next: number) => {
    const clamped = Math.min(HEIGHT_MAX, Math.max(HEIGHT_MIN, Math.round(next)));
    setEditorHeightState(clamped);
    writeNumberPref(LS_EDITOR_HEIGHT, clamped);
  };

  // Observe the resizable wrapper so dragging the corner persists the new
  // height. CSS `resize: vertical` mutates the element style directly — we
  // pick it up via ResizeObserver and round-trip to localStorage.
  const editorWrapRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = editorWrapRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const h = entries[0]?.contentRect?.height;
      if (typeof h === 'number' && Math.abs(h - editorHeight) > 1) {
        setEditorHeight(h);
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  // Type → Mantine color mapping. The colors mirror the Dash side's
  // column-type chips so the same numeric/string/boolean palette appears
  // wherever a DC column is rendered (data preview, builder dropdowns, here).
  const colorForType = (t: string): string => {
    const lower = (t || '').toLowerCase();
    if (lower.includes('int') || lower.includes('float') || lower.includes('num')) {
      return 'blue';
    }
    if (lower.includes('bool')) return 'orange';
    if (lower.includes('date') || lower.includes('time')) return 'grape';
    if (lower.includes('str') || lower.includes('utf') || lower.includes('object')) {
      return 'teal';
    }
    return 'gray';
  };

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
      <Group justify="space-between" align="center" wrap="nowrap">
        <Text size="sm" fw={700} c="dimmed">
          Python Code:
        </Text>
        <Group gap={6} wrap="nowrap">
          <Tooltip label="Decrease font size" withArrow>
            <ActionIcon
              size="sm"
              variant="default"
              onClick={() => setFontSize(fontSize - 1)}
              disabled={fontSize <= FONT_MIN}
              aria-label="Decrease editor font size"
            >
              <Icon icon="mdi:format-font-size-decrease" width={14} />
            </ActionIcon>
          </Tooltip>
          <Text size="xs" c="dimmed" style={{ minWidth: 24, textAlign: 'center' }}>
            {fontSize}px
          </Text>
          <Tooltip label="Increase font size" withArrow>
            <ActionIcon
              size="sm"
              variant="default"
              onClick={() => setFontSize(fontSize + 1)}
              disabled={fontSize >= FONT_MAX}
              aria-label="Increase editor font size"
            >
              <Icon icon="mdi:format-font-size-increase" width={14} />
            </ActionIcon>
          </Tooltip>
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
        {/* Resizable host. `resize: vertical` lets the user drag the corner
         *  to grow / shrink the editor; ResizeObserver above persists the
         *  new height. Monaco fills 100% of this wrapper. */}
        <div
          ref={editorWrapRef}
          style={{
            height: editorHeight,
            minHeight: HEIGHT_MIN,
            maxHeight: HEIGHT_MAX,
            resize: 'vertical',
            overflow: 'hidden',
          }}
        >
          <Editor
            height="100%"
            defaultLanguage="python"
            theme={colorScheme === 'dark' ? 'vs-dark' : 'vs-light'}
            value={codeContent}
            onChange={(v) => setCodeContent(v ?? '')}
            options={{
              minimap: { enabled: false },
              fontSize,
              fontFamily: EDITOR_FONT_FAMILY,
              scrollBeyondLastLine: false,
              tabSize: 4,
              insertSpaces: true,
              wordWrap: 'on',
              renderLineHighlight: 'line',
              automaticLayout: true,
            }}
          />
        </div>
      </div>

      {/* Always-visible status alert — last execution result lives here so
       *  users see error tracebacks without expanding a section. */}
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

      {/* Help — collapsible, all closed by default so the panel stays compact.
       *  `multiple` lets the user keep more than one section open if they're
       *  cross-referencing (e.g., columns + examples while writing code). */}
      <Accordion variant="separated" radius="md" multiple defaultValue={[]}>
        <Accordion.Item value="about">
          <Accordion.Control icon={<Icon icon="mdi:shield-check" width={18} />}>
            <Text fw={700} size="sm">
              About Code Mode
            </Text>
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              <Text size="xs">
                Code Mode lets you author the figure as Python code instead of
                clicking through visualization parameters. Your code runs
                server-side inside a sandbox built on{' '}
                <Anchor
                  href="https://restrictedpython.readthedocs.io/"
                  target="_blank"
                  rel="noreferrer"
                  size="xs"
                >
                  RestrictedPython
                </Anchor>{' '}
                (Zope Foundation) — the source is at{' '}
                <code>depictio/dash/modules/figure_component/simple_code_executor.py</code>.
              </Text>

              <Text size="xs" fw={700}>
                Pre-loaded modules (full names)
              </Text>
              {/* One row per module — alias chip, full dotted name, short
               *  description. Flat Stack of Groups with nowrap so the row
               *  never wraps onto two lines; the description takes the
               *  remaining width and truncates via `lineClamp={1}` rather
               *  than wrapping. Avoids the previous Table layout which
               *  multi-row'd each module when the description was long. */}
              <Stack gap={4}>
                {[
                  {
                    alias: 'px',
                    full: 'plotly.express',
                    desc: 'High-level chart constructors (scatter, bar, …)',
                  },
                  {
                    alias: 'go',
                    full: 'plotly.graph_objects',
                    desc: 'Low-level trace + layout primitives',
                  },
                  {
                    alias: 'pl',
                    full: 'polars',
                    desc: 'Native dataframe library — df is a Polars DataFrame',
                  },
                  {
                    alias: 'pd',
                    full: 'pandas',
                    desc: 'For df.to_pandas() conversions / pie-chart preprocessing',
                  },
                  {
                    alias: 'np',
                    full: 'numpy',
                    desc: 'Numeric helpers (np.log, array ops)',
                  },
                ].map((m) => (
                  <Group key={m.alias} gap="sm" wrap="nowrap" align="center">
                    <Code style={{ minWidth: 28, textAlign: 'center' }}>
                      {m.alias}
                    </Code>
                    <Text size="xs" c="dimmed" style={{ width: 14 }}>
                      →
                    </Text>
                    <Code style={{ minWidth: 168, fontFamily: EDITOR_FONT_FAMILY }}>
                      {m.full}
                    </Code>
                    <Text
                      size="xs"
                      c="dimmed"
                      lineClamp={1}
                      style={{ flex: 1, minWidth: 0 }}
                    >
                      {m.desc}
                    </Text>
                  </Group>
                ))}
              </Stack>

              <Text size="xs" fw={700}>
                Safe built-ins (whitelisted, not the full <Code>builtins</Code> module)
              </Text>
              <Group gap={4} wrap="wrap">
                {['len', 'range', 'list', 'dict', 'tuple', 'enumerate', 'zip'].map((b) => (
                  <Badge key={b} variant="light" color="gray" size="sm">
                    <Code style={{ background: 'transparent', padding: 0 }}>{b}</Code>
                  </Badge>
                ))}
              </Group>
              <Text size="xs" c="dimmed">
                Anything else from <Code>builtins</Code> — including <Code>print</Code>,{' '}
                <Code>input</Code>, <Code>type</Code>, <Code>__import__</Code>,{' '}
                <Code>open</Code> — comes from{' '}
                <Code>RestrictedPython.Guards.safe_builtins</Code>, which omits all
                I/O, introspection, and import primitives.
              </Text>

              <Text size="xs" fw={700}>
                Variables in scope
              </Text>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
                <li>
                  <Code>df</Code> — your data collection as a Polars
                  DataFrame. Read-only: an AST pre-pass rejects code that
                  rebinds <Code>df</Code> (<Code>df = …</Code>, <Code>df += …</Code>).
                </li>
                <li>
                  <Code>df_modified</Code> — optional single preprocessing
                  statement (e.g. <Code>df_modified = df.to_pandas().groupby(…)</Code>).
                </li>
                <li>
                  <Code>fig</Code> — the Plotly figure your code MUST produce. The
                  preview pane renders <Code>fig</Code> after execution.
                </li>
              </ul>

              <Text size="xs" fw={700}>
                What RestrictedPython blocks at compile time
              </Text>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
                <li>
                  <Code>import …</Code> / <Code>from … import …</Code> — only
                  modules already in scope are usable.
                </li>
                <li>
                  <Code>exec</Code>, <Code>eval</Code>, <Code>compile</Code> —
                  no dynamic code execution.
                </li>
                <li>
                  Direct access to dunder attributes (<Code>__class__</Code>,{' '}
                  <Code>__globals__</Code>, <Code>__subclasses__</Code>, …) — the
                  compiler rewrites attribute access through a guarded getter
                  that rejects names starting with <Code>_</Code>.
                </li>
                <li>
                  File I/O, subprocess, network sockets — none of{' '}
                  <Code>open</Code>, <Code>os</Code>, <Code>sys</Code>,{' '}
                  <Code>subprocess</Code>, <Code>socket</Code>,{' '}
                  <Code>requests</Code>, <Code>urllib</Code> are reachable.
                </li>
              </ul>

              <Text size="xs" fw={700}>
                How safe is this?
              </Text>
              <Text size="xs">
                Honest answer: <strong>safe enough for authenticated users in
                your own deployment, not safe for arbitrary public input.</strong>
                {' '}RestrictedPython has had 20+ years of hardening at Zope and
                blocks every well-known Python-sandbox escape gadget (dunder
                attribute walks, <Code>__import__</Code> chains, raw bytecode).
                But two design choices in this executor widen the attack
                surface:
              </Text>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
                <li>
                  <Code>safe_getattr</Code> / <Code>safe_setattr</Code> in
                  this codebase delegate to the real <Code>getattr</Code> /{' '}
                  <Code>setattr</Code> (not RestrictedPython's stricter
                  defaults) so pandas / polars method chains work. That means
                  any attribute that doesn't start with <Code>_</Code> is
                  reachable on every exposed object.
                </li>
                <li>
                  Pandas and Polars are large API surfaces. Methods like{' '}
                  <Code>DataFrame.to_csv(path)</Code>,{' '}
                  <Code>DataFrame.to_pickle(path)</Code>, or{' '}
                  <Code>polars.read_csv(path)</Code> sit on the exposed objects
                  and are not individually blacklisted — a determined
                  authenticated user could write to disk via the server
                  process's filesystem permissions.
                </li>
              </ul>
              <Text size="xs">
                Practical posture: treat code mode as "trusted user runs
                trusted code as the server user." If you ever expose code mode
                to anonymous / adversarial users, add a second layer
                underneath (container with read-only FS, seccomp filter, or a
                separate worker process with dropped capabilities) — don't
                rely on RestrictedPython alone.
              </Text>
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="columns">
          <Accordion.Control icon={<Icon icon="mdi:table" width={18} />}>
            <Text fw={700} size="sm">
              Available Columns{' '}
              {cols.length > 0 && (
                <Text component="span" c="dimmed" size="xs" fw={400}>
                  ({cols.length})
                </Text>
              )}
            </Text>
          </Accordion.Control>
          <Accordion.Panel>
            {cols.length === 0 ? (
              <Text size="xs" c="dimmed">
                No columns loaded yet — pick a data collection in the Data
                Source step.
              </Text>
            ) : (
              <ScrollArea.Autosize mah={260}>
                <Table
                  withRowBorders
                  highlightOnHover
                  verticalSpacing={4}
                  horizontalSpacing="sm"
                  styles={{ td: { padding: '4px 8px' }, th: { padding: '4px 8px' } }}
                >
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>
                        <Text size="xs" fw={600} c="dimmed">
                          Name
                        </Text>
                      </Table.Th>
                      <Table.Th>
                        <Text size="xs" fw={600} c="dimmed">
                          Type
                        </Text>
                      </Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {cols.map((c) => (
                      <Table.Tr key={c.name}>
                        <Table.Td>
                          <Code style={{ fontFamily: EDITOR_FONT_FAMILY }}>
                            {c.name}
                          </Code>
                        </Table.Td>
                        <Table.Td>
                          <Badge
                            variant="light"
                            color={colorForType(c.type)}
                            size="sm"
                            radius="sm"
                          >
                            {c.type}
                          </Badge>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea.Autosize>
            )}
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="variables">
          <Accordion.Control icon={<Icon icon="mdi:variable" width={18} />}>
            <Text fw={700} size="sm">
              Variables & Output
            </Text>
          </Accordion.Control>
          <Accordion.Panel>
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
                Valid: <code>fig = px.scatter(df, ...)</code> or{' '}
                <code>fig = px.pie(df_modified, ...)</code>
              </li>
              <li>
                Invalid: multiple preprocessing lines or reassigning{' '}
                <code>df</code>
              </li>
            </ul>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="examples">
          <Accordion.Control icon={<Icon icon="mdi:code-tags" width={18} />}>
            <Text fw={700} size="sm">
              Code Examples (Iris Dataset)
            </Text>
          </Accordion.Control>
          <Accordion.Panel>
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
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
};

export default FigureCodeMode;
