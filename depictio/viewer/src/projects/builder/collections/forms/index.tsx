/** The properties form of a collection's type. */
import React from 'react';

import type { BuilderCapabilities, BuilderDcProps, BuilderStoreSummary } from 'depictio-react-core';

import type { BuilderMode } from '../../mode';
import { GeoJSONForm } from './GeoJSONForm';
import { ImageForm } from './ImageForm';
import { IndexedFileForm } from './IndexedFileForm';
import { MultiQCForm } from './MultiQCForm';
import { PhylogenyForm } from './PhylogenyForm';
import { TableForm } from './TableForm';

/** What the forms read beyond the properties themselves. */
export interface PropsFormContext {
  /** The previewed file's columns (a genomic manifest's, when matched). */
  columns: string[];
  remote: boolean;
  /** Tags of the project's table collections (phylogeny metadata). */
  tables: string[];
  capabilities: BuilderCapabilities;
  mode: BuilderMode;
  /** What `/suggest` read of a picked store. */
  store: BuilderStoreSummary | null;
}

export const PropsForm: React.FC<{
  props: BuilderDcProps;
  onChange: (props: BuilderDcProps) => void;
  context: PropsFormContext;
}> = ({ props, onChange, context }) => {
  const { columns, remote, tables, capabilities, mode, store } = context;
  switch (props.kind) {
    case 'table':
      return (
        <TableForm
          props={props}
          onChange={onChange}
          columns={columns}
          capabilities={capabilities}
          remote={remote}
          store={store}
        />
      );
    case 'multiqc':
      return <MultiQCForm />;
    case 'image':
      return <ImageForm props={props} onChange={onChange} columns={columns} capabilities={capabilities} mode={mode} />;
    case 'indexed_file':
      return <IndexedFileForm props={props} onChange={onChange} />;
    case 'geojson':
      return <GeoJSONForm props={props} onChange={onChange} />;
    case 'phylogeny':
      return <PhylogenyForm props={props} onChange={onChange} tables={tables} />;
    default:
      return null;
  }
};
