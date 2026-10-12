import React from 'react';
import { Radio, Stack } from '@mantine/core';

import { CHROME_VARIANTS, useChromeChoice } from '../../../chrome/variants';
import { Field } from '../SettingsSections';

/** Value of the "follow the instance" option; a style id never collides with it. */
const FOLLOW_INSTANCE = '';

/** The reader's own look for the app, kept in this browser. Without a pick the
 *  instance default (set by an admin in Branding) applies; a `?chrome=` link
 *  overrides both for the rest of the session. */
const ChromeLookField: React.FC = () => {
  const { pick, instanceDefault, choose } = useChromeChoice();
  return (
    <Field label="Look" testId="chrome-style-section">
      <Radio.Group
        value={pick ?? FOLLOW_INSTANCE}
        onChange={(value) => choose(value === FOLLOW_INSTANCE ? null : value)}
      >
        <Stack gap="xs">
          <Radio
            value={FOLLOW_INSTANCE}
            label={`Instance default (${instanceDefault.name})`}
            description="Whatever this instance's admin chose"
            data-testid="chrome-style-default"
          />
          {CHROME_VARIANTS.map((v) => (
            <Radio
              key={v.id}
              value={v.id}
              label={v.name}
              description={v.tagline}
              data-testid={`chrome-style-${v.id}`}
            />
          ))}
        </Stack>
      </Radio.Group>
    </Field>
  );
};

export default ChromeLookField;
