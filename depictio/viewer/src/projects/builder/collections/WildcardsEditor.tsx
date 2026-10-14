/**
 * The wildcards of a scan: `{name}` placeholders in its regex, each read
 * from the matched file's path into a column of the table (the sample from
 * its folder, say). When the ticked examples differ in one folder, the
 * suggestion offers that folder as a `sample` column in one click.
 */
import React from 'react';
import { ActionIcon, Button, Code, Group, Stack, Text, TextInput, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents, wildcardIssues } from 'depictio-react-core';
import type { BuilderSuggestion, BuilderWildcard } from 'depictio-react-core';

import { usesPathWildcard, withPathWildcard } from './dcForm';
import type { DcFormState } from './dcForm';

const MONO = { input: { fontFamily: 'var(--mantine-font-family-monospace)' } };

export const WildcardsEditor: React.FC<{
  form: DcFormState;
  suggestion: BuilderSuggestion | null;
  onChange: (form: DcFormState) => void;
}> = ({ form, suggestion, onChange }) => {
  const accent = useBrandAccents();
  const wildcards = form.dc.wildcards ?? [];
  const issues = wildcardIssues(form.dc);
  const pathWildcard = suggestion?.path_wildcard ?? null;
  const offer = pathWildcard && !usesPathWildcard(form, pathWildcard);
  const set = (next: BuilderWildcard[]) => onChange({ ...form, dc: { ...form.dc, wildcards: next } });

  return (
    <Stack gap={6} data-testid="builder-dc-wildcards">
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Stack gap={0} style={{ minWidth: 0 }}>
          <Text size="sm" fw={500}>
            Wildcards
          </Text>
          <Text size="xs" c="dimmed">
            Each wildcard becomes a column: write <Code fz="xs">{'{name}'}</Code> in the regex where its
            value sits in the path, and the regex that value matches.
          </Text>
        </Stack>
        <Button
          size="compact-xs"
          variant="subtle"
          color="gray"
          leftSection={<Icon icon="mdi:plus" width={14} />}
          onClick={() => set([...wildcards, { name: '', regex: '[^/]+' }])}
          style={{ flexShrink: 0 }}
          data-testid="builder-dc-wildcard-add"
        >
          Add wildcard
        </Button>
      </Group>
      {offer && pathWildcard && (
        <Group gap="xs" wrap="nowrap" data-testid="builder-dc-path-wildcard-offer">
          <Icon icon="mdi:auto-fix" width={15} color={`var(--mantine-color-${accent.secondary}-6)`} style={{ flexShrink: 0 }} />
          <Button
            size="compact-xs"
            variant="light"
            color={accent.secondary}
            onClick={() => onChange(withPathWildcard(form, pathWildcard))}
            data-testid="builder-dc-use-path-wildcard"
          >
            Use the varying folder as a sample column
          </Button>
          <Text size="xs" c="dimmed" ff="monospace" truncate style={{ minWidth: 0 }}>
            {pathWildcard.pattern}
          </Text>
        </Group>
      )}
      {wildcards.map((w, i) => (
        // eslint-disable-next-line react/no-array-index-key
        <Group key={i} gap="xs" wrap="nowrap" align="flex-start" data-testid="builder-dc-wildcard">
          <TextInput
            size="xs"
            placeholder="sample"
            aria-label="Wildcard name"
            value={w.name}
            onChange={(e) => set(wildcards.map((o, j) => (j === i ? { ...o, name: e.currentTarget.value } : o)))}
            styles={MONO}
            spellCheck={false}
            style={{ flex: 1 }}
            data-testid="builder-dc-wildcard-name"
          />
          <TextInput
            size="xs"
            placeholder="[^/]+"
            aria-label="Wildcard regex"
            value={w.regex}
            onChange={(e) => set(wildcards.map((o, j) => (j === i ? { ...o, regex: e.currentTarget.value } : o)))}
            styles={MONO}
            spellCheck={false}
            style={{ flex: 2 }}
            data-testid="builder-dc-wildcard-regex"
          />
          <Tooltip label="Remove the wildcard" withArrow>
            <ActionIcon
              variant="subtle"
              color="red"
              size="md"
              onClick={() => set(wildcards.filter((_, j) => j !== i))}
              aria-label="Remove the wildcard"
            >
              <Icon icon="mdi:close" width={14} />
            </ActionIcon>
          </Tooltip>
        </Group>
      ))}
      {issues.map((message) => (
        <Text key={message} size="xs" c="red" data-testid="builder-dc-wildcard-error">
          {message}
        </Text>
      ))}
    </Stack>
  );
};
