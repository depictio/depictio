import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Box,
  Button,
  Checkbox,
  Divider,
  FileButton,
  Grid,
  Group,
  Modal,
  Paper,
  Select,
  Stack,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type {
  CreateDashboardInput,
  ImportDashboardOptions,
  ProjectListEntry,
} from 'depictio-react-core';

import { UnstyledDropZone } from '../components/UnstyledDropZone';

const COLOR_OPTIONS: { value: string; label: string }[] = [
  { value: 'gray', label: 'Gray' },
  { value: 'red', label: 'Red' },
  { value: 'pink', label: 'Pink' },
  { value: 'grape', label: 'Grape' },
  { value: 'violet', label: 'Violet' },
  { value: 'indigo', label: 'Indigo' },
  { value: 'blue', label: 'Blue' },
  { value: 'cyan', label: 'Cyan' },
  { value: 'teal', label: 'Teal' },
  { value: 'green', label: 'Green' },
  { value: 'lime', label: 'Lime' },
  { value: 'yellow', label: 'Yellow' },
  { value: 'orange', label: 'Orange' },
  { value: 'dark', label: 'Dark' },
];

const WORKFLOW_SYSTEM_OPTIONS: { value: string; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'snakemake', label: 'Snakemake' },
  { value: 'nextflow', label: 'Nextflow' },
  { value: 'galaxy', label: 'Galaxy' },
  { value: 'cwl', label: 'CWL' },
  { value: 'smk_wrapper', label: 'Snakemake wrapper' },
  { value: 'python', label: 'Python' },
];

const DEFAULT_ICON = 'mdi:view-dashboard';
const DEFAULT_COLOR = 'orange';

interface CreateDashboardModalProps {
  opened: boolean;
  projects: ProjectListEntry[];
  existingTitles: string[];
  onClose: () => void;
  onCreate: (input: CreateDashboardInput) => Promise<string>;
  onImport: (
    jsonContent: Record<string, unknown>,
    opts: ImportDashboardOptions,
  ) => Promise<void>;
  /** When true, the Import tab is disabled and the import button stays
   *  inert. Set in public/demo deployments where importing user-supplied
   *  YAML/JSON would let an anonymous visitor write into shared projects. */
  disableImport?: boolean;
}

const projectOptions = (projects: ProjectListEntry[]) =>
  projects
    .map((p) => {
      const value = String(p._id ?? p.id ?? '');
      return value ? { value, label: p.name } : null;
    })
    .filter((o): o is { value: string; label: string } => o !== null);

