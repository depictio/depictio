import { Card, Stack, Text, Title } from "@mantine/core";
import AppShell from "../components/AppShell";
import { useAuthStore } from "../store/auth";

export default function ProfilePage() {
  const { user } = useAuthStore();

  return (
    <AppShell>
      <Stack gap="lg">
        <Title order={2}>Profile</Title>
        <Card withBorder padding="lg" radius="md" maw={480}>
          <Stack gap="xs">
            <Text size="sm" c="dimmed">
              Email
            </Text>
            <Text id="profile-email">{user?.email ?? "—"}</Text>
            <Text size="sm" c="dimmed" mt="sm">
              Role
            </Text>
            <Text>{user?.is_admin ? "Administrator" : "User"}</Text>
          </Stack>
        </Card>
      </Stack>
    </AppShell>
  );
}
