import React, { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  FileButton,
  Group,
  Modal,
  Paper,
  SimpleGrid,
  Stack,
  Stepper,
  Switch,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { CreateProjectInput, CreateProjectResult } from 'depictio-react-core';

type Tab = 'create' | 'import';
type ProjectType = 'basic' | 'advanced';

interface CreateProjectModalProps {
  opened: boolean;
  existingNames: string[];
  onClose: () => void;
  onCreate: (input: CreateProjectInput) => Promise<CreateProjectResult>;
  onImport: (file: File, overwrite: boolean) => Promise<void>;
}

const TEAL_BORDER = 'var(--mantine-color-teal-6)';

const CreateProjectModal: React.FC<CreateProjectModalProps> = ({
  opened,
  existingNames,
  onClose,
  onCreate,
  onImport,
}) => {
  const [tab, setTab] = useState<Tab>('create');
  const [activeStep, setActiveStep] = useState(0);
  const [projectType, setProjectType] = useState<ProjectType | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isPublic, setIsPublic] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Import tab state
  const [importFile, setImportFile] = useState<File | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const importResetRef = useRef<() => void>(null);

  // Reset everything whenever the modal opens.
  useEffect(() => {
    if (!opened) return;
    setTab('create');
    setActiveStep(0);
    setProjectType(null);
    setName('');
    setDescription('');
    setIsPublic(false);
    setImportFile(null);
    setOverwrite(false);
    setError(null);
    setSubmitting(false);
    importResetRef.current?.();
  }, [opened]);

  // Step-1 card click also auto-advances (matches Dash UX).
  const handleSelectType = (type: ProjectType) => {
    if (type === 'advanced') return; // disabled card
    setProjectType(type);
    setActiveStep(1);
  };

  const trimmedName = name.trim();
  const nameAlreadyUsed = existingNames.some(
    (n) => n.toLowerCase() === trimmedName.toLowerCase(),
  );
  const canSubmit =
    !!projectType && trimmedName.length > 0 && !nameAlreadyUsed && !submitting;

  const handleCreate = async () => {
    if (!projectType || !trimmedName) return;
    setSubmitting(true);
    setError(null);
    try {
      await onCreate({
        name: trimmedName,
        project_type: projectType,
        is_public: isPublic,
        ...(description.trim() ? { description: description.trim() } : {}),
      } as CreateProjectInput);
    } catch (err) {
      setError((err as Error).message || 'Failed to create project.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleImport = async () => {
    if (!importFile) return;
    setSubmitting(true);
    setError(null);
    try {
      await onImport(importFile, overwrite);
    } catch (err) {
      setError(
        (err as Error).message ||
          'Failed to import project. The /projects/import endpoint may not yet be available.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      centered
      size="lg"
      withCloseButton
      closeOnClickOutside={false}
      closeOnEscape={!submitting}
      overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
      title={null}
      padding="lg"
    >
      <Stack gap="md">
        {/* Title row — folder+ icon + Virgil "Projects" */}
        <Center>
          <Group gap="xs">
            <Icon
              icon="mdi:folder-plus-outline"
              width={28}
              color="var(--mantine-color-teal-6)"
            />
            <Title
              order={2}
              c="teal"
              style={{ fontFamily: 'Virgil', fontWeight: 400 }}
            >
              Projects
            </Title>
          </Group>
        </Center>

        {/* Pill-style tabs (Create New / Import) */}
        <Tabs
          value={tab}
          onChange={(v) => setTab((v as Tab) || 'create')}
          variant="pills"
          color="teal"
        >
          <Tabs.List justify="center">
            <Tabs.Tab
              value="create"
              leftSection={<Icon icon="mdi:plus" width={16} />}
            >
              Create New
            </Tabs.Tab>
            <Tabs.Tab
              value="import"
              leftSection={<Icon icon="mdi:import" width={16} />}
            >
              Import
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="create" pt="md">
            <Stack gap="md">
              <Stepper
                active={activeStep}
                onStepClick={setActiveStep}
                color="teal"
                size="sm"
                allowNextStepsSelect={false}
              >
                <Stepper.Step
                  label="Project Type"
                  description="Choose basic or advanced"
                >
                  <Stack gap="md" pt="md">
                    <Text ta="center" fw={500}>
                      Choose your project type:
                    </Text>
                    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                      <ProjectTypeCard
                        active={projectType === 'basic'}
                        type="basic"
                        title="Basic Project"
                        description="Perfect for simple data visualization and exploration. No workflows required — upload data collections directly through the UI. Best for individual datasets and quick analysis."
                        icon="mdi:view-dashboard-outline"
                        tag="UI Creation Only"
                        tagColor="cyan"
                        onClick={() => handleSelectType('basic')}
                      />
                      <ProjectTypeCard
                        active={false}
                        type="advanced"
                        title="Advanced Project"
                        description="Designed for complex bioinformatics runs, processing workflows, and data ingestion pipelines. Requires depictio-CLI for project design and workflow management. Best for bioinformatics and computational analysis."
                        icon="mdi:sitemap"
                        tag="Depictio-CLI Only"
                        tagColor="orange"
                        disabled
                      />
                    </SimpleGrid>
                  </Stack>
                </Stepper.Step>

                <Stepper.Step
                  label="Project Details"
                  description="Configure your project"
                >
                  <Stack gap="md" pt="md">
                    <TextInput
                      label="Project Name"
                      description="Give your project a descriptive name"
                      required
                      placeholder="Enter project name"
                      value={name}
                      onChange={(e) => setName(e.currentTarget.value)}
                      leftSection={<Icon icon="mdi:folder-outline" width={16} />}
                      error={
                        nameAlreadyUsed
                          ? 'A project with this name already exists.'
                          : undefined
                      }
                    />
                    <Textarea
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
                      label={
                        <span style={{ fontFamily: 'Virgil' }}>
                          Make this project public
                        </span>
                      }
                      description="Public projects are visible to all users"
                      checked={isPublic}
                      onChange={(e) => setIsPublic(e.currentTarget.checked)}
                      color="teal"
                    />
                  </Stack>
                </Stepper.Step>
              </Stepper>

              {error && (
                <Alert color="red" variant="light">
                  {error}
                </Alert>
              )}

              <Group justify="space-between">
                <Button
                  variant="default"
                  onClick={() => setActiveStep((s) => Math.max(0, s - 1))}
                  disabled={activeStep === 0 || submitting}
                >
                  Previous
                </Button>
                {activeStep === 0 ? (
                  <Button
                    color="teal"
                    onClick={() => setActiveStep(1)}
                    disabled={!projectType}
                  >
                    Next
                  </Button>
                ) : (
                  <Button
                    color="teal"
                    onClick={handleCreate}
                    loading={submitting}
                    disabled={!canSubmit}
                  >
                    Create Project
                  </Button>
                )}
              </Group>
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="import" pt="md">
            <Stack gap="md">
              <Text size="sm" c="dimmed" ta="center">
                Upload a .zip bundle exported from another Depictio instance.
              </Text>
              <FileButton
                resetRef={importResetRef}
                accept=".zip,application/zip,application/x-zip-compressed"
                onChange={(f) => setImportFile(f)}
              >
                {(props) => (
                  <Box
                    {...props}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e: React.KeyboardEvent<HTMLDivElement>) => {
                      if (e.key === 'Enter' || e.key === ' ') props.onClick();
                    }}
                    style={{
                      cursor: 'pointer',
                      border: `2px dashed ${TEAL_BORDER}`,
                      borderRadius: 12,
                      padding: 32,
                      textAlign: 'center' as const,
                      background: 'var(--mantine-color-default-hover)',
                    }}
                  >
                    <Stack gap="xs" align="center">
                      <Icon
                        icon="mdi:file-upload-outline"
                        width={36}
                        color="var(--mantine-color-teal-6)"
                      />
                      <Text fw={500}>
                        {importFile
                          ? importFile.name
                          : 'Drop .zip here or click to browse'}
                      </Text>
                      {importFile && (
                        <Text size="xs" c="dimmed">
                          {(importFile.size / 1024).toFixed(1)} KB
                        </Text>
                      )}
                    </Stack>
                  </Box>
                )}
              </FileButton>
              <Switch
                label={
                  <span style={{ fontFamily: 'Virgil' }}>
                    overwrite if project already exists
                  </span>
                }
                checked={overwrite}
                onChange={(e) => setOverwrite(e.currentTarget.checked)}
                color="teal"
              />
              <Alert
                color="yellow"
                variant="light"
                icon={<Icon icon="mdi:information-outline" width={18} />}
              >
                The /projects/import endpoint is not yet wired on the backend.
                Submitting will fail until that endpoint lands.
              </Alert>
              {error && (
                <Alert color="red" variant="light">
                  {error}
                </Alert>
              )}
              <Button
                color="teal"
                onClick={handleImport}
                disabled={!importFile || submitting}
                loading={submitting}
                leftSection={<Icon icon="mdi:check" width={16} />}
                fullWidth
              >
                Import Project
              </Button>
            </Stack>
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </Modal>
  );
};

interface ProjectTypeCardProps {
  active: boolean;
  type: ProjectType;
  title: string;
  description: string;
  icon: string;
  tag: string;
  tagColor: string;
  disabled?: boolean;
  onClick?: () => void;
}

const ProjectTypeCard: React.FC<ProjectTypeCardProps> = ({
  active,
  type,
  title,
  description,
  icon,
  tag,
  tagColor,
  disabled,
  onClick,
}) => {
  const accent =
    type === 'basic' ? 'var(--mantine-color-teal-6)' : 'var(--mantine-color-orange-6)';
  return (
    <Paper
      withBorder
      radius="md"
      p="lg"
      onClick={disabled ? undefined : onClick}
      style={{
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.55 : 1,
        borderColor: active ? accent : undefined,
        borderWidth: active ? 2 : 1,
        transition: 'border-color 120ms ease',
      }}
    >
      <Stack gap="sm" align="center">
        <Icon icon={icon} width={42} height={42} color={accent} />
        <Title order={4} ta="center">
          {title}
        </Title>
        <Text size="xs" c="dimmed" ta="center" lh={1.4}>
          {description}
        </Text>
        <Badge color={tagColor} variant="light" radius="sm">
          {tag}
        </Badge>
      </Stack>
    </Paper>
  );
};

export default CreateProjectModal;