const CreateDashboardModal: React.FC<CreateDashboardModalProps> = ({
  opened,
  projects,
  existingTitles,
  onClose,
  onCreate,
  onImport,
  disableImport = false,
}) => {
  const [tab, setTab] = useState<'create' | 'import'>('create');

  const [title, setTitle] = useState('');
  const [subtitle, setSubtitle] = useState('');
  const [projectId, setProjectId] = useState<string>('');
  const [icon, setIcon] = useState(DEFAULT_ICON);
  const [iconColor, setIconColor] = useState(DEFAULT_COLOR);
  const [workflowSystem, setWorkflowSystem] = useState('none');
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [importFileName, setImportFileName] = useState<string | null>(null);
  const [importJson, setImportJson] = useState<Record<string, unknown> | null>(null);
  const [importTargetProject, setImportTargetProject] = useState<string | null>(null);
  const [validateIntegrity, setValidateIntegrity] = useState(true);
  const [importSubmitting, setImportSubmitting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  useEffect(() => {
    if (!opened) return;
    setTab('create');
    setTitle('');
    setSubtitle('');
    setProjectId('');
    setIcon(DEFAULT_ICON);
    setIconColor(DEFAULT_COLOR);
    setWorkflowSystem('none');
    setCreateSubmitting(false);
    setCreateError(null);
    setImportFileName(null);
    setImportJson(null);
    setImportTargetProject(null);
    setValidateIntegrity(true);
    setImportSubmitting(false);
    setImportError(null);
  }, [opened]);

  const trimmedTitle = title.trim();
  const titleConflict =
    trimmedTitle.length > 0 && existingTitles.includes(trimmedTitle);
  const canCreate =
    trimmedTitle.length > 0 && projectId.length > 0 && !createSubmitting;

  const handleCreate = async () => {
    if (!canCreate) return;
    setCreateSubmitting(true);
    setCreateError(null);
    try {
      await onCreate({
        title: trimmedTitle,
        subtitle: subtitle.trim() || undefined,
        project_id: projectId,
        icon: icon.trim() || undefined,
        icon_color: iconColor || undefined,
      });
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create dashboard');
      setCreateSubmitting(false);
    }
  };

  const handleFileChosen = async (file: File | null) => {
    setImportError(null);
    if (!file) {
      setImportFileName(null);
      setImportJson(null);
      return;
    }
    setImportFileName(file.name);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as Record<string, unknown>;
      setImportJson(parsed);
    } catch (err) {
      setImportJson(null);
      setImportError(
        err instanceof Error ? `Could not parse JSON: ${err.message}` : 'Could not parse JSON',
      );
    }
  };

  const handleImport = async () => {
    if (!importJson) return;
    setImportSubmitting(true);
    setImportError(null);
    try {
      await onImport(importJson, {
        projectId: importTargetProject || undefined,
        validateIntegrity,
      });
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Failed to import dashboard');
      setImportSubmitting(false);
    }
  };

  const previewIsImage =
    !!icon &&
    (/^(\/|https?:\/\/|data:)/.test(icon) || /\.(png|svg|jpe?g|webp)$/i.test(icon));

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      withCloseButton
      centered
      closeOnClickOutside={false}
      closeOnEscape={false}
      shadow="xl"
      radius="md"
      size={1100}
      zIndex={10000}
      padding={28}
      overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
    >
      <Stack gap="lg">
        <Group justify="center" gap="sm">
          <Icon
            icon="mdi:view-dashboard-outline"
            width={40}
            height={40}
            color="var(--mantine-color-orange-6)"
          />
          <Title order={1} c="orange" m={0}>
            New Dashboard
          </Title>
        </Group>

        <Tabs
          value={tab}
          onChange={(v) => setTab((v as 'create' | 'import') ?? 'create')}
          variant="pills"
          color="orange"
        >
          <Tabs.List justify="center" style={{ gap: 12 }}>
            <Tabs.Tab
              value="create"
              leftSection={<Icon icon="mdi:plus" width={18} />}
            >
              <Text size="md" fw={500} style={{ fontFamily: 'Virgil' }}>
                Create New
              </Text>
            </Tabs.Tab>
            <Tabs.Tab
              value="import"
              leftSection={<Icon icon="mdi:import" width={18} />}
              disabled={disableImport}
              title={
                disableImport
                  ? 'Dashboard import is disabled in public/demo mode'
                  : undefined
              }
            >
              <Text size="md" fw={500} style={{ fontFamily: 'Virgil' }}>
                Import
              </Text>
            </Tabs.Tab>
          </Tabs.List>

        <Tabs.Panel value="create" pt="lg">
          <Stack gap="lg">
            <Grid gutter="xl">
              <Grid.Col span={{ base: 12, sm: 7 }}>
                <Stack gap="md">
                  <TextInput
                    label="Dashboard Title"
                    description="Give your dashboard a descriptive name"
                    placeholder="Enter dashboard title"
                    value={title}
                    onChange={(e) => setTitle(e.currentTarget.value)}
                    required
                    leftSection={<Icon icon="mdi:text-box-outline" width={16} />}
                    data-autofocus
                  />
                  <Textarea
                    label="Dashboard Subtitle (Optional)"
                    description="Add a brief description for your dashboard"
                    placeholder="Enter subtitle (optional)"
                    value={subtitle}
                    onChange={(e) => setSubtitle(e.currentTarget.value)}
                    autosize
                    minRows={2}
                    maxRows={4}
                  />
                  <Select
                    label="Project"
                    description="Select the project this dashboard belongs to"
                    placeholder="Select a project"
                    data={projectOptions(projects)}
                    value={projectId || null}
                    onChange={(v) => setProjectId(v ?? '')}
                    required
                    comboboxProps={{ withinPortal: false }}
                    leftSection={<Icon icon="mdi:folder-outline" width={16} />}
                  />
                  {titleConflict && (
                    <Alert color="red" icon={<Icon icon="mdi:alert" />} variant="light">
                      Dashboard title must be unique
                    </Alert>
                  )}
                  {createError && (
                    <Alert
                      color="red"
                      icon={<Icon icon="mdi:alert-circle" />}
                      variant="light"
                    >
                      {createError}
                    </Alert>
                  )}
                </Stack>
              </Grid.Col>

              <Grid.Col span={{ base: 12, sm: 5 }}>
                <Paper shadow="sm" radius="md" withBorder p="md" h="100%">
                  <Stack gap="md">
                    <Text size="sm" fw={700} c="dimmed">
                      Icon Customization
                    </Text>

                    <Stack gap={4} align="center">
                      <Text size="xs" c="dimmed">
                        Preview
                      </Text>
                      {previewIsImage ? (
                        <img
                          src={icon}
                          alt=""
                          style={{
                            width: 48,
                            height: 48,
                            objectFit: 'contain',
                            borderRadius: '50%',
                          }}
                        />
                      ) : (
                        <ActionIcon
                          color={iconColor || 'orange'}
                          radius="xl"
                          size="lg"
                          variant="filled"
                          aria-hidden
                        >
                          <Icon icon={icon || DEFAULT_ICON} width={24} height={24} />
                        </ActionIcon>
                      )}
                    </Stack>

                    <Divider />

                    <TextInput
                      label="Dashboard Icon"
                      description="Icon from Iconify (e.g., mdi:chart-line)"
                      placeholder="mdi:view-dashboard"
                      value={icon}
                      onChange={(e) => setIcon(e.currentTarget.value)}
                      leftSection={<Icon icon="mdi:emoticon-outline" width={16} />}
                      size="sm"
                    />
                    <Box mt={-8}>
                      <a
                        href="https://pictogrammers.com/library/mdi/"
                        target="_blank"
                        rel="noreferrer"
                        style={{ textDecoration: 'none' }}
                      >
                        <Group gap={4}>
                          <Icon icon="mdi:open-in-new" width={14} />
                          <Text size="xs" c="blue">
                            Browse MDI icons
                          </Text>
                        </Group>
                      </a>
                    </Box>

                    <Select
                      label="Icon Color"
                      description="Color for the dashboard icon"
                      data={COLOR_OPTIONS}
                      value={iconColor}
                      onChange={(v) => setIconColor(v ?? '')}
                      leftSection={<Icon icon="mdi:palette" width={16} />}
                      size="sm"
                      allowDeselect={false}
                      comboboxProps={{ withinPortal: false }}
                    />

                    <Divider
                      label="Workflow System (Optional)"
                      labelPosition="center"
                      mt="xs"
                    />
                    <Select
                      label="Workflow System"
                      description="Auto-set icon based on workflow"
                      data={WORKFLOW_SYSTEM_OPTIONS}
                      value={workflowSystem}
                      onChange={(v) => setWorkflowSystem(v ?? 'none')}
                      leftSection={<Icon icon="mdi:cog-outline" width={16} />}
                      size="sm"
                      allowDeselect={false}
                      comboboxProps={{ withinPortal: false }}
                    />
                    <Text size="xs" c="dimmed" mt={-8}>
                      Selecting a workflow will override the custom icon
                    </Text>
                  </Stack>
                </Paper>
              </Grid.Col>
            </Grid>

            <Group justify="flex-end" gap="md" mt="md">
              <Button
                variant="outline"
                color="gray"
                radius="md"
                onClick={onClose}
                disabled={createSubmitting}
              >
                Cancel
              </Button>
              <Button
                color="orange"
                radius="md"
                leftSection={<Icon icon="mdi:plus" width={16} />}
                loading={createSubmitting}
                disabled={!canCreate || titleConflict}
                onClick={handleCreate}
              >
                Create Dashboard
              </Button>
            </Group>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="import" pt="lg">
          <Stack gap="lg">
            <Grid gutter="xl">
              <Grid.Col span={{ base: 12, sm: 6 }}>
                <Paper p="lg" radius="md" withBorder h="100%">
                  <Stack gap="md">
                    <Text size="sm" fw={500}>
                      Upload JSON File
                    </Text>
                    <FileButton accept="application/json" onChange={handleFileChosen}>
                      {(props) => (
                        <UnstyledDropZone {...props}>
                          <Stack gap="sm" align="center">
                            <Icon
                              icon="mdi:file-upload-outline"
                              width={48}
                              color="var(--mantine-color-gray-6)"
                            />
                            <Text size="sm" c="dimmed">
                              Click to upload
                            </Text>
                            <Text size="xs" c="dimmed">
                              Accepts .json files
                            </Text>
                          </Stack>
                        </UnstyledDropZone>
                      )}
                    </FileButton>
                    {importFileName && (
                      <Group gap="xs">
                        <Icon icon="mdi:file-document-outline" width={16} />
                        <Text size="sm" c="dimmed">
                          {importFileName}
                        </Text>
                      </Group>
                    )}
                  </Stack>
                </Paper>
              </Grid.Col>

              <Grid.Col span={{ base: 12, sm: 6 }}>
                <Stack gap="md">
                  <Alert
                    color="blue"
                    variant="light"
                    icon={<Icon icon="mdi:information-outline" />}
                  >
                    Upload a JSON file exported from Depictio to import a dashboard. The
                    import will validate that data collections exist in the target
                    project.
                  </Alert>
                  <Select
                    label="Target Project"
                    description="Select the project to import the dashboard into"
                    placeholder="Select a project..."
                    data={projectOptions(projects)}
                    value={importTargetProject}
                    onChange={(v) => setImportTargetProject(v)}
                    searchable
                    clearable
                    comboboxProps={{ withinPortal: false }}
                  />
                  <Checkbox
                    label="Validate data integrity (check that data collections exist)"
                    checked={validateIntegrity}
                    onChange={(e) => setValidateIntegrity(e.currentTarget.checked)}
                  />
                  {importError && (
                    <Alert
                      color="red"
                      icon={<Icon icon="mdi:alert-circle" />}
                      variant="light"
                    >
                      {importError}
                    </Alert>
                  )}
                </Stack>
              </Grid.Col>
            </Grid>

            <Group justify="flex-end" gap="md" mt="md">
              <Button
                variant="outline"
                color="gray"
                radius="md"
                onClick={onClose}
                disabled={importSubmitting}
              >
                Cancel
              </Button>
              <Button
                color="orange"
                radius="md"
                leftSection={<Icon icon="mdi:import" width={16} />}
                loading={importSubmitting}
                disabled={disableImport || !importJson || importSubmitting}
                onClick={handleImport}
              >
                Import Dashboard
              </Button>
            </Group>
          </Stack>
        </Tabs.Panel>
      </Tabs>
      </Stack>
    </Modal>
  );
};

export default CreateDashboardModal;
