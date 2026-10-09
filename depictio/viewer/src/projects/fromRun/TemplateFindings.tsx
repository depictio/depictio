/**
 * Under the run / template comparison: what the template would find in the
 * folder, folded until asked for. Opening it previews the folder with that
 * template (a dry run of `POST /projects/from_run`, nothing is created) and
 * lists every data collection with the files it matched and, for a table,
 * the recipe that builds it. The answer is kept per folder and template, so
 * folding and unfolding does not ask again.
 */
import React, { useEffect, useId, useRef, useState } from 'react';
import { Alert, Collapse, Group, Loader, Stack, Text, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { createProjectFromRun, runCollectionTotals } from 'depictio-react-core';
import type { FromRunReport, RunStorageIn } from 'depictio-react-core';

import { CollectionPlan } from './CollectionPlan';
import { plural } from './plural';

type FindingsState =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; report: FromRunReport };

interface TemplateFindingsProps {
  location: string;
  templateId: string;
  /** The private bucket's connection details, for a location in one. */
  storage?: RunStorageIn | null;
  testIdPrefix: string;
}

export const TemplateFindings: React.FC<TemplateFindingsProps> = ({
  location,
  templateId,
  storage = null,
  testIdPrefix,
}) => {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<FindingsState | null>(null);
  const answers = useRef(new Map<string, FindingsState>());
  const panelId = useId();
  const key = `${templateId}\n${location}`;

  useEffect(() => {
    if (!open) return undefined;
    const known = answers.current.get(key);
    if (known && known.status !== 'error') {
      setState(known);
      return undefined;
    }
    let cancelled = false;
    setState({ status: 'loading' });
    createProjectFromRun({ dataRoot: location, templateId, dryRun: true, storage })
      .then((report) => {
        const next: FindingsState = { status: 'ready', report };
        answers.current.set(key, next);
        if (!cancelled) setState(next);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setState({ status: 'error', error: err.message || 'The folder could not be previewed.' });
        }
      });
    return () => {
      cancelled = true;
    };
    // `storage` is read with the location it belongs to; the key decides.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, key]);

  const report = state?.status === 'ready' ? state.report : null;
  const totals = report ? runCollectionTotals(report.data_collections) : null;

  return (
    <Stack gap={6} data-testid={`${testIdPrefix}-findings`}>
      <UnstyledButton
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={panelId}
        data-testid={`${testIdPrefix}-findings-toggle`}
      >
        <Group gap={6} wrap="nowrap">
          <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />
          <Icon icon="mdi:table-search" width={16} />
          <Text size="sm" fw={600}>
            What this template finds here
          </Text>
          {totals && (
            <Text size="xs" c="dimmed" data-testid={`${testIdPrefix}-findings-summary`}>
              {totals.ready} of {plural(totals.considered, 'collection')} found
            </Text>
          )}
        </Group>
      </UnstyledButton>
      <Collapse in={open} id={panelId}>
        <Stack gap="xs" pt={4} aria-live="polite">
          <Text size="xs" c="dimmed">
            Every data collection of the template, the files it matched in this folder and,
            for a table, the recipe that builds it. Nothing is created.
          </Text>
          {state?.status === 'loading' && (
            <Group gap="xs" wrap="nowrap">
              <Loader size="xs" />
              <Text size="sm" c="dimmed">
                Previewing the folder with this template...
              </Text>
            </Group>
          )}
          {state?.status === 'error' && (
            <Alert
              color="yellow"
              variant="light"
              icon={<Icon icon="mdi:alert-outline" width={16} />}
              data-testid={`${testIdPrefix}-findings-error`}
            >
              {state.error}
            </Alert>
          )}
          {report &&
            (report.data_collections.length > 0 ? (
              <CollectionPlan rows={report.data_collections} dataRoot={report.data_root} />
            ) : (
              <Text size="sm" c="dimmed">
                The template defines no data collection to look for in this folder.
              </Text>
            ))}
          {report?.truncated && (
            <Text size="xs" c="dimmed">
              The folder listing was cut short, so these counts are a lower bound.
            </Text>
          )}
        </Stack>
      </Collapse>
    </Stack>
  );
};
