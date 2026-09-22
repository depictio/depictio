import React from 'react';
import {
  ActionIcon,
  Anchor,
  AppShell,
  Button,
  Card,
  Center,
  Container,
  Group,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import { AppSidebar } from '../chrome';
import { usePageTitle } from '../branding';

const LOGO_BASE = '/dashboard/logos';

// Fixed media slot, so a tall EU logo and a wide EMBL one still put every
// card's title on the same line.
const MEDIA_HEIGHT = 84;

// One column of the three-column funding grid, give or take: it keeps the lone
// partner card the same size as its neighbours above.
const SINGLE_CARD_WIDTH = 380;

interface AboutCardProps {
  /** A logo fills the media slot; without one, `icon` is drawn instead. */
  imagePath?: string;
  icon?: string;
  title: string;
  description: string;
  href: string;
  buttonLabel?: string;
  buttonIcon?: string;
}

/**
 * The single card used by every section: media, title, description, and a
 * link button pinned to the bottom so buttons line up across a row whatever
 * the description's length.
 */
const AboutCard: React.FC<AboutCardProps> = ({
  imagePath,
  icon,
  title,
  description,
  href,
  buttonLabel = 'Learn more',
  buttonIcon,
}) => (
  <Card withBorder shadow="md" radius="md" p="lg" h="100%">
    <Stack gap="sm" align="center" style={{ flex: 1, textAlign: 'center' }}>
      <Center h={MEDIA_HEIGHT}>
        {imagePath ? (
          <img
            src={imagePath}
            alt={title}
            style={{ maxHeight: MEDIA_HEIGHT, maxWidth: '100%', objectFit: 'contain' }}
          />
        ) : (
          icon && <Icon icon={icon} width={48} />
        )}
      </Center>
      <Text size="lg" fw={700}>
        {title}
      </Text>
      <Text size="sm" c="dimmed">
        {description}
      </Text>
      <Anchor href={href} target="_blank" rel="noreferrer" mt="auto">
        <Button
          variant="default"
          size="sm"
          radius="md"
          leftSection={buttonIcon ? <Icon icon={buttonIcon} width={16} /> : undefined}
        >
          {buttonLabel}
        </Button>
      </Anchor>
    </Stack>
  </Card>
);

const AboutSection: React.FC<{ title: string; children: React.ReactNode }> = ({
  title,
  children,
}) => (
  <Stack gap="lg">
    <Title order={3} ta="center">
      {title}
    </Title>
    {children}
  </Stack>
);

const AboutApp: React.FC = () => {
  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(true);

  usePageTitle('About');

  return (
    <AppShell
      layout="alt"
      header={{ height: 64 }}
      navbar={{
        width: 260,
        breakpoint: 'sm',
        collapsed: { mobile: !mobileOpened, desktop: !desktopOpened },
      }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              onClick={toggleMobile}
              hiddenFrom="sm"
              aria-label="Toggle navigation (mobile)"
            >
              <Icon icon="mdi:menu" width={22} />
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              onClick={toggleDesktop}
              visibleFrom="sm"
              aria-label="Toggle navigation"
            >
              <Icon icon="mdi:menu" width={22} />
            </ActionIcon>
            <Icon
              icon="mingcute:question-line"
              width={22}
              color="var(--mantine-color-gray-6)"
            />
            <Title order={3} c="gray">
              About
            </Title>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="about" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Container size="lg" py="xl">
          <Stack gap={48}>
            <AboutSection title="Resources">
              <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xl">
                <AboutCard
                  icon="mdi:github"
                  title="GitHub Repository"
                  description="Explore the source code of Depictio on GitHub."
                  buttonLabel="GitHub"
                  buttonIcon="mdi:github"
                  href="https://github.com/depictio/depictio"
                />
                <AboutCard
                  icon="mdi:file-document"
                  title="Documentation"
                  description="Learn how to use Depictio with our comprehensive documentation."
                  buttonLabel="Documentation"
                  buttonIcon="mdi:file-document-box"
                  href="https://depictio.github.io/depictio-docs/"
                />
              </SimpleGrid>
            </AboutSection>

            <AboutSection title="Funding">
              <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="xl">
                <AboutCard
                  imagePath={`${LOGO_BASE}/EN_fundedbyEU_VERTICAL_RGB_POS.png`}
                  title="Marie Sklodowska-Curie Grant"
                  description="This project has received funding from the European Union's Horizon 2020 research and innovation programme under the Marie Sklodowska-Curie grant agreement No 945405"
                  href="https://marie-sklodowska-curie-actions.ec.europa.eu/"
                />
                <AboutCard
                  imagePath={`${LOGO_BASE}/AriseLogo300dpi.png`}
                  title="ARISE Programme"
                  description="ARISE is a postdoctoral research programme for technology developers, hosted at EMBL."
                  href="https://www.embl.org/about/info/arise/"
                />
                <AboutCard
                  imagePath={`${LOGO_BASE}/EMBL_logo_colour_DIGITAL.png`}
                  title="EMBL"
                  description="The European Molecular Biology Laboratory is Europe's flagship laboratory for the life sciences."
                  href="https://www.embl.org/"
                />
              </SimpleGrid>
            </AboutSection>

            <AboutSection title="Academic Partners">
              <Center>
                <div style={{ width: '100%', maxWidth: SINGLE_CARD_WIDTH }}>
                  <AboutCard
                    imagePath={`${LOGO_BASE}/scilifelab_logo.png`}
                    title="SciLifeLab Data Centre"
                    description="SciLifeLab Data Centre provides data-driven life science research infrastructure and expertise to accelerate open science in Sweden and beyond."
                    href="https://www.scilifelab.se/data/"
                  />
                </div>
              </Center>
            </AboutSection>

            {/* Computed rather than written out, so the notice cannot go
                stale the way the hardcoded 2025 did. */}
            <Text size="xs" c="dimmed" ta="center">
              {new Date().getFullYear()} Depictio. Developed by Thomas Weber. All rights
              reserved.
            </Text>
          </Stack>
        </Container>
      </AppShell.Main>
    </AppShell>
  );
};

export default AboutApp;
