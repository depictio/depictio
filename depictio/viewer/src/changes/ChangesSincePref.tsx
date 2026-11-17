/**
 * The reader's "Changes since your last visit" preference on /profile (#1397):
 * when "changed" restarts. Saved to the account, so it is for signed-in readers
 * on an instance that has the feature on; nothing else sees it or calls the API.
 */
import React, { useEffect, useState } from 'react';
import { Loader } from '@mantine/core';

import { fetchChangesPrefs, saveChangesPrefs } from 'depictio-react-core';
import type { MarkMode } from 'depictio-react-core';

import { useChangesSinceEnabled } from '../hooks/useChangesSinceEnabled';
import { Field } from '../components/settings/SettingsSections';
import ChangesModeSelect from './ChangesModeSelect';

const ChangesSincePref: React.FC<{ signedIn: boolean }> = ({ signedIn }) => {
  const enabled = useChangesSinceEnabled() && signedIn;
  const [mode, setMode] = useState<MarkMode | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    fetchChangesPrefs()
      .then((prefs) => {
        if (!cancelled) setMode(prefs.mark_mode);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  if (!enabled || failed) return null;

  const change = (next: MarkMode) => {
    const previous = mode;
    setMode(next);
    saveChangesPrefs(next).catch(() => setMode(previous));
  };

  return (
    <Field
      label="Changes since your last visit"
      description="Dashboards mark what changed since you last looked: new data, edits, comments. Choose when a mark clears. Saved to your account."
      testId="changes-since-pref"
    >
      {mode ? <ChangesModeSelect value={mode} onChange={change} fullWidth={false} /> : <Loader size="xs" />}
    </Field>
  );
};

export default ChangesSincePref;
