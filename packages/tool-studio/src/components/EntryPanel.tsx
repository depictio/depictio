/**
 * The entry as it stands, beside every step: the files the export will write,
 * the YAML of the one you pick (live), and the checks — each linking to the
 * step (and output) that fixes it. It replaces finding out at Export.
 */
import { useMemo, useState } from 'react';
import { Badge, Group, NavLink, ScrollArea, Stack, Text, Title } from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import { Icon } from '@iconify/react';
import { allOutputs, useStudioStore } from '../state/useStudioStore';
import { generateEntry, genModuleYaml } from '../catalog/yamlGen';
import type { Diagnostic } from '../catalog/diagnostics';
import DiagnosticsList from './DiagnosticsList';

export default function EntryPanel({ diagnostics }: { diagnostics: Diagnostic[] }) {
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
    const out: Array<{ name: string; text: string | null; outputIndex?: number; kind: 'module' | 'output' | 'fixture' }> = [];
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
    });
    return out;
  }, [tool, output, fixture, renders, siblings, activeIndex, existing, newOutputTarget]);

  const current = files.find((f) => f.name === selected && f.text != null) ?? files.find((f) => f.text != null);
  const errorsByOutput = (i?: number) =>
    diagnostics.filter((d) => d.severity === 'error' && (i === undefined ? d.path.startsWith('tool') : d.outputIndex === i || (d.outputIndex === undefined && !d.path.startsWith('tool')))).length;

  const goTo = (step: number, d?: Diagnostic) => {
    if (d?.outputIndex !== undefined && d.outputIndex !== activeIndex) switchOutput(d.outputIndex);
    setStep(step);
  };

  return (
    <ScrollArea h="100%" type="auto" data-testid="entry-panel">
      <Stack gap="sm" p="md">
        <Group justify="space-between">
          <Title order={2} size="h5">
            Entry
          </Title>
          <Badge variant="light" color={diagnostics.some((d) => d.severity === 'error') ? 'red' : 'teal'} data-testid="entry-status">
            {diagnostics.filter((d) => d.severity === 'error').length || 'no'} error(s)
          </Badge>
        </Group>
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
                const errs = f.kind === 'module' ? errorsByOutput(undefined) : f.kind === 'output' ? errorsByOutput(f.outputIndex) : 0;
                return (
                  <NavLink
                    key={`${f.kind}-${f.name}-${f.outputIndex ?? ''}`}
                    label={f.name}
                    active={current?.name === f.name && f.text != null}
                    disabled={f.text == null}
                    leftSection={
                      <Icon
                        icon={f.kind === 'fixture' ? 'mdi:file-delimited-outline' : 'mdi:file-code-outline'}
                        width={16}
                      />
                    }
                    rightSection={
                      errs ? (
                        <Badge size="xs" color="red" variant="light">
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
              <CodeHighlight code={current.text} language="yaml" withCopyButton styles={{ code: { fontSize: 11 } }} />
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
  );
}
