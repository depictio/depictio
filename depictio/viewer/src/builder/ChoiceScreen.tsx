/**
 * Step 0 of the Add-component flow: a two-tile chooser. The user either builds a
 * component from scratch (the manual stepper) or picks a pre-configured one that
 * depictio recognised from the project's ingested data (the catalog browser).
 *
 * The catalog tile carries the depictio *tools* branding: the pinwheel + violet
 * hammer logo (`tools_catalog_logo.png`) and the violet accent used everywhere
 * the catalog surfaces (`CATALOG_ACCENT` in catalog-preview/shared.tsx,
 * advanced_viz = violet in the builder).
 */
import React from 'react';
import { Badge, Box, Center, Paper, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { Icon } from '@iconify/react';

// Served from depictio/viewer/public/logos under the SPA base (/dashboard/).
const TOOLS_CATALOG_LOGO = '/dashboard/logos/tools_catalog_logo.png';

interface ChoiceCardProps {
  /** Iconify id — used when `image` is not provided. */
  icon?: string;
  /** Image src (e.g. the tools-catalog logo) — takes precedence over `icon`. */
  image?: string;
  iconColor: string;
  iconBg: string;
  accentColor: string;
  title: string;
  description: string;
  badge: string;
  onClick: () => void;
}

const ChoiceCard: React.FC<ChoiceCardProps> = ({
  icon,
  image,
  iconColor,
  iconBg,
  accentColor,
  title,
  description,
  badge,
  onClick,
}) => (
  <Paper
    withBorder
    p="xl"
    radius="md"
    onClick={onClick}
    style={{
      cursor: 'pointer',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 16,
      textAlign: 'center',
      transition: 'transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease',
      minHeight: 260,
      borderColor: `var(--mantine-color-${accentColor}-3)`,
    }}
    styles={{
      root: {
        '&:hover': {
          transform: 'translateY(-4px)',
          boxShadow: 'var(--mantine-shadow-lg)',
          borderColor: `var(--mantine-color-${accentColor}-5)`,
        },
        '&:active': {
          transform: 'translateY(-1px)',
        },
      },
    }}
  >
    <Center
      style={{
        width: 88,
        height: 88,
        borderRadius: image ? 16 : '50%',
        background: iconBg,
        flexShrink: 0,
      }}
    >
      {image ? (
        <img
          src={image}
          alt={title}
          style={{ width: 60, height: 60, objectFit: 'contain' }}
        />
      ) : (
        <Icon icon={icon ?? 'mdi:help-circle'} width={40} color={iconColor} />
      )}
    </Center>

    <Stack gap={6} align="center" style={{ flex: 1 }}>
      <Title order={3} fw={700}>
        {title}
      </Title>
      <Text size="sm" c="dimmed" maw={320}>
        {description}
      </Text>
    </Stack>

    <Badge variant="light" color={accentColor} size="md" radius="xl">
      {badge}
    </Badge>
  </Paper>
);

interface ChoiceScreenProps {
  onManual: () => void;
  onCatalog: () => void;
}

const ChoiceScreen: React.FC<ChoiceScreenProps> = ({ onManual, onCatalog }) => (
  <Center style={{ minHeight: 'calc(100vh - 220px)' }}>
    <Stack gap="xl" align="center" w="100%">
      <Stack gap="xs" align="center">
        <Title order={2} fw={700} ta="center">
          Add a component
        </Title>
        <Text size="md" c="dimmed" ta="center" maw={560}>
          Build one from scratch, or pick a pre-configured visualization Depictio
          recognized from the tools in your project's data.
        </Text>
      </Stack>

      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xl" style={{ maxWidth: 860, width: '100%' }}>
        <ChoiceCard
          icon="mdi:puzzle-plus"
          iconColor="var(--mantine-color-blue-6)"
          iconBg="var(--mantine-color-blue-0)"
          accentColor="blue"
          title="New component"
          description="Choose a component type, connect your data, and configure the design step by step."
          badge="Manual"
          onClick={onManual}
        />
        <ChoiceCard
          image={TOOLS_CATALOG_LOGO}
          iconColor="var(--mantine-color-violet-6)"
          iconBg="var(--mantine-color-violet-0)"
          accentColor="violet"
          title="Pick from catalog"
          description="Depictio recognizes the bioinformatics tools behind your data and suggests ready-to-add visualizations."
          badge="Catalog"
          onClick={onCatalog}
        />
      </SimpleGrid>

      <Box maw={560}>
        <Text size="xs" c="dimmed" ta="center">
          <Icon icon="mdi:information-outline" width={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />
          Catalog suggestions come from the tool outputs found in this project's
          ingested data collections.
        </Text>
      </Box>
    </Stack>
  </Center>
);

export default ChoiceScreen;
