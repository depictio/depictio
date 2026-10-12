/** The properties form of a collection's type. */
import React from 'react';

import type { BuilderDcProps } from 'depictio-react-core';

import { GeoJSONForm } from './GeoJSONForm';
import { ImageForm } from './ImageForm';
import { IndexedFileForm } from './IndexedFileForm';
import { MultiQCForm } from './MultiQCForm';
import { PhylogenyForm } from './PhylogenyForm';
import { TableForm } from './TableForm';

export const PropsForm: React.FC<{
  props: BuilderDcProps;
  onChange: (props: BuilderDcProps) => void;
  /** The previewed file's columns. */
  columns: string[];
  remote: boolean;
  /** Tags of the project's table collections (phylogeny metadata). */
  tables: string[];
}> = ({ props, onChange, columns, remote, tables }) => {
  switch (props.kind) {
    case 'table':
      return <TableForm props={props} onChange={onChange} columns={columns} />;
    case 'multiqc':
      return <MultiQCForm />;
    case 'image':
      return <ImageForm props={props} onChange={onChange} columns={columns} remote={remote} />;
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
