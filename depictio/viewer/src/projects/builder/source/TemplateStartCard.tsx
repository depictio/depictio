/**
 * What Depictio recognised in the folder, said at the top of the Source step:
 * the pipeline, the template that fits, and the choices that follow. The
 * builder starts empty (with the recognised engine) and the template is one
 * click away. A template opened as the draft is edited, not converted: the
 * card says what it holds and what the reader changed of it.
 */
import React, { useState } from 'react';
import { Alert, Anchor, Button, Group, Loader, Paper, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import { baseCollections, baseEditCounts, useBrandAccents } from 'depictio-react-core';
import type { BuilderState, FromRunReport, TemplateInfo } from 'depictio-react-core';

import { FactBadge } from '../../badges';
import { plural } from '../../fromRun/plural';
import type { TemplateStart } from './useTemplateStart';

/** A project made from a run folder: the folder it was created from. */
export interface FolderProject {
  id: string;
  name: string;
  dataRoot: string;
}

const folderKey = (location: string) => location.trim().replace(/\/+$/, '');

/** The projects the list holds that were created from a run folder. */
export function projectsByFolder(projects: unknown[]): FolderProject[] {
  const found: FolderProject[] = [];
  for (const raw of projects) {
    const project = raw as { id?: string; _id?: string; name?: string; template_origin?: { data_root?: unknown } };
    const dataRoot = project.template_origin?.data_root;
    const id = project.id ?? project._id;
    if (typeof dataRoot === 'string' && dataRoot && id) {
      found.push({ id: String(id), name: project.name ?? '', dataRoot: folderKey(dataRoot) });
    }
  }
  return found;
}

/** The project already created from `dataRoot`, if any. */
export function projectOfFolder(projects: FolderProject[], dataRoot: string | null | undefined): FolderProject | null {
  if (!dataRoot) return null;
  const key = folderKey(dataRoot);
  return projects.find((p) => p.dataRoot === key) ?? null;
}

interface TemplateStartCardProps {
  start: TemplateStart;
  templates: TemplateInfo[];
  /** The draft has collections or links: loading the template replaces them. */
  draftHasWork: boolean;
  /** The draft, for what was changed of the template. */
  state: BuilderState;
  onStartOver: () => void;
  /** This draft was just created: its dashboards are imported. */
  created?: FromRunReport | null;
  /** A project already made from this folder, with the template's dashboards. */
  folderProject?: FolderProject | null;
}

export const TemplateStartCard: React.FC<TemplateStartCardProps> = ({
  start,
  templates,
  draftHasWork,
  state: draft,
  onStartOver,
  created = null,
  folderProject = null,
}) => {
  const accent = useBrandAccents();
  const [confirming, setConfirming] = useState(false);
  const [hidden, setHidden] = useState(false);

  const { detection, templateId, state } = start;
  // A draft that edits a template says so, whether just loaded or resumed.
  const editing = Boolean(draft.base) && state.status !== 'loading';
  if (hidden && !editing) return null;
  if (detection.status === 'loading' && !templateId) return null;
  if (!templateId && state.status === 'idle' && !editing) return null;

  const detected = detection.status === 'ready' ? detection.result.detected : null;
  const template = templates.find((t) => t.template_id === templateId) ?? null;
  const title = template?.name ?? templateId;
  const pipeline = detected?.pipeline ?? null;
  const version = detected?.version ?? null;
  const headline = pipeline
    ? `Recognised ${pipeline}${version ? ` ${version}` : ''}`
    : 'A template fits this folder';
  // What the New project dialog chose replaced a draft saved for this
  // folder: said, and undoable, wherever the card is.
  const replacedNotice = start.replaced ? (
    <Alert
      color="yellow"
      variant="light"
      icon={<Icon icon="mdi:content-save-outline" width={16} />}
      data-testid="builder-template-replaced"
    >
      <Group gap="sm" justify="space-between" wrap="nowrap">
        <Text size="sm">This folder had another saved draft. What you chose replaced it.</Text>
        <Button size="xs" variant="light" color="yellow" onClick={start.restore} data-testid="builder-template-restore">
          Restore it
        </Button>
      </Group>
    </Alert>
  ) : null;

  if (editing && draft.base) {
    const description = draft.base.template;
    const collections = baseCollections(draft.base).length;
    const counts = baseEditCounts(draft);
    const changes = [
      counts.removed ? `${plural(counts.removed, 'collection')} removed` : null,
      counts.repointed ? `${plural(counts.repointed, 'collection')} repointed` : null,
      counts.added ? `${plural(counts.added, 'collection')} added` : null,
      counts.workflows ? `settings of ${plural(counts.workflows, 'workflow')} changed` : null,
    ].filter(Boolean);
    return (
      <Paper withBorder radius="md" p="md" data-testid="builder-template-start" data-state="loaded">
        <Stack gap="xs">
          <Group gap="sm" wrap="nowrap" align="flex-start" justify="space-between">
            <Group gap="sm" wrap="nowrap" align="flex-start" style={{ minWidth: 0 }}>
              <ThemeIcon variant="light" color={accent.secondary} size="md" radius="md" style={{ flexShrink: 0 }}>
                <Icon icon="mdi:file-edit-outline" width={16} />
              </ThemeIcon>
              <Stack gap={4} style={{ minWidth: 0 }}>
                <Text size="sm" fw={600}>
                  Editing {description.title ?? description.template_id}
                  {/* The pipeline's version names it; the template's own
                      version (1.3.3...) is only its revision. */}
                  {description.workflows[0]?.version ? ` (${description.workflows[0].version})` : ''}
                </Text>
                <Group gap={6} data-testid="builder-template-carried">
                  <FactBadge icon="mdi:database-outline">{plural(collections, 'collection')}</FactBadge>
                  <FactBadge icon="mdi:link-variant">{plural(description.links.length, 'link')}</FactBadge>
                  {/* What the template brings, against what a project already has. */}
                  <FactBadge icon="mdi:view-dashboard-outline" data-testid="builder-template-dashboards">
                    {created
                      ? `${plural(created.dashboards.filter((d) => d.success).length, 'dashboard')} imported`
                      : `${plural(description.dashboards.length, 'dashboard')} ${folderProject ? 'in the template' : 'to import'}`}
                  </FactBadge>
                </Group>
                {!created && folderProject && (
                  <Text size="sm" c="dimmed" data-testid="builder-template-folder-project">
                    This folder already has a project,{' '}
                    <Anchor href={`/projects/${folderProject.id}`} size="sm">
                      {folderProject.name || 'unnamed'}
                    </Anchor>
                    , with the template&apos;s dashboards. Creating again makes a second project; to
                    change the first one, open it.
                  </Text>
                )}
                <Text size="sm" c="dimmed" data-testid="builder-template-changes">
                  {changes.length
                    ? `Your changes: ${changes.join(', ')}.`
                    : 'Nothing changed yet.'}{' '}
                  Whatever you do not change stays as the template ships it, its recipes and
                  dashboards included.
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
          {replacedNotice}
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
              {headline}
            </Text>
            <Text size="sm" c="dimmed">
              Depictio has a template for it{title ? `: ${title}` : ''}. Start from it to keep its collections,
              recipes and dashboards and change only what you need, or keep defining the collections
              yourself{start.engine ? ` (the workflow engine is set to ${start.engine})` : ''}.
            </Text>
          </Stack>
        </Group>

        {state.status === 'error' && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle-outline" width={16} />}>
            The builder cannot open this template: {state.error}
          </Alert>
        )}
        {replacedNotice}

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
