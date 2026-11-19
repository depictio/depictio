import { ActionIcon, Button, Group, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { allOutputs, useStudioStore } from '../state/useStudioStore';
import { isTodo, type Diagnostic } from '../catalog/diagnostics';

/** The tool's outputs as tabs. Every step edits the highlighted one; switching
 *  keeps each output's fixture and renders. */
export default function OutputsBar({ diagnostics }: { diagnostics: Diagnostic[] }) {
  const output = useStudioStore((s) => s.output);
  const fixture = useStudioStore((s) => s.fixture);
  const renders = useStudioStore((s) => s.renders);
  const siblings = useStudioStore((s) => s.siblings);
  const activeIndex = useStudioStore((s) => s.activeIndex);
  const addOutput = useStudioStore((s) => s.addOutput);
  const switchOutput = useStudioStore((s) => s.switchOutput);
  const removeOutput = useStudioStore((s) => s.removeOutput);
  const list = allOutputs({ output, fixture, renders, siblings, activeIndex });
  const mine = (i: number) =>
    diagnostics.filter((d) => d.severity === 'error' && (d.outputIndex === i || (list.length === 1 && d.outputIndex === undefined && !d.path.startsWith('tool'))));
  const errs = (i: number) => mine(i).length;
  // Only "left to fill in" items: grey rather than red.
  const onlyTodos = (i: number) => mine(i).every(isTodo);

  return (
    <Group gap={6} mb="md" wrap="wrap" data-testid="outputs-bar" role="tablist" aria-label="Outputs of this tool">
      <Text size="xs" c="dimmed" mr={4}>
        Outputs
      </Text>
      {list.map((o, i) => (
        <Group key={i} gap={0} wrap="nowrap">
          <Button
            size="compact-sm"
            role="tab"
            aria-selected={i === activeIndex}
            variant={i === activeIndex ? 'filled' : 'default'}
            onClick={() => switchOutput(i)}
            data-testid="output-tab"
            data-slug={o.output.slug}
            rightSection={
              errs(i) ? (
                <Text span size="xs" c={i === activeIndex ? 'white' : onlyTodos(i) ? 'dimmed' : 'red'}>
                  {errs(i)}
                </Text>
              ) : undefined
            }
          >
            {o.output.slug || `output ${i + 1}`}
          </Button>
          {list.length > 1 && (
            <Tooltip label="Remove this output">
              <ActionIcon size="sm" variant="subtle" color="gray" aria-label={`Remove output ${o.output.slug || i + 1}`} onClick={() => removeOutput(i)}>
                <Icon icon="mdi:close" width={14} />
              </ActionIcon>
            </Tooltip>
          )}
        </Group>
      ))}
      <Button size="compact-sm" variant="subtle" leftSection={<Icon icon="mdi:plus" width={14} />} onClick={addOutput} data-testid="add-output">
        Add output
      </Button>
    </Group>
  );
}
