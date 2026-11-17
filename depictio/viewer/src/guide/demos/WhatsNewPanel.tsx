import React, { useState } from 'react';
import { Modal } from '@mantine/core';

import type { DataChange } from 'depictio-react-core';

import ChangesPanel from '../../changes/ChangesPanel';
import NewRowsPreview from '../../changes/NewRowsPreview';

/**
 * The header's "What's new" list, laid out in the Guide: the real change set
 * of this dashboard, not an example. A collection's new rows open in a modal
 * of its own, as from the header.
 */
export const WhatsNewPanel: React.FC = () => {
  const [rowsOf, setRowsOf] = useState<DataChange | null>(null);
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
      <ChangesPanel embedded onViewRows={setRowsOf} />
    </>
  );
};
