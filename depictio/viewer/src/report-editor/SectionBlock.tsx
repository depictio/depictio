import React from 'react';
import { Box, Checkbox, Collapse, Group, Stack, Text, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

interface SectionBlockProps {
  tabId: string;
  title: string;
  total: number;
  included: number;
  open: boolean;
  onToggle: () => void;
  /** Put every component of the section in the report, or take them all out. */
  onToggleAll: (on: boolean) => void;
  /** Padding above, to set a section off from the one before it. */
  first: boolean;
  children: React.ReactNode;
}

/** A section of a tab: a header with its count and an include-all box, and
 *  its component cards in a collapsible body. */
const SectionBlock: React.FC<SectionBlockProps> = ({
  tabId,
  title,
  total,
  included,
  open,
  onToggle,
  onToggleAll,
  first,
  children,
}) => (
  <Box pt={first ? 0 : 'xs'}>
    <Group gap="xs" wrap="nowrap" px="xs">
      <Checkbox
        size="xs"
        checked={total > 0 && included === total}
        indeterminate={included > 0 && included < total}
        onChange={(e) => onToggleAll(e.currentTarget.checked)}
        aria-label={`Include all of ${title} in the report`}
        data-testid={`report-section-toggle-${tabId}:${title}`}
      />
      <UnstyledButton
        onClick={onToggle}
        aria-expanded={open}
        data-testid={`report-section-${tabId}:${title}`}
        style={{ flex: 1, minWidth: 0 }}
      >
        <Group gap={6} wrap="nowrap">
          <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />
          <Text
            size="xs"
            fw={600}
            c="dimmed"
            tt="uppercase"
            truncate
            data-testid="report-section-heading"
          >
            {title}
          </Text>
          <Text size="xs" c="dimmed" style={{ flex: 'none' }}>
            {included} of {total} in the report
          </Text>
        </Group>
      </UnstyledButton>
    </Group>
    <Collapse in={open}>
      <Stack gap={6} pt={6}>
        {children}
      </Stack>
    </Collapse>
  </Box>
);

export default SectionBlock;
