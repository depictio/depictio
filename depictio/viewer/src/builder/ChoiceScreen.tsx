import React from 'react';
import { Badge, Center, Group, Paper, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { Icon } from '@iconify/react';

interface ChoiceCardProps {
  icon: string;
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
      transition: 'transform 180ms ease, box-shadow 180ms ease',
      minHeight: 260,
    }}
    styles={{
      root: {
        '&:hover': {
          transform: 'translateY(-4px)',
          boxShadow: 'var(--mantine-shadow-lg)',
        },
        '&:active': {
          transform: 'translateY(-1px)',
        },
      },
    }}
  >
    <Center
      style={{
        width: 80,
        height: 80,
        borderRadius: '50%',
        background: iconBg,
        flexShrink: 0,
      }}
    >
      <Icon icon={icon} width={40} color={iconColor} />
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
  <Center style={{ minHeight: 'calc(100vh - 180px)' }}>
    <Stack gap="xl" align="center" w="100%">
      <Stack gap="xs" align="center">
        <Title order={2} fw={700} ta="center">
          Add a component
        </Title>
        <Text size="md" c="dimmed" ta="center" maw={520}>
          Build from scratch or let Depictio suggest visualizations based on your data.
        </Text>
      </Stack>

      <SimpleGrid cols={2} spacing="xl" style={{ maxWidth: 860, width: '100%' }}>
        <ChoiceCard
          icon="mdi:puzzle-plus"
          iconColor="var(--mantine-color-blue-6)"
          iconBg="var(--mantine-color-blue-0)"
          accentColor="blue"
          title="Build manually"
          description="Choose a component type, connect your data, and configure the design step by step."
          badge="Manual"
          onClick={onManual}
        />
        <ChoiceCard
          icon="mdi:database-search"
          iconColor="var(--mantine-color-teal-6)"
          iconBg="var(--mantine-color-teal-0)"
          accentColor="teal"
          title="Start from Catalog"
          description="Depictio recognizes your data files and suggests pre-configured visualizations."
          badge="Catalog-assisted"
          onClick={onCatalog}
        />
      </SimpleGrid>
    </Stack>
  </Center>
);

export default ChoiceScreen;
