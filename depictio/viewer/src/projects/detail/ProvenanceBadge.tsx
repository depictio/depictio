import React from 'react';
import { Badge, Tooltip } from '@mantine/core';
import { provenanceBadge } from 'depictio-react-core';
import type { ProjectProvenance, ProvenanceState } from 'depictio-react-core';

import { useServerInfo } from '../../hooks/useServerInfo';

const COLOR: Record<ProvenanceState, string> = {
  same: 'gray',
  legacy: 'gray',
  older: 'yellow',
  newer: 'orange',
  unknown_running: 'gray',
};

/** Which Depictio version produced the project, versus the one running now. */
export const ProvenanceBadge: React.FC<{ provenance?: ProjectProvenance | null }> = ({
  provenance,
}) => {
  const { info } = useServerInfo();
  const { label, state, tooltipLines } = provenanceBadge(provenance, info?.version);
  return (
    <Tooltip
      multiline
      withinPortal
      w={320}
      label={
        <div>
          {tooltipLines.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      }
    >
      <Badge
        size="sm"
        variant={state === 'legacy' ? 'outline' : 'light'}
        color={COLOR[state]}
        radius="sm"
        style={{ cursor: 'default' }}
      >
        {label}
      </Badge>
    </Tooltip>
  );
};
