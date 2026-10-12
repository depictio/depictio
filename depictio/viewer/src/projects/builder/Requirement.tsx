/**
 * What the builder forms share to say what must be filled in and what need
 * not: a Required / Optional badge, a section head carrying it, and a block
 * that folds its optional fields away (opened at first only when one of them
 * already holds a value).
 */
import React, { useState } from 'react';
import { Badge, Collapse, Group, Paper, Stack, Text, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';

export type RequirementKind = 'required' | 'optional';

export const RequirementBadge: React.FC<{ kind: RequirementKind }> = ({ kind }) => {
  const accent = useBrandAccents();
  return kind === 'required' ? (
    <Badge size="xs" variant="light" color={accent.secondary} tt="none" data-requirement="required">
      Required
    </Badge>
  ) : (
    <Badge size="xs" variant="outline" color="gray" tt="none" data-requirement="optional">
      Optional
    </Badge>
  );
};

/** A titled group of fields, its badge on the right of the title. */
export const SectionHead: React.FC<{
  title: string;
  hint?: string;
  kind?: RequirementKind;
  icon?: string;
}> = ({ title, hint, kind, icon }) => (
  <Group gap="xs" wrap="nowrap" align="flex-start">
    {icon && <Icon icon={icon} width={18} style={{ marginTop: 2, flexShrink: 0 }} />}
    <div style={{ minWidth: 0 }}>
      <Group gap={8} wrap="nowrap">
        <Text size="sm" fw={600} lh={1.3}>
          {title}
        </Text>
        {kind && <RequirementBadge kind={kind} />}
      </Group>
      {hint && (
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      )}
    </div>
  </Group>
);

/** Optional fields, folded under a head that says so. `initiallyOpen` opens
 *  it when the reader has already filled something in. */
export const OptionalBlock: React.FC<{
  title: string;
  hint: string;
  icon?: string;
  initiallyOpen?: boolean;
  testId?: string;
  children: React.ReactNode;
}> = ({ title, hint, icon = 'mdi:tune-variant', initiallyOpen = false, testId, children }) => {
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <Paper withBorder radius="md" p="sm" data-testid={testId}>
      <UnstyledButton
        w="100%"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-testid={testId ? `${testId}-toggle` : undefined}
      >
        <Group gap="xs" wrap="nowrap" align="flex-start">
          <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={18} style={{ marginTop: 2, flexShrink: 0 }} />
          <SectionHead title={title} hint={hint} kind="optional" icon={icon} />
        </Group>
      </UnstyledButton>
      <Collapse in={open}>
        <Stack gap="sm" pt="sm">
          {children}
        </Stack>
      </Collapse>
    </Paper>
  );
};
