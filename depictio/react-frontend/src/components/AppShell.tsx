import { ReactNode } from "react";
import {
  AppShell as MantineAppShell,
  Burger,
  Group,
  Title,
  Button,
  Box,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/auth";
import ThemeToggle from "./ThemeToggle";

interface Props {
  children: ReactNode;
}

export default function AppShell({ children }: Props) {
  const [opened, { toggle }] = useDisclosure();
  const navigate = useNavigate();
  const { clear, user } = useAuthStore();

  const handleLogout = () => {
    clear();
    navigate("/auth", { replace: true });
  };

  return (
    <MantineAppShell
      id="app-shell"
      header={{ height: 56 }}
      navbar={{
        width: 220,
        breakpoint: "sm",
        collapsed: { mobile: !opened },
      }}
      padding="md"
    >
      <MantineAppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
            />
            <Title order={4}>Depictio</Title>
          </Group>
          <Group gap="xs">
            {user?.email && (
              <Box id="user-info-placeholder" component="span" fz="sm">
                {user.email}
              </Box>
            )}
            <ThemeToggle />
            <Button
              id="logout-button"
              variant="light"
              size="xs"
              onClick={handleLogout}
            >
              Logout
            </Button>
          </Group>
        </Group>
      </MantineAppShell.Header>

      <MantineAppShell.Navbar p="md">
        <Button variant="subtle" onClick={() => navigate("/dashboards")}>
          Dashboards
        </Button>
      </MantineAppShell.Navbar>

      <MantineAppShell.Main>
        <Box id="page-content">{children}</Box>
      </MantineAppShell.Main>
    </MantineAppShell>
  );
}
