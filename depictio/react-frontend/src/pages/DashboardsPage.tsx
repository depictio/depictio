import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconAlertCircle, IconPlus } from "@tabler/icons-react";
import AppShell from "../components/AppShell";
import {
  createDashboard,
  deleteDashboard,
  listDashboards,
  listProjects,
} from "../api/dashboards";
import { useAuthStore } from "../store/auth";

export default function DashboardsPage() {
  const { user } = useAuthStore();
  const queryClient = useQueryClient();

  const [modalOpen, setModalOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [formError, setFormError] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboards"],
    queryFn: listDashboards,
  });

  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
    enabled: modalOpen,
  });

  const createMutation = useMutation({
    mutationFn: () => {
      if (!user) throw new Error("Not authenticated");
      return createDashboard(
        { title, subtitle, projectId: projectId! },
        user,
      );
    },
    onSuccess: () => {
      setModalOpen(false);
      setTitle("");
      setSubtitle("");
      setProjectId(null);
      setFormError("");
      queryClient.invalidateQueries({ queryKey: ["dashboards"] });
    },
    onError: () => setFormError("Failed to create dashboard."),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteDashboard(id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["dashboards"] }),
  });

  const handleSubmit = () => {
    if (!title.trim()) {
      setFormError("Title cannot be empty.");
      return;
    }
    if (!projectId) {
      setFormError("Project not selected.");
      return;
    }
    if (data?.some((d) => d.title === title.trim())) {
      setFormError("Title already exists.");
      return;
    }
    createMutation.mutate();
  };

  const projectOptions =
    projects?.map((p) => ({
      value: p.id,
      label: `${p.name} (${p.id})`,
    })) ?? [];

  return (
    <AppShell>
      <Stack gap="lg">
        <Group justify="space-between">
          <Title order={2}>Dashboards</Title>
          <Button
            id={`create-dashboard-button-${user?.email ?? ""}`}
            leftSection={<IconPlus size={16} />}
            onClick={() => setModalOpen(true)}
          >
            + New Dashboard
          </Button>
        </Group>

        {isLoading && (
          <Center mih={200}>
            <Loader />
          </Center>
        )}

        {error && (
          <Alert
            color="red"
            icon={<IconAlertCircle size={16} />}
            title="Failed to load dashboards"
          >
            {(error as Error).message}
          </Alert>
        )}

        {data && data.length === 0 && (
          <Text c="dimmed">No dashboards yet. Create one to get started.</Text>
        )}

        {data && data.length > 0 && (
          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
            {data.map((d) => (
              <Card
                key={d.dashboard_id}
                className="mantine-Card-root"
                shadow="sm"
                padding="lg"
                radius="md"
                withBorder
              >
                <Stack gap="xs">
                  <Group justify="space-between">
                    <Title order={4}>{d.title}</Title>
                    {d.is_public && <Badge color="green">Public</Badge>}
                  </Group>
                  {d.subtitle && (
                    <Text size="sm" c="dimmed">
                      {d.subtitle}
                    </Text>
                  )}
                  <Group mt="sm">
                    <Button
                      component="a"
                      href={`/dashboard/${d.dashboard_id}`}
                      variant="light"
                      size="xs"
                    >
                      View
                    </Button>
                    <Button
                      component="a"
                      href={`/dashboard/${d.dashboard_id}/edit`}
                      variant="subtle"
                      size="xs"
                    >
                      Edit
                    </Button>
                    <Button
                      variant="subtle"
                      color="red"
                      size="xs"
                      loading={
                        deleteMutation.isPending &&
                        deleteMutation.variables === d.dashboard_id
                      }
                      onClick={() => deleteMutation.mutate(d.dashboard_id)}
                    >
                      Delete
                    </Button>
                  </Group>
                </Stack>
              </Card>
            ))}
          </SimpleGrid>
        )}
      </Stack>

      <Modal
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
        id="dashboard-modal"
        title={<Title order={4}>Create New Dashboard</Title>}
        centered
      >
        <Stack>
          <TextInput
            id="dashboard-title-input"
            label="Title"
            placeholder="Enter dashboard title"
            required
            value={title}
            onChange={(e) => setTitle(e.currentTarget.value)}
          />
          <TextInput
            id="dashboard-subtitle-input"
            label="Subtitle"
            placeholder="Enter subtitle (optional)"
            value={subtitle}
            onChange={(e) => setSubtitle(e.currentTarget.value)}
          />
          <Select
            id="dashboard-projects"
            label="Project"
            placeholder="Select a project"
            data={projectOptions}
            value={projectId}
            onChange={setProjectId}
            searchable
            required
          />
          {formError && (
            <Text id="unique-title-warning" c="red" size="sm" role="alert">
              {formError}
            </Text>
          )}
          <Group justify="flex-end">
            <Button
              id="cancel-dashboard-button"
              variant="default"
              onClick={() => setModalOpen(false)}
            >
              Cancel
            </Button>
            <Button
              id="create-dashboard-submit"
              loading={createMutation.isPending}
              onClick={handleSubmit}
            >
              Create Dashboard
            </Button>
          </Group>
        </Stack>
      </Modal>
    </AppShell>
  );
}
