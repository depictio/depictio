/**
 * The entry as it stands, beside every step: the files the export will write,
 * the YAML of the one you pick (live), and the checks — each linking to the
 * step (and output) that fixes it. It replaces finding out at Export.
 */
import { useMemo, useState } from 'react';
import { Badge, NavLink, ScrollArea, Stack, Text, Tooltip } from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import { Icon } from '@iconify/react';
import { allOutputs, useStudioStore } from '../state/useStudioStore';
import { generateEntry, genModuleYaml } from '../catalog/yamlGen';
import { isTodo, type Diagnostic } from '../catalog/diagnostics';
import DiagnosticsList from './DiagnosticsList';
import { ShieldCheck, X } from 'lucide-react';
import { PRIVACY_LINE } from './AppHeader';

export default function EntryPanel({
  diagnostics,
  onClose,
}: {
  diagnostics: Diagnostic[];
  /** Hides the panel (its key in the step's toolbar brings it back). */
  onClose?: () => void;
}) {
  const tool = useStudioStore((s) => s.tool);
  const output = useStudioStore((s) => s.output);
  const fixture = useStudioStore((s) => s.fixture);
  const renders = useStudioStore((s) => s.renders);
  const siblings = useStudioStore((s) => s.siblings);
  const activeIndex = useStudioStore((s) => s.activeIndex);
  const existing = useStudioStore((s) => s.existing);
  const newOutputTarget = useStudioStore((s) => s.newOutputTarget);
  const setStep = useStudioStore((s) => s.setStep);
  const switchOutput = useStudioStore((s) => s.switchOutput);
  const [selected, setSelected] = useState<string>('module.yaml');

  const files = useMemo(() => {
    const out: Array<{ name: string; text: string | null; outputIndex?: number; kind: 'module' | 'output' | 'fixture' | 'recipe' }> = [];
    if (existing) return out;
    if (!newOutputTarget && tool.id) out.push({ name: 'module.yaml', text: genModuleYaml(tool), kind: 'module' });
    allOutputs({ output, fixture, renders, siblings, activeIndex }).forEach((o, i) => {
      const slug = o.output.slug || `output-${i + 1}`;
      const e = generateEntry({
        tool,
        output: { ...o.output, slug },
        fixtureFileName: o.fixture?.fileName ?? `${slug}.csv`,
        fixtureContent: o.fixture?.raw ?? '',
        renders: o.renders,
      });
      out.push({ name: e.outputYamlName, text: e.outputYaml, outputIndex: i, kind: 'output' });
      out.push({ name: o.fixture?.fileName ?? `${slug}.csv (missing)`, text: null, outputIndex: i, kind: 'fixture' });
      if (e.recipeFile) out.push({ name: e.recipeFile.name, text: e.recipeFile.content, outputIndex: i, kind: 'recipe' });
    });
    return out;
  }, [tool, output, fixture, renders, siblings, activeIndex, existing, newOutputTarget]);

  const current = files.find((f) => f.name === selected && f.text != null) ?? files.find((f) => f.text != null);
  const inFile = (d: Diagnostic, i?: number) =>
    i === undefined ? d.path.startsWith('tool') : d.outputIndex === i || (d.outputIndex === undefined && !d.path.startsWith('tool'));
  /** Per file: real errors (red) and items left to fill in (grey). */
  const countsByOutput = (i?: number) => {
    const mine = diagnostics.filter((d) => d.severity === 'error' && inFile(d, i));
    const todos = mine.filter(isTodo).length;
    return { errors: mine.length - todos, todos };
  };

  const goTo = (step: number, d?: Diagnostic) => {
    if (d?.outputIndex !== undefined && d.outputIndex !== activeIndex) switchOutput(d.outputIndex);
    setStep(step);
  };

  const errorCount = diagnostics.filter((d) => d.severity === 'error' && !isTodo(d)).length;
  const todoCount = diagnostics.filter(isTodo).length;

  return (
    <div className="ts-panel-card">
      {/* The dashboards' side-panel head (layout.css .hy-drawer-head): the
          title, its count, then the close key. */}
      <div className="hy-drawer-head">
        <span className="hy-drawer-title">Entry</span>
        <Badge variant="light" color={errorCount ? 'red' : todoCount ? 'gray' : 'teal'} data-testid="entry-status">
          {errorCount
            ? `${errorCount} error${errorCount > 1 ? 's' : ''}`
            : todoCount
              ? `${todoCount} to do`
              : 'Ready'}
        </Badge>
        <span className="hy-flex" />
        {onClose && (
          <Tooltip label="Hide the entry" withArrow openDelay={250}>
            <button type="button" className="hy-close" onClick={onClose} aria-label="Hide the entry panel">
              <X size={18} strokeWidth={1.8} aria-hidden />
            </button>
          </Tooltip>
        )}
      </div>
    <ScrollArea className="ts-panel-body" type="auto" data-testid="entry-panel">
      <Stack gap="sm" p="md">
        {existing ? (
          <Text size="sm" c="dimmed">
            Appending to <code>{existing.yamlPath}</code>; the updated file is shown at Export.
          </Text>
        ) : (
          <>
            <Text size="xs" c="dimmed" ff="monospace">
              depictio/catalog/{tool.id || '<tool>'}/
            </Text>
            <Stack gap={0}>
              {files.map((f) => {
                const c = f.kind === 'module' ? countsByOutput(undefined) : f.kind === 'output' ? countsByOutput(f.outputIndex) : { errors: 0, todos: 0 };
                const errs = c.errors + c.todos;
                return (
                  <NavLink
                    key={`${f.kind}-${f.name}-${f.outputIndex ?? ''}`}
                    label={f.name}
                    active={current?.name === f.name && f.text != null}
                    disabled={f.text == null}
                    leftSection={
                      <Icon
                        icon={f.kind === 'fixture' ? 'mdi:file-delimited-outline' : f.kind === 'recipe' ? 'mdi:language-python' : 'mdi:file-code-outline'}
                        width={16}
                      />
                    }
                    rightSection={
                      errs ? (
                        <Badge size="xs" color={c.errors ? 'red' : 'gray'} variant="light">
                          {errs}
                        </Badge>
                      ) : f.outputIndex === activeIndex && f.kind === 'output' && files.filter((x) => x.kind === 'output').length > 1 ? (
                        <Badge size="xs" variant="light">
                          editing
                        </Badge>
                      ) : null
                    }
                    onClick={() => f.text != null && setSelected(f.name)}
                    py={4}
                    data-testid="entry-file"
                    data-file={f.name}
                  />
                );
              })}
            </Stack>
            {current?.text && (
              <CodeHighlight code={current.text} language={current.kind === 'recipe' ? 'python' : 'yaml'} withCopyButton styles={{ code: { fontSize: 11 } }} />
            )}
          </>
        )}
        {diagnostics.length > 0 ? (
          <DiagnosticsList diagnostics={diagnostics} onGoTo={goTo} testId="entry-diagnostics" compact />
        ) : (
          <Text size="sm" c="teal" data-testid="entry-clean">
            <Icon icon="mdi:check-circle-outline" width={14} /> Every client check passes.
          </Text>
        )}
      </Stack>
    </ScrollArea>
      <div className="ts-panel-foot">
        <ShieldCheck size={14} strokeWidth={1.8} aria-hidden />
        <span>{PRIVACY_LINE}</span>
      </div>
    </div>
  );
}
