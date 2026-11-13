/**
 * How many runs a workflow reads, said the same way wherever a workflow is
 * shown: "1 run", "2 runs", or the pattern its runs match. A template's
 * workflow reads one run folder; given a folder of runs (`useFolderRuns`), it
 * reads each of them into the one project. A workflow of the builder's own
 * reads every sub-folder its pattern matches.
 */
import React from 'react';
import { Tooltip } from '@mantine/core';

import type { BuilderWorkflowState } from 'depictio-react-core';

import { FactBadge } from '../../badges';

export const RunsBadge: React.FC<{
  workflow: Pick<BuilderWorkflowState, 'structure' | 'runs_regex' | 'fromTemplate'>;
  /** The folder's runs, when it holds several (template workflows only). */
  runs: string[] | null;
  size?: 'xs' | 'sm';
}> = ({ workflow, runs, size = 'sm' }) => {
  let label: string;
  let hint: string;
  let icon = 'mdi:folder-multiple-outline';
  if (workflow.fromTemplate && runs && runs.length > 1) {
    label = `${runs.length} runs`;
    hint = `The data folder holds ${runs.length} runs (${runs.join(', ')}): each is read the same way, into this one project`;
  } else if (workflow.structure === 'sequencing-runs') {
    label = workflow.runs_regex ? `runs matching ${workflow.runs_regex}` : 'several runs';
    hint = 'The data folder holds several runs, one per subfolder matching this pattern';
  } else {
    label = '1 run';
    icon = 'mdi:folder-outline';
    hint = 'The data folder is one run of the pipeline: its results sit at the top';
  }
  return (
    <Tooltip label={hint} withArrow multiline maw={320}>
      <FactBadge size={size} icon={icon} data-testid="builder-workflow-runs">
        {label}
      </FactBadge>
    </Tooltip>
  );
};
