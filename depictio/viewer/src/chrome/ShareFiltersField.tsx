/**
 * The link to the current view, shown rather than hidden behind a button
 * (issue #936).
 *
 * The URL is the dashboard's own address plus a `#filters=` fragment that
 * carries the applied filters, one readable line per component, so what the
 * recipient will get can be read here before it is sent. Selecting the field
 * selects all of it; the icon copies it. With no filters applied it is the
 * plain dashboard link. A selection too large to survive chat apps and proxies
 * cannot become a link, and the field says so instead of showing one that
 * would break in transit.
 *
 * Lives in the "Your filters" section of the dashboard settings; the active
 * filters summary carries a one-click copy for the same link.
 */

import React, { useMemo } from 'react';
import { ActionIcon, CopyButton, TextInput, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { buildFilterShareUrl } from 'depictio-react-core';
import type { InteractiveFilter } from 'depictio-react-core';

interface ShareFiltersFieldProps {
  filters: InteractiveFilter[];
  activeCount: number;
}

const ShareFiltersField: React.FC<ShareFiltersFieldProps> = ({ filters, activeCount }) => {
  const url = useMemo(
    () => buildFilterShareUrl(activeCount > 0 ? filters : []),
    [filters, activeCount],
  );

  return (
    <TextInput
      readOnly
      size="xs"
      aria-label="Link to this view"
      value={url ?? ''}
      placeholder={url === null ? 'Too many selected values to put in a link' : undefined}
      error={url === null ? 'Too many selected values to put in a link' : undefined}
      onFocus={(e) => e.currentTarget.select()}
      styles={{ input: { fontFamily: 'var(--mantine-font-family-monospace)', fontSize: 11 } }}
      data-testid="share-filters-field"
      rightSection={
        url === null ? null : (
          <CopyButton value={url} timeout={1600}>
            {({ copied, copy }) => (
              <Tooltip label={copied ? 'Link copied' : 'Copy link'} withArrow position="left">
                <ActionIcon
                  variant="subtle"
                  color={copied ? 'teal' : 'gray'}
                  size="sm"
                  aria-label="Copy link"
                  onClick={copy}
                  data-testid="share-filters-copy"
                >
                  <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} height={14} />
                </ActionIcon>
              </Tooltip>
            )}
          </CopyButton>
        )
      }
    />
  );
};

export default ShareFiltersField;
