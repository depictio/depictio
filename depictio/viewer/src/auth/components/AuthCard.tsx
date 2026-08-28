import { Center, Paper, Stack, Title } from '@mantine/core';

import BrandLogo from '../../chrome/BrandLogo';
import PoweredBy from '../../chrome/PoweredBy';
import { useBrandLogoMode } from '../../chrome/useBrandLogoMode';
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
  const logoMode = useBrandLogoMode();
  // The space before the colon is a normal break opportunity, so a heading long
  // enough to wrap (any instance name longer than "Depictio") leaves the colon
  // stranded alone on the second line. A non-breaking space keeps it welded to
  // the last word; the heading still wraps, just never on that final space.
  const resolvedHeading = (
    branding?.app_name ? heading.replace('Depictio', branding.app_name) : heading
  ).replace(' :', '\u00A0:');

  return (
    <Paper
      className="auth-modal-content"
      data-testid="modal-content"
      p="xl"
      radius="md"
      style={{ width: 480, maxWidth: '90vw' }}
    >
      <Stack gap="md">
        {/* A custom mark gets the room the depictio wordmark does not need: the
            wordmark is a wide lockup that reads fine at 60, a custom logo is as
            often a square badge that looks incidental at that height. Width
            stays capped by BrandLogo's `maxWidth: 100%`. The attribution sits
            under the mark it qualifies, and renders itself only once that mark
            is no longer the depictio one (see PoweredBy). */}
        <Stack gap={6} align="center">
          <BrandLogo height={logoMode === 'custom' ? 110 : 60} />
          <PoweredBy />
        </Stack>
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
