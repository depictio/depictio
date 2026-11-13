/** GeoJSON properties: the feature property that identifies each shape. */
import React from 'react';
import { TextInput } from '@mantine/core';

import type { BuilderGeoJSONProps } from 'depictio-react-core';

export const GeoJSONForm: React.FC<{
  props: BuilderGeoJSONProps;
  onChange: (props: BuilderGeoJSONProps) => void;
}> = ({ props, onChange }) => (
  <TextInput
    label="Feature id key"
    description="The property of each feature that tables join on (e.g. iso_a3)"
    placeholder="id"
    value={props.feature_id_key}
    onChange={(e) => onChange({ ...props, feature_id_key: e.currentTarget.value })}
    error={!props.feature_id_key.trim() ? 'Required' : undefined}
    spellCheck={false}
    data-testid="builder-props-feature-id-key"
  />
);
