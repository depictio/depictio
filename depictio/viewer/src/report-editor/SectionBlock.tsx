import React from 'react';
import { Box, Checkbox, Collapse, Group, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';
import { SectionIcon, resolveSectionColor, sectionColorVar } from 'depictio-react-core';

import type { SectionLook } from './model';
import TileGrid from './tiles/TileGrid';

interface SectionBlockProps {
  tabId: string;
  title: string;
  /** The section's icon, colour and subtitle; none for a section the layer
   *  made up (a tile moved to a name the dashboard does not have). */
  look?: SectionLook;
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

/** A section of a tab, drawn like the dashboard's own header: its icon in its
 *  colour, its title over its description, a rail in its colour down the
 *  side. An include-all box and a count lead the row; its component cards
 *  sit in a collapsible body. */
const SectionBlock: React.FC<SectionBlockProps> = ({
  tabId,
  title,
  look,
  total,
  included,
  open,
  onToggle,
  onToggleAll,
  first,
  children,
}) => {
  // The dashboard's own colour for the section: its declared one, else the
  // one its name hashes to, so it matches the grid and the report.
  const color = resolveSectionColor(look?.color, title);
  const accent = sectionColorVar(color);
  return (
    <Box
      pt={first ? 0 : 'xs'}
      data-testid={`report-section-block-${tabId}:${title}`}
      style={{ ['--section-accent' as string]: accent }}
    >
      <Group
        gap="xs"
        wrap="nowrap"
        px="xs"
        py={6}
        style={{
          borderInlineStart: '3px solid var(--section-accent)',
          borderRadius: 'var(--mantine-radius-sm)',
          background: 'color-mix(in srgb, var(--section-accent) 8%, transparent)',
        }}
      >
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
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />
            {look?.icon ? <SectionIcon spec={{ icon: look.icon, color }} size={18} /> : null}
            <Box style={{ flex: 1, minWidth: 0 }}>
              <Text size="sm" fw={600} truncate data-testid="report-section-heading">
                {title}
              </Text>
              {look?.description ? (
                <Tooltip label={look.description} multiline w={280} openDelay={400} withArrow>
                  <Text size="xs" c="dimmed" truncate>
                    {look.description}
                  </Text>
                </Tooltip>
              ) : null}
            </Box>
            <Text size="xs" c="dimmed" style={{ flex: 'none' }}>
              {included} of {total} in the report
            </Text>
          </Group>
        </UnstyledButton>
      </Group>
      <Collapse in={open}>
        <Box pt={6} pl={6} style={{ borderInlineStart: '3px solid transparent' }}>
          <TileGrid>{children}</TileGrid>
        </Box>
      </Collapse>
    </Box>
  );
};

export default SectionBlock;
