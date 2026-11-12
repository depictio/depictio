/**
 * The quiet "Changed since 3 days ago" pill in the header's title area (#1397).
 * Hidden on a first visit, when nothing differs, in a pinned preview and while
 * the feature is off: it draws only from `ChangeMarksProvider`'s change set.
 */
import React, { useState } from 'react';
import { Button, Popover } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandScopeAttributes, Z_LAYERS } from 'depictio-react-core';

import { formatDate, formatDateTimeVerbose, formatRelativeTime } from '../lib/datetime';
import ChangesPanel from './ChangesPanel';
import { useChangesSince } from './ChangesSinceContext';
import { changeCounts, hasChanges, pillLabel } from './describe';

const ChangesSincePill: React.FC = () => {
  const ctx = useChangesSince();
  const brandScope = useBrandScopeAttributes();
  const [opened, setOpened] = useState(false);
  if (!ctx || !hasChanges(ctx.changeSet)) return null;

  const { changeSet, readOnlyQuery } = ctx;
  const label = pillLabel(
    changeSet.since,
    readOnlyQuery,
    (raw) => formatRelativeTime(raw),
    (raw) => formatDate(raw),
  );

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position="bottom-start"
      width={420}
      shadow="md"
      withArrow
      zIndex={Z_LAYERS.tooltip}
    >
      <Popover.Target>
        <Button
          size="compact-xs"
          radius="xl"
          variant="light"
          color="blue"
          leftSection={<Icon icon="mdi:update" width={13} />}
          onClick={() => setOpened((o) => !o)}
          title={changeSet.since ? formatDateTimeVerbose(changeSet.since) : undefined}
          aria-label={`${label}, ${changeCounts(changeSet).total} changes`}
          data-testid="changes-pill"
          data-read-only={ctx.readOnly ? 'true' : undefined}
        >
          {label}
        </Button>
      </Popover.Target>
      <Popover.Dropdown
        className={brandScope?.className}
        data-mantine-color-scheme={brandScope?.['data-mantine-color-scheme']}
      >
        <ChangesPanel onClose={() => setOpened(false)} />
      </Popover.Dropdown>
    </Popover>
  );
};

export default ChangesSincePill;
