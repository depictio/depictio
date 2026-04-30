import { Center, Image, Paper, Stack, Title, useMantineColorScheme } from '@mantine/core';

interface Props {
  heading: string;
  children: React.ReactNode;
}

/**
 * Card frame for the /auth page: theme-aware logo, "Welcome to Depictio :"
 * heading, and the body (login/register form or public-mode options).
 *
 * Mirrors render_login_form / render_register_form in users_management.py so
 * the React form sits in the same visual frame as the prior Dash version.
 */
export default function AuthCard({ heading, children }: Props) {
  const { colorScheme } = useMantineColorScheme();
  const logoSrc = colorScheme === 'dark'
    ? '/dashboard-beta/logos/logo_white.svg'
    : '/dashboard-beta/logos/logo_black.svg';

  return (
    <Paper
      className="auth-modal-content"
      p="xl"
      radius="md"
      style={{ width: 480, maxWidth: '90vw' }}
    >
      <Stack gap="md">
        <Center>
          <Image src={logoSrc} alt="Depictio" h={60} w="auto" fit="contain" />
        </Center>
        <Center>
          <Title
            order={2}
            ta="center"
            c="gray"
            style={{ fontFamily: 'Virgil' }}
          >
            {heading}
          </Title>
        </Center>
        {children}
      </Stack>
    </Paper>
  );
}
