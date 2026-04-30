import React, { useEffect } from 'react';
import {
  ActionIcon,
  Anchor,
  AppShell,
  Box,
  Button,
  Card,
  Center,
  Container,
  Group,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import { AppSidebar } from '../chrome';

const LOGO_BASE = '/dashboard-beta/logos';

interface ResourceCardProps {
  icon: string;
  title: string;
  description: string;
  buttonLabel: string;
  buttonIcon: string;
  href: string;
}

const ResourceCard: React.FC<ResourceCardProps> = ({
  icon,
  title,
  description,
  buttonLabel,
  buttonIcon,
  href,
}) => (
  <Card withBorder shadow="md" radius="md" p="lg" style={{ textAlign: 'center' }}>
    <Stack gap="sm" align="center">
      <Group justify="center" gap="sm">
        <Icon icon={icon} width={36} />
        <Text size="xl" fw={700}>
          {title}
        </Text>
      </Group>
      <Text size="sm" c="gray">
        {description}
      </Text>
      <Anchor href={href} target="_blank" rel="noreferrer">
        <Button
          variant="filled"
          size="md"
          radius="md"
          color="dark"
          leftSection={<Icon icon={buttonIcon} width={18} />}
        >
          {buttonLabel}
        </Button>
      </Anchor>
    </Stack>
  </Card>
);

interface FundingPartnerCardProps {
  imagePath: string;
  title: string;
  description: string;
  href: string;
  logoHeight?: number;
  textSize?: 'sm' | 'md';
  minHeight?: number;
}

const FundingPartnerCard: React.FC<FundingPartnerCardProps> = ({
  imagePath,
  title,
  description,
  href,
  logoHeight = 100,
  textSize = 'sm',
  minHeight = 350,
}) => (
  <Card
    withBorder
    shadow="md"
    radius="md"
    p="lg"
    style={{
      textAlign: 'center',
      display: 'flex',
      flexDirection: 'column',
      minHeight,
    }}
  >
    <Stack gap="sm" style={{ flex: 1 }}>
      <Center>
        <img
          src={imagePath}
          alt={title}
          style={{ height: logoHeight, objectFit: 'contain', marginBottom: 10 }}
        />
      </Center>
      <Text size="lg" fw="bold">
        {title}
      </Text>
      <Text size={textSize} c="gray" style={{ flex: 1 }}>
        {description}
      </Text>
    </Stack>
    <Anchor href={href} target="_blank" rel="noreferrer" style={{ marginTop: 'auto' }}>
      <Button variant="outline" size="sm" radius="md" mt="md" color="dark">
        Learn More
      </Button>
    </Anchor>
  </Card>
);

const AboutApp: React.FC = () => {
  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(true);

  useEffect(() => {
    document.title = 'Depictio — About';
  }, []);

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
        <Box px="lg" py="md">
          <Container size="xl" py="xl">
            <Stack gap="xl">
              <Paper p="xl" radius="md" mt="xl">
                <Text size="xl" fw="bold" ta="center" mb="md">
                  Resources
                </Text>
                <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xl">
                  <ResourceCard
                    icon="mdi:github"
                    title="GitHub Repository"
                    description="Explore the source code of Depictio on GitHub."
                    buttonLabel="GitHub"
                    buttonIcon="mdi:github"
                    href="https://github.com/depictio/depictio"
                  />
                  <ResourceCard
                    icon="mdi:file-document"
                    title="Documentation"
                    description="Learn how to use Depictio with our comprehensive documentation."
                    buttonLabel="Documentation"
                    buttonIcon="mdi:file-document-box"
                    href="https://depictio.github.io/depictio-docs/"
                  />
                </SimpleGrid>
              </Paper>

              <Paper p="xl" radius="md" mt="xl">
                <Text size="xl" fw="bold" ta="center" mb="xl">
                  Funding
                </Text>
                <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="xl">
                  <FundingPartnerCard
                    imagePath={`${LOGO_BASE}/EN_fundedbyEU_VERTICAL_RGB_POS.png`}
                    title="Marie Sklodowska-Curie Grant"
                    description="This project has received funding from the European Union's Horizon 2020 research and innovation programme under the Marie Sklodowska-Curie grant agreement No 945405"
                    href="https://marie-sklodowska-curie-actions.ec.europa.eu/"
                  />
                  <FundingPartnerCard
                    imagePath={`${LOGO_BASE}/AriseLogo300dpi.png`}
                    title="ARISE Programme"
                    description="ARISE is a postdoctoral research programme for technology developers, hosted at EMBL."
                    href="https://www.embl.org/about/info/arise/"
                  />
                  <FundingPartnerCard
                    imagePath={`${LOGO_BASE}/EMBL_logo_colour_DIGITAL.png`}
                    title="EMBL"
                    description="The European Molecular Biology Laboratory is Europe's flagship laboratory for the life sciences."
                    href="https://www.embl.org/"
                  />
                </SimpleGrid>
              </Paper>

              <Paper p="xl" radius="md" mt="xl">
                <Text size="xl" fw="bold" ta="center" mb="xl">
                  Academic Partners
                </Text>
                <Center>
                  <Box style={{ width: '100%', maxWidth: 500 }}>
                    <FundingPartnerCard
                      imagePath={`${LOGO_BASE}/scilifelab_logo.png`}
                      title="SciLifeLab Data Centre"
                      description="SciLifeLab Data Centre provides data-driven life science research infrastructure and expertise to accelerate open science in Sweden and beyond."
                      href="https://www.scilifelab.se/data/"
                      logoHeight={60}
                      textSize="md"
                      minHeight={300}
                    />
                  </Box>
                </Center>
              </Paper>

              <Text size="xs" c="gray" ta="center" mt="xl" mb="xl">
                2025 Depictio. Developed by Thomas Weber. All rights reserved.
              </Text>
            </Stack>
          </Container>
        </Box>
      </AppShell.Main>
    </AppShell>
  );
};

export default AboutApp;
