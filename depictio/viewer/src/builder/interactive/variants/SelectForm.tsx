/**
 * Select variant: single-value picker. Defaults pulled from
 * /deltatables/unique_values when a column is set.
 */
import React, { useEffect, useState } from 'react';
import { Select, Text } from '@mantine/core';
import { fetchUniqueValues } from 'depictio-react-core';
import { useBuilderStore } from '../../store/useBuilderStore';

const SelectForm: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const config = useBuilderStore((s) => s.config) as {
    column_name?: string;
    default_state?: { default_value?: string };
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const [options, setOptions] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!dcId || !config.column_name) {
      setOptions([]);
      return;
    }
    setLoading(true);
    fetchUniqueValues(dcId, config.column_name)
      .then(setOptions)
      .finally(() => setLoading(false));
  }, [dcId, config.column_name]);

  return (
    <>
      <Text size="sm" fw={500} mt="xs">
        Default value
      </Text>
      <Select
        placeholder={loading ? 'Loading values…' : 'Pick a default'}
        data={options}
        value={config.default_state?.default_value ?? null}
        onChange={(val) =>
          patchConfig({ default_state: { default_value: val } })
        }
        searchable
        clearable
        disabled={!options.length}
      />
    </>
  );
};

export default SelectForm;
