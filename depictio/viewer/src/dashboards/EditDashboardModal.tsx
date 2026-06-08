import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Box,
  Button,
  Divider,
  Grid,
  Group,
  Modal,
  Paper,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardListEntry, EditDashboardInput } from 'depictio-react-core';

import {
  WORKFLOW_SYSTEM_OPTIONS,
  WORKFLOW_ICON_MAP,
  WORKFLOW_COLOR_MAP,
  isWorkflowSelected,
} from './lib/workflowIcons';

/** Mantine palette options — empty string = "no override" / inherit. */
const COLOR_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'Auto' },
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

const DEFAULT_ICON = 'mdi:view-dashboard';
const DEFAULT_COLOR = 'orange';

interface EditDashboardModalProps {
  opened: boolean;
  dashboard: DashboardListEntry | null;
  onClose: () => void;
  onSubmit: (dashboardId: string, input: EditDashboardInput) => Promise<void>;
}

const EditDashboardModal: React.FC<EditDashboardModalProps> = ({
  opened,
  dashboard,
  onClose,
  onSubmit,
}) => {
  const [title, setTitle] = useState('');
  const [subtitle, setSubtitle] = useState('');
  const [icon, setIcon] = useState('');
  const [iconColor, setIconColor] = useState('');
  const [workflowSystem, setWorkflowSystem] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Re-sync from the target dashboard whenever the modal opens.
  useEffect(() => {
    if (!opened) return;
    setErrorMessage(null);
    setSubmitting(false);
    if (dashboard) {
      setTitle(dashboard.title || '');
      setSubtitle((dashboard.subtitle as string) || '');
      setIcon(dashboard.icon || '');
      setIconColor(dashboard.icon_color || '');
      setWorkflowSystem((dashboard.workflow_system as string) || '');
    } else {
      setTitle('');
      setSubtitle('');
      setIcon('');
      setIconColor('');
      setWorkflowSystem('');
    }
  }, [opened, dashboard]);

  const trimmedTitle = title.trim();
  const canSubmit = !!dashboard && trimmedTitle.length > 0 && !submitting;

  // When a workflow system is selected, its logo + brand color override the
  // custom icon/color (mirrors Dash's `build_icon_preview`).
  const workflowActive = isWorkflowSelected(workflowSystem);
  const effectiveIcon = workflowActive ? WORKFLOW_ICON_MAP[workflowSystem] : icon.trim();
  const effectiveColor = workflowActive
    ? WORKFLOW_COLOR_MAP[workflowSystem]
    : iconColor || DEFAULT_COLOR;

  const handleSubmit = async () => {
    if (!dashboard || !trimmedTitle) return;
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await onSubmit(dashboard.dashboard_id, {
        title: trimmedTitle || undefined,
        subtitle: subtitle,
        icon: workflowActive ? effectiveIcon : icon.trim() || undefined,
        icon_color: workflowActive ? effectiveColor : iconColor || undefined,
        workflow_system: workflowSystem || undefined,
      });
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to save dashboard');
      setSubmitting(false);
    }
  };

  const previewIsImage =
    !!effectiveIcon &&
    (/^(\/|https?:\/\/|data:)/.test(effectiveIcon) ||
      /\.(png|svg|jpe?g|webp)$/i.test(effectiveIcon));

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      withCloseButton
      centered
      shadow="xl"
      radius="md"
      size={1000}
      padding={28}
      overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
    >
      <Stack gap="lg" data-testid="edit-dashboard-modal">
        {/* Header — mirrors CreateDashboardModal's centered orange title. */}
        <Group justify="center" gap="sm">
          <Icon
            icon="mdi:square-edit-outline"
            width={40}
            height={40}
            color="var(--mantine-color-orange-6)"
          />
          <Title order={1} c="orange" m={0}>
            Edit Dashboard
          </Title>
        </Group>

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
              {errorMessage && (
                <Alert
                  color="red"
                  variant="light"
                  icon={<Icon icon="mdi:alert-circle" />}
                >
                  {errorMessage}
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
                      src={effectiveIcon}
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
                      color={effectiveColor}
                      radius="xl"
                      size="lg"
                      variant="filled"
                      aria-hidden
                    >
                      <Icon
                        icon={effectiveIcon || DEFAULT_ICON}
                        width={24}
                        height={24}
                      />
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
                  disabled={workflowActive}
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
                  disabled={workflowActive}
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
                  value={workflowSystem || 'none'}
                  onChange={(v) => setWorkflowSystem(v ?? '')}
                  leftSection={<Icon icon="mdi:cog-outline" width={16} />}
                  size="sm"
                  allowDeselect={false}
                  comboboxProps={{ withinPortal: false }}
                />
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
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            color="orange"
            radius="md"
            leftSection={<Icon icon="mdi:content-save" width={16} />}
            onClick={handleSubmit}
            loading={submitting}
            disabled={!canSubmit}
          >
            Save Changes
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default EditDashboardModal;
