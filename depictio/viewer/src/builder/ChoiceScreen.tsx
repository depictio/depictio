/**
 * Step 0 of the Add-component flow: a two-tile chooser. The user either builds a
 * component from scratch (the manual stepper) or picks a pre-configured one that
 * depictio recognised from the project's ingested data (the catalog browser).
 *
 * The labels, glyphs and accents come from `componentSource.ts`, which the
 * header band above these tiles reads too, so the two cannot disagree about
 * what the catalog looks like.
 */
import React from 'react';
import { Badge, Box, Center, Paper, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { Icon } from '@iconify/react';

import { COMPONENT_SOURCE, type ComponentSourceVisual } from './componentSource';

interface ChoiceCardProps {
  source: ComponentSourceVisual;
  description: string;
  badge: string;
  onClick: () => void;
  testId: string;
}

const ChoiceCard: React.FC<ChoiceCardProps> = ({
  source: { label, icon, image, accent },
  description,
  badge,
  onClick,
  testId,
}) => (
  <Paper
    withBorder
    p="xl"
    radius="md"
    data-testid={testId}
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
      borderColor: `var(--mantine-color-${accent}-3)`,
    }}
    styles={{
      root: {
        '&:hover': {
          transform: 'translateY(-4px)',
          boxShadow: 'var(--mantine-shadow-lg)',
          borderColor: `var(--mantine-color-${accent}-5)`,
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
        background: `var(--mantine-color-${accent}-0)`,
        flexShrink: 0,
      }}
    >
      {image ? (
        <img
          src={image}
          alt={label}
          style={{ width: 60, height: 60, objectFit: 'contain' }}
        />
      ) : (
        <Icon icon={icon} width={40} color={`var(--mantine-color-${accent}-6)`} />
      )}
    </Center>

    <Stack gap={6} align="center" style={{ flex: 1 }}>
      <Title order={3} fw={700}>
        {label}
      </Title>
      <Text size="sm" c="dimmed" maw={320}>
        {description}
      </Text>
    </Stack>

    <Badge variant="light" color={accent} size="md" radius="xl">
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
          source={COMPONENT_SOURCE.manual}
          description="Choose a component type, connect your data, and configure the design step by step."
          badge="Manual"
          testId="component-source-manual"
          onClick={onManual}
        />
        <ChoiceCard
          source={COMPONENT_SOURCE.catalog}
          description="Depictio recognizes the bioinformatics tools behind your data and suggests ready-to-add visualizations."
          badge="Catalog"
          testId="component-source-catalog"
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
