import { Alert, Anchor, Badge, Group, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { Diagnostic } from '../catalog/diagnostics';

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
  const errors = diagnostics.filter((d) => d.severity === 'error').length;
  const warnings = diagnostics.length - errors;
  if (!diagnostics.length) return null;
  return (
    <Alert
      color={errors ? 'red' : 'yellow'}
      variant="light"
      icon={<Icon icon={errors ? 'mdi:alert-circle' : 'mdi:alert-outline'} />}
      title={
        title ??
        [errors && `${errors} error${errors > 1 ? 's' : ''} CI would reject`, warnings && `${warnings} warning${warnings > 1 ? 's' : ''}`]
          .filter(Boolean)
          .join(' · ')
      }
      data-testid={testId}
      data-errors={errors}
      data-warnings={warnings}
    >
      <Stack gap={6} component="ul" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {diagnostics.map((d, i) => (
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
            <Badge size="xs" variant="light" color={d.severity === 'error' ? 'red' : 'yellow'} style={{ flexShrink: 0, marginTop: 3 }}>
              {d.severity}
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
