/**
 * "What's new" in the header's action bar (#1397): a chrome button like
 * Comments, counting the changes since the reader's mark, opening the list of
 * them. Hidden on a first visit, when nothing differs, in a pinned preview and
 * while the feature is off: it draws only from `ChangeMarksProvider`'s change
 * set.
 */
import React, { useState } from 'react';
import { Modal, Popover } from '@mantine/core';

import { ChromeButton, useBrandScopeAttributes, Z_LAYERS } from 'depictio-react-core';
import type { DataChange } from 'depictio-react-core';

import { formatDate, formatRelativeTime } from '../lib/datetime';

import ChangesPanel from './ChangesPanel';
import NewRowsPreview from './NewRowsPreview';
import { useChangesSince } from './ChangesSinceContext';
import { changeCounts, hasChanges, pillLabel } from './describe';

const ChangesHeaderButton: React.FC = () => {
  const ctx = useChangesSince();
  const brandScope = useBrandScopeAttributes();
  const [opened, setOpened] = useState(false);
  // The collection whose new rows are open. Held here, not in the panel: a
  // modal inside the popover would close with it on the first click.
  const [rowsOf, setRowsOf] = useState<DataChange | null>(null);
  if (!ctx || !hasChanges(ctx.changeSet)) return null;

  const { changeSet, readOnlyQuery } = ctx;
  const since = pillLabel(
    changeSet.since,
    readOnlyQuery,
    (raw) => formatRelativeTime(raw),
    (raw) => formatDate(raw),
  );
  const total = changeCounts(changeSet).total;
  const label = readOnlyQuery.beforeRun ? 'This ingestion' : ctx.readOnly ? 'Changes' : "What's new";

  return (
    <>
      <Modal
        opened={rowsOf !== null}
        onClose={() => setRowsOf(null)}
        title={rowsOf ? `${rowsOf.data_collection_tag}: new rows` : ''}
        size="90%"
      >
        {rowsOf && <NewRowsPreview dcId={rowsOf.dc_id} runs={rowsOf.new_run_tags} height={480} />}
      </Modal>
      <Popover
        opened={opened}
        onChange={setOpened}
        position="bottom-end"
        width={400}
        shadow="md"
        radius="md"
        zIndex={Z_LAYERS.tooltip}
      >
        <Popover.Target>
          <ChromeButton
            role="secondary"
            collapse
            icon="mdi:update"
            label={label}
            badge={total}
            tooltip={opened ? null : since}
            onClick={() => setOpened((o) => !o)}
            aria-label={`${since}, ${total} change${total === 1 ? '' : 's'}`}
            data-testid="changes-pill"
            data-read-only={ctx.readOnly ? 'true' : undefined}
          />
        </Popover.Target>
        <Popover.Dropdown
          p="sm"
          className={brandScope?.className}
          data-mantine-color-scheme={brandScope?.['data-mantine-color-scheme']}
        >
          <ChangesPanel
            onClose={() => setOpened(false)}
            subtitle={since}
            onViewRows={(change) => {
              setOpened(false);
              setRowsOf(change);
            }}
          />
        </Popover.Dropdown>
      </Popover>
    </>
  );
};

export default ChangesHeaderButton;
