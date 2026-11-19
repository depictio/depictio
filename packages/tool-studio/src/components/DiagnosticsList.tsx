import { Alert, Anchor, Badge, Group, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { isTodo, triage, type Diagnostic } from '../catalog/diagnostics';

const STEP_LABEL = ['Tool', 'Fixture', 'Visualizations'] as const;

/** Errors and warnings with a link to the step that fixes each. Every row
 *  carries `data-code` / `data-severity` / `data-path`, so a test or an agent
 *  can read the result without parsing the prose. */
export default function DiagnosticsList({
  diagnostics,
  onGoTo,
  title,
  testId = 'diagnostics',
  compact = false,
}: {
  testId?: string;
  /** Narrow column: the "Fix in" link goes under the message instead of beside it. */
  compact?: boolean;
  diagnostics: Diagnostic[];
  onGoTo?: (step: number, d: Diagnostic) => void;
  title?: string;
}) {
  const t = triage(diagnostics);
  const errors = t.errors.length;
  const todos = t.todos.length;
  const warnings = t.warnings.length;
  if (!diagnostics.length) return null;
  // Real errors first, then what is left to fill in, then warnings: the list
  // reads as "what is wrong", then "what is next".
  const ordered = [...t.errors, ...t.todos, ...t.warnings];
  // Only "to do" items: a draft in progress, not a broken entry. Neutral grey.
  const color = errors ? 'red' : warnings ? 'yellow' : 'gray';
  return (
    <Alert
      color={color}
      variant="light"
      icon={<Icon icon={errors ? 'mdi:alert-circle' : warnings ? 'mdi:alert-outline' : 'mdi:format-list-checks'} />}
      title={
        title ??
        [
          errors && `${errors} error${errors > 1 ? 's' : ''} CI would reject`,
          todos && `${todos} left to fill in`,
          warnings && `${warnings} warning${warnings > 1 ? 's' : ''}`,
        ]
          .filter(Boolean)
          .join(' · ')
      }
      data-testid={testId}
      data-errors={errors + todos}
      data-todos={todos}
      data-warnings={warnings}
    >
      <Stack gap={6} component="ul" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {ordered.map((d, i) => (
          <Group
            key={`${d.code}-${d.path}-${i}`}
            component="li"
            gap="xs"
            wrap="nowrap"
            align="flex-start"
            data-testid="diagnostic"
            data-code={d.code}
            data-severity={d.severity}
            data-path={d.path}
          >
            <Badge
              size="xs"
              variant="light"
              color={isTodo(d) ? 'gray' : d.severity === 'error' ? 'red' : 'yellow'}
              style={{ flexShrink: 0, marginTop: 3 }}
            >
              {isTodo(d) ? 'to do' : d.severity}
            </Badge>
            <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
              <Text size="sm">
                {d.message}{' '}
                <Text span size="xs" c="dimmed" ff="monospace">
                  {d.code}
                </Text>
              </Text>
              {onGoTo && compact && <FixLink d={d} onGoTo={onGoTo} />}
            </Stack>
            {onGoTo && !compact && <FixLink d={d} onGoTo={onGoTo} />}
          </Group>
        ))}
      </Stack>
    </Alert>
  );
}

function FixLink({ d, onGoTo }: { d: Diagnostic; onGoTo: (step: number, d: Diagnostic) => void }) {
  return (
    <Anchor component="button" type="button" size="xs" onClick={() => onGoTo(d.step, d)} style={{ flexShrink: 0, textAlign: 'left' }}>
      Fix in {STEP_LABEL[d.step]}
      {d.outputIndex !== undefined ? ` (output ${d.outputIndex + 1})` : ''}
    </Anchor>
  );
}
