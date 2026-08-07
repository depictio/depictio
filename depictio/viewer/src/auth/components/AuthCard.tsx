import { Center, Paper, Stack, Title } from '@mantine/core';

import BrandLogo from '../../chrome/BrandLogo';
import { useBranding } from '../../branding';

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
 *
 * On a branded instance (#397) the logo is the deployment's own and the
 * literal "Depictio" in headings is swapped for the instance name — done here
 * rather than at every call site so the greeting logic lives in one place.
 */
export default function AuthCard({ heading, children }: Props) {
  const branding = useBranding();
  const resolvedHeading = branding?.app_name
    ? heading.replace('Depictio', branding.app_name)
    : heading;

  return (
    <Paper
      className="auth-modal-content"
      data-testid="modal-content"
      p="xl"
      radius="md"
      style={{ width: 480, maxWidth: '90vw' }}
    >
      <Stack gap="md">
        <Center>
          <BrandLogo height={60} />
        </Center>
        <Center>
          <Title
            order={2}
            ta="center"
            c="gray"
            style={{ fontFamily: 'Virgil' }}
          >
            {resolvedHeading}
          </Title>
        </Center>
        {children}
      </Stack>
    </Paper>
  );
}
