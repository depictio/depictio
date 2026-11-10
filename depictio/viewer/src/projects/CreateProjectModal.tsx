import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Center,
  Divider,
  Group,
  Modal,
  SimpleGrid,
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
  onCreateFromRun: (input: FromRunRequest, context: RunCreatedContext) => void;
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

/** "New project", in two screens: what the project is (a name, and whatever
 *  else scopes it), then its data. The rarer ways in stay in a quiet row. */
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
  /** Past the first screen: the project is described, its data comes next. */
  const [onData, setOnData] = useState(false);
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
    setOnData(false);
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
        description: description.trim() || null,
      });
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

  const tinted = `var(--mantine-color-${accent.secondary}-6)`;
  /** A big two-line button: what it does, and what that means. */
  const choice = (icon: string, title: string, detail: string, iconColor?: string) => (
    <Stack gap={2} align="center">
      <Icon icon={icon} width={26} color={iconColor} />
      <Text fw={600} size="md" inherit>
        {title}
      </Text>
      <Text size="xs" inherit style={{ opacity: 0.8, fontWeight: 400, whiteSpace: 'normal' }}>
        {detail}
      </Text>
    </Stack>
  );
  const CHOICE_STYLES = { label: { whiteSpace: 'normal' as const }, inner: { justifyContent: 'center' } };

  const otherRow = (
    <Stack gap="sm" data-testid="create-source-other">
      <Divider label="Or start from" labelPosition="center" />
      <SimpleGrid cols={exampleHref ? 2 : 1}>
        <Button
          variant="default"
          h={92}
                radius="md"
          fullWidth
          styles={CHOICE_STYLES}
          onClick={onOpenImport}
          data-testid="create-source-import"
        >
          {choice('mdi:package-down', 'Import a project', 'One exported from Depictio', tinted)}
        </Button>
        {exampleHref && (
          <Button
            component="a"
            href={exampleHref}
            variant="default"
            h={92}
                radius="md"
            fullWidth
            styles={CHOICE_STYLES}
            data-testid="create-source-example"
          >
            {choice('mdi:compass-outline', 'See an example', 'A finished project to explore', tinted)}
          </Button>
        )}
      </SimpleGrid>
    </Stack>
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
      size={onData ? 1160 : 640}
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
          <Text size="sm" c="dimmed" ta="center" data-testid="create-project-intro">
            {onData
              ? `Add data to “${trimmedName}”: Depictio works out what each file or folder is.`
              : 'Tell Depictio what this project is. You add its data next.'}
          </Text>
        </Stack>

        {!onData ? (
          <Stack gap="md" data-testid="create-project-info">
            <TextInput
              size="md"
              label="Project name"
              required
              placeholder="Enter project name"
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              leftSection={<Icon icon="mdi:folder-outline" width={16} />}
              error={nameAlreadyUsed ? 'A project with this name already exists.' : undefined}
              data-testid="create-project-name"
            />
            <Textarea
              size="md"
              label="Description"
              description="Optional. What this project is about"
              value={description}
              onChange={(e) => setDescription(e.currentTarget.value)}
              autosize
              minRows={2}
              maxRows={5}
              data-testid="create-project-description"
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
            <SimpleGrid cols={2}>
              <Button
                color={accent.secondary}
                h={92}
                radius="md"
                fullWidth
                styles={CHOICE_STYLES}
                onClick={() => setOnData(true)}
                disabled={!canSubmit}
                data-testid="create-project-next"
              >
                {choice('mdi:database-plus-outline', 'Add data', 'Files, a folder or a pipeline run')}
              </Button>
              <Button
                variant="default"
                h={92}
                radius="md"
                fullWidth
                styles={CHOICE_STYLES}
                onClick={handleCreate}
                loading={submitting}
                disabled={!canSubmit}
                data-testid="create-project-submit"
              >
                {choice('mdi:folder-outline', 'Create without data', 'Add data later', tinted)}
              </Button>
            </SimpleGrid>
            {!trimmedName && (
              <Text size="xs" c="dimmed" ta="center" data-testid="create-project-name-hint">
                Name the project to continue.
              </Text>
            )}
            {otherRow}
          </Stack>
        ) : (
          <Stack gap="md">
          <Button
            variant="subtle"
            color="gray"
            size="compact-sm"
            leftSection={<Icon icon="mdi:arrow-left" width={16} />}
            onClick={() => setOnData(false)}
            disabled={submitting}
            style={{ alignSelf: 'flex-start' }}
            data-testid="create-project-back"
          >
            Project details
          </Button>
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
            projectInfo={{
              name: trimmedName,
              description: description.trim(),
              isPublic,
            }}
          />
          </Stack>
        )}
      </Stack>
    </Modal>
  );

  // One stack, so the folder browser gets the higher layer and Escape closes
  // only the top one.
  return <Modal.Stack>{createDialog}</Modal.Stack>;
};

export default CreateProjectModal;
