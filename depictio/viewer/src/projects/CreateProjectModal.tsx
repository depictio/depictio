import React, { useEffect, useState } from 'react';
import {
  Alert,
  Anchor,
  Button,
  Center,
  Group,
  Modal,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { listProjectTemplates } from 'depictio-react-core';
import { useListingAccents } from '../lib/useListingAccents';
import type {
  CreateProjectInput,
  CreateProjectResult,
  FromRunReport,
  FromRunRequest,
  TemplateInfo,
} from 'depictio-react-core';

import { RunFolderTab } from './fromRun';
import type { RunCreatedContext } from './fromRun';

/** Stack id of the create dialog: the folder browser opens above it, in the
 *  same `Modal.Stack`. */
const CREATE_STACK_ID = 'create-project';

interface CreateProjectModalProps {
  opened: boolean;
  existingNames: string[];
  onClose: () => void;
  /** `keepOpen`: create the project only; the dialog stays for what follows. */
  onCreate: (
    input: CreateProjectInput,
    options?: { keepOpen?: boolean },
  ) => Promise<CreateProjectResult>;
  /** A project started from data is complete (or the reader chose to open it
   *  despite problems): close the dialog and go to its page, on `tableId` when
   *  it holds a table to show. */
  onProjectReady: (projectId: string, name: string, tableId?: string | null) => void;
  onCreateFromRun: (input: FromRunRequest, context: RunCreatedContext) => Promise<FromRunReport>;
  /** Leave for the import dialog (a project that exists elsewhere). */
  onOpenImport: () => void;
  /** Where "See an example" goes; null when this server holds no example. */
  exampleHref?: string | null;
  /** The server reads run folders from its own disk (`depictio local`): the
   *  folder field then takes a local path and offers a folder browser. */
  localDataRootsEnabled?: boolean;
  /** The server may browse allowed S3 locations: the folder browser then
   *  offers an S3 side. */
  remoteBrowseEnabled?: boolean;
  /** Why a private bucket's connection details may not be given (public
   *  mode, non-admin); null when they may. */
  privateBucketDisabledReason?: string | null;
}

/** "New project": one screen asking where the results are. What they are, and
 *  the project's name, come after; the rarer ways in stay in a quiet row. */
const CreateProjectModal: React.FC<CreateProjectModalProps> = ({
  opened,
  existingNames,
  onClose,
  onCreate,
  onProjectReady,
  onCreateFromRun,
  onOpenImport,
  exampleHref = null,
  localDataRootsEnabled = false,
  remoteBrowseEnabled = false,
  privateBucketDisabledReason = null,
}) => {
  const accent = useListingAccents('projects');
  /** The empty-project form replaces the data screen. */
  const [emptyProject, setEmptyProject] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isPublic, setIsPublic] = useState(false);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [templatesError, setTemplatesError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset everything whenever the modal opens.
  useEffect(() => {
    if (!opened) return;
    setEmptyProject(false);
    setName('');
    setDescription('');
    setIsPublic(false);
    setError(null);
    setSubmitting(false);
  }, [opened]);

  // Every template the backend knows, fetched fresh per open so a newly
  // registered one shows up without a page reload.
  useEffect(() => {
    if (!opened) return;
    let cancelled = false;
    setTemplatesError(null);
    listProjectTemplates()
      .then((all) => {
        if (!cancelled) setTemplates(all);
      })
      .catch((err: Error) => {
        if (!cancelled) setTemplatesError(err.message || 'Failed to load the list of pipelines.');
      });
    return () => {
      cancelled = true;
    };
  }, [opened]);

  const trimmedName = name.trim();
  const nameAlreadyUsed = existingNames.some((n) => n.toLowerCase() === trimmedName.toLowerCase());
  const canSubmit = trimmedName.length > 0 && !nameAlreadyUsed && !submitting;

  const handleCreate = async () => {
    if (!trimmedName) return;
    setSubmitting(true);
    setError(null);
    try {
      await onCreate({
        name: trimmedName,
        // Legacy field: the type no longer changes what a project can do.
        project_type: 'basic',
        is_public: isPublic,
        ...(description.trim() ? { description: description.trim() } : {}),
      } as CreateProjectInput);
    } catch (err) {
      setError((err as Error).message || 'Failed to create project.');
    } finally {
      setSubmitting(false);
    }
  };

  // Escape and the close button both land here; neither may drop a request
  // that is still being sent.
  const handleModalClose = () => {
    if (!submitting) onClose();
  };

  const otherLink = (label: string, testId: string, props: Record<string, unknown>) => (
    <Anchor size="sm" data-testid={testId} {...props}>
      {label}
    </Anchor>
  );
  const otherRow = (
    <Group gap={6} justify="center" data-testid="create-source-other">
      <Text size="sm" c="dimmed">
        Other:
      </Text>
      {otherLink('An empty project', 'create-source-empty', {
        component: 'button',
        type: 'button',
        onClick: () => setEmptyProject(true),
      })}
      <Text size="sm" c="dimmed">
        ·
      </Text>
      {otherLink('Import a project', 'create-source-import', {
        component: 'button',
        type: 'button',
        onClick: onOpenImport,
      })}
      {exampleHref && (
        <>
          <Text size="sm" c="dimmed">
            ·
          </Text>
          {otherLink('See an example', 'create-source-example', { href: exampleHref })}
        </>
      )}
    </Group>
  );

  const createDialog = (
    <Modal
      stackId={CREATE_STACK_ID}
      className="depictio-form-modal"
      opened={opened}
      onClose={handleModalClose}
      centered
      // What Depictio found: a detection card, a two-column summary and the
      // grouped plan, which a narrower dialog would wrap into noise.
      size={1160}
      withCloseButton
      closeOnClickOutside={false}
      closeOnEscape={!submitting}
      overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
      title={null}
      padding="xl"
    >
      <Stack gap="md">
        <Stack gap={4} align="center">
          <Center>
            <Group gap="xs">
              <Icon
                icon="mdi:folder-plus-outline"
                width={28}
                color={`var(--mantine-color-${accent.secondary}-6)`}
              />
              <Title
                order={2}
                c={accent.secondary}
                style={{ fontFamily: 'Virgil', fontWeight: 400 }}
              >
                Projects
              </Title>
            </Group>
          </Center>
          {!emptyProject && (
            <Text size="sm" c="dimmed" ta="center" data-testid="create-project-intro">
              Show Depictio your results: it works out what they are, and you explore them.
            </Text>
          )}
        </Stack>

        {emptyProject ? (
          <Stack gap="md" data-testid="create-project-empty-form">
            <Button
              variant="subtle"
              color="gray"
              size="compact-sm"
              leftSection={<Icon icon="mdi:arrow-left" width={16} />}
              onClick={() => setEmptyProject(false)}
              disabled={submitting}
              style={{ alignSelf: 'flex-start' }}
              data-testid="create-source-back"
            >
              Start from my data
            </Button>
            <TextInput
              size="md"
              label="Project Name"
              description="Give your project a descriptive name"
              required
              placeholder="Enter project name"
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              leftSection={<Icon icon="mdi:folder-outline" width={16} />}
              error={nameAlreadyUsed ? 'A project with this name already exists.' : undefined}
            />
            <Textarea
              size="md"
              label="Project Description (Optional)"
              description="Describe what this project is about"
              placeholder="Enter project description..."
              value={description}
              onChange={(e) => setDescription(e.currentTarget.value)}
              autosize
              minRows={2}
              maxRows={5}
            />
            <Switch
              size="md"
              label={<span style={{ fontFamily: 'Virgil' }}>Make this project public</span>}
              description="Public projects are visible to all users"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.currentTarget.checked)}
              color={accent.secondary}
            />
            {error && (
              <Alert color="red" variant="light">
                {error}
              </Alert>
            )}
            <Group justify="flex-end">
              <Button
                size="md"
                color={accent.secondary}
                onClick={handleCreate}
                loading={submitting}
                disabled={!canSubmit}
                data-testid="create-project-submit"
              >
                Create project
              </Button>
            </Group>
          </Stack>
        ) : (
          <RunFolderTab
            opened={opened}
            existingNames={existingNames}
            templates={templates}
            templatesError={templatesError}
            localDataRootsEnabled={localDataRootsEnabled}
            remoteBrowseEnabled={remoteBrowseEnabled}
            privateBucketDisabledReason={privateBucketDisabledReason}
            onCreateFromRun={onCreateFromRun}
            onCreateProject={onCreate}
            onProjectReady={onProjectReady}
            submitting={submitting}
            setSubmitting={setSubmitting}
            sourceFooter={otherRow}
          />
        )}
      </Stack>
    </Modal>
  );

  // One stack, so the folder browser gets the higher layer and Escape closes
  // only the top one.
  return <Modal.Stack>{createDialog}</Modal.Stack>;
};

export default CreateProjectModal;
