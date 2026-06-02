import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Card,
  Center,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconAlertCircle, IconPlus } from "@tabler/icons-react";
import AppShell from "../components/AppShell";
import { listDashboards } from "../api/dashboards";
import { useAuthStore } from "../store/auth";

export default function DashboardsPage() {
  const { user } = useAuthStore();
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboards"],
    queryFn: listDashboards,
  });

  return (
    <AppShell>
      <Stack gap="lg">
        <Group justify="space-between">
          <Title order={2}>Dashboards</Title>
          <Button
            id={`create-dashboard-button-${user?.email ?? ""}`}
            leftSection={<IconPlus size={16} />}
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
                  </Group>
                </Stack>
              </Card>
            ))}
          </SimpleGrid>
        )}
      </Stack>
    </AppShell>
  );
}
