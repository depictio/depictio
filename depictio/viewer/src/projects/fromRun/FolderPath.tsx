/**
 * A folder location written once and short: the home folder as `~`, the
 * middle cut on segment boundaries, the full location in a tooltip and one
 * click away from the clipboard.
 */
import React from 'react';
import { ActionIcon, Code, CopyButton, Group, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { shortenFolder, Z_LAYERS } from 'depictio-react-core';

interface FolderPathProps {
  location: string;
  /** Longest shortened form, in characters. */
  maxLength?: number;
  withCopy?: boolean;
  testId?: string;
}

export const FolderPath: React.FC<FolderPathProps> = ({
  location,
  maxLength = 56,
  withCopy = true,
  testId,
}) => {
  const short = shortenFolder(location, { maxLength });
  return (
    <Group gap={4} wrap="nowrap" style={{ minWidth: 0 }}>
      <Tooltip
        label={location}
        withArrow
        multiline
        maw={480}
        zIndex={Z_LAYERS.tooltip}
        disabled={short === location}
        styles={{ tooltip: { wordBreak: 'break-all' } }}
      >
        <Code
          data-testid={testId}
          data-full-path={location}
          style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0 }}
        >
          {short}
        </Code>
      </Tooltip>
      {withCopy && (
        <CopyButton value={location} timeout={1500}>
          {({ copied, copy }) => (
            <Tooltip
              label={copied ? 'Copied' : 'Copy the full path'}
              withArrow
              zIndex={Z_LAYERS.tooltip}
            >
              <ActionIcon
                size="sm"
                variant="subtle"
                color={copied ? 'teal' : 'gray'}
                onClick={copy}
                aria-label="Copy the full path"
                data-testid={testId ? `${testId}-copy` : undefined}
              >
                <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
              </ActionIcon>
            </Tooltip>
          )}
        </CopyButton>
      )}
    </Group>
  );
};
