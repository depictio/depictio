/**
 * "What Depictio found" for a folder that holds plain tables and no pipeline
 * run: the files it lists, the ones that can become a table ticked, the
 * others disabled with a reason.
 */
import React from 'react';
import { Checkbox, Stack, Text } from '@mantine/core';

import { isS3Location } from 'depictio-react-core';

import { FoundCard, SourceValue } from '../detail/FoundCard';
import { classifyTableName } from './tableFiles';

interface FolderTablesFoundProps {
  location: string;
  names: string[];
  /** The folder holds more files than were listed. */
  moreCount: number;
  ticked: ReadonlySet<string>;
  onToggle: (name: string, checked: boolean) => void;
}

export const FolderTablesFound: React.FC<FolderTablesFoundProps> = ({
  location,
  names,
  moreCount,
  ticked,
  onToggle,
}) => (
  <FoundCard
    testId="folder-tables-found-card"
    rows={[
      {
        key: 'source',
        label: 'Source',
        value: <SourceValue kind={isS3Location(location) ? 's3' : 'folder'} location={location} />,
      },
      {
        key: 'contents',
        label: 'Contents',
        value: (
          <Stack gap={6}>
            {names.map((name) => {
              const guess = classifyTableName(name);
              return (
                <Checkbox
                  key={name}
                  size="sm"
                  checked={guess.table && ticked.has(name)}
                  disabled={!guess.table}
                  onChange={(e) => onToggle(name, e.currentTarget.checked)}
                  data-testid={`folder-table-${name}`}
                  label={
                    <Text span size="sm" c={guess.table ? undefined : 'dimmed'}>
                      {name}{' '}
                      <Text span size="xs" c="dimmed">
                        {guess.table ? guess.format : guess.reason}
                      </Text>
                    </Text>
                  }
                />
              );
            })}
            {moreCount > 0 && (
              <Text size="xs" c="dimmed">
                and {moreCount} more not listed
              </Text>
            )}
          </Stack>
        ),
      },
    ]}
  />
);
