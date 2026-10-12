/**
 * What Depictio recognised in the folder, said at the top of the Source step:
 * the pipeline, the template that fits, and the choices that follow. The
 * builder starts empty (with the recognised engine) and the template is one
 * click away; a template loaded as the draft says what it carried over and
 * what the builder cannot express.
 */
import React, { useState } from 'react';
import { Alert, Anchor, Button, Collapse, Group, Loader, Paper, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import type { TemplateInfo } from 'depictio-react-core';

import { ITEM_KINDS } from '../../fromRun/NextStepChoice';
import { plural } from '../../fromRun/plural';
import type { TemplateStart } from './useTemplateStart';

interface TemplateStartCardProps {
  start: TemplateStart;
  templates: TemplateInfo[];
  /** The draft has collections or links: loading the template replaces them. */
  draftHasWork: boolean;
  onStartOver: () => void;
}

export const TemplateStartCard: React.FC<TemplateStartCardProps> = ({
  start,
  templates,
  draftHasWork,
  onStartOver,
}) => {
  const accent = useBrandAccents();
  const [confirming, setConfirming] = useState(false);
  const [showDropped, setShowDropped] = useState(false);
  const [hidden, setHidden] = useState(false);

  const { detection, templateId, state } = start;
  if (hidden && state.status !== 'loaded') return null;
  if (detection.status === 'loading' && !templateId) return null;
  if (!templateId && state.status === 'idle') return null;

  const detected = detection.status === 'ready' ? detection.result.detected : null;
  const template = templates.find((t) => t.template_id === templateId) ?? null;
  const title = template?.name ?? templateId;
  const pipeline = detected?.pipeline ?? null;
  const version = detected?.version ?? null;

  if (state.status === 'loaded') {
    const { carried, dropped } = state.result;
    const notCarried = dropped.filter((d) => !ITEM_KINDS.has(d.kind));
    const lost = dropped.filter((d) => ITEM_KINDS.has(d.kind));
    return (
      <Paper withBorder radius="md" p="md" data-testid="builder-template-start" data-state="loaded">
        <Stack gap="xs">
          <Group gap="sm" wrap="nowrap" align="flex-start" justify="space-between">
            <Group gap="sm" wrap="nowrap" align="flex-start" style={{ minWidth: 0 }}>
              <ThemeIcon variant="light" color={accent.secondary} size="md" radius="md" style={{ flexShrink: 0 }}>
                <Icon icon="mdi:file-edit-outline" width={16} />
              </ThemeIcon>
              <Stack gap={2} style={{ minWidth: 0 }}>
                <Text size="sm" fw={600}>
                  Started from {title}
                </Text>
                <Text size="sm" c="dimmed" data-testid="builder-template-carried">
                  {plural(carried.collections, 'collection')} and {plural(carried.links, 'link')} carried over
                  {notCarried.length > 0
                    ? `; not carried over: ${[...new Set(notCarried.map((d) => d.kind))].join(', ')}`
                    : ''}
                  . The project follows your edits, not the shipped template.
                </Text>
              </Stack>
            </Group>
            <Button
              size="sm"
              variant="subtle"
              color="gray"
              style={{ flexShrink: 0 }}
              onClick={() => {
                start.dismiss();
                onStartOver();
              }}
              data-testid="builder-template-start-over"
            >
              Start from scratch instead
            </Button>
          </Group>
          {(lost.length > 0 || notCarried.length > 0) && (
            <>
              <Anchor size="xs" component="button" type="button" onClick={() => setShowDropped((v) => !v)}>
                {showDropped ? 'Hide' : 'Show'} what was left out
              </Anchor>
              <Collapse in={showDropped}>
                <Stack gap={2} data-testid="builder-template-dropped">
                  {[...lost, ...notCarried].map((item, i) => (
                    <Text key={`${item.kind}-${item.tag ?? i}`} size="xs" c="dimmed">
                      {item.tag ? `${item.tag}: ` : ''}
                      {item.reason}
                    </Text>
                  ))}
                </Stack>
              </Collapse>
            </>
          )}
        </Stack>
      </Paper>
    );
  }

  const busy = state.status === 'loading';
  return (
    <Paper withBorder radius="md" p="md" data-testid="builder-template-start" data-state={state.status}>
      <Stack gap="sm">
        <Group gap="sm" wrap="nowrap" align="flex-start">
          <ThemeIcon variant="light" color={accent.secondary} size="md" radius="md">
            <Icon icon="mdi:auto-fix" width={16} />
          </ThemeIcon>
          <Stack gap={2}>
            <Text size="sm" fw={600}>
              {pipeline ? `Recognised ${pipeline}${version ? ` ${version}` : ''}` : 'A template fits this folder'}
            </Text>
            <Text size="sm" c="dimmed">
              Depictio has a template for it{title ? `: ${title}` : ''}. Start the draft from it, or keep
              defining the collections yourself{start.engine ? ` (the workflow engine is set to ${start.engine})` : ''}.
            </Text>
          </Stack>
        </Group>

        {start.keptSavedDraft && (
          <Alert color="yellow" variant="light" icon={<Icon icon="mdi:content-save-outline" width={16} />}>
            You asked to start from the template, but this folder already has a saved draft, which was kept.
            Loading the template replaces it.
          </Alert>
        )}
        {state.status === 'error' && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle-outline" width={16} />}>
            The builder cannot open this template: {state.error}
          </Alert>
        )}

        <Group gap="xs">
          {confirming ? (
            <>
              <Text size="sm">Replace your draft with the template?</Text>
              <Button
                size="sm"
                color="red"
                variant="light"
                onClick={() => {
                  setConfirming(false);
                  start.load();
                }}
                data-testid="builder-template-replace-confirm"
              >
                Replace
              </Button>
              <Button size="sm" variant="default" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                color={accent.secondary}
                leftSection={busy ? <Loader size={12} color="white" /> : <Icon icon="mdi:file-edit-outline" width={14} />}
                disabled={busy || !templateId}
                onClick={() => (draftHasWork ? setConfirming(true) : start.load())}
                data-testid="builder-template-load"
              >
                Start from {title ?? 'the template'}
              </Button>
              <Button
                size="sm"
                variant="default"
                onClick={() => setHidden(true)}
                data-testid="builder-template-scratch"
              >
                Keep building from scratch
              </Button>
            </>
          )}
        </Group>
      </Stack>
    </Paper>
  );
};

export default TemplateStartCard;
