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
import { ArrowRight, Info } from 'lucide-react';

import { useGlassPages } from '../chrome/variants/glass/pages';
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

/** The Glass tile: a paper button with a tinted glyph well, a title, a line
 *  on what it does, and a pill naming the path. The tint is the source's own
 *  accent, which also lights the tile's ring when it is hovered. */
const GlassChoiceCard: React.FC<ChoiceCardProps> = ({
  source: { label, icon, image, accent },
  description,
  badge,
  onClick,
  testId,
}) => (
  <button
    type="button"
    className="bgl-source"
    data-testid={testId}
    onClick={onClick}
    style={{ ['--bgl-tint' as string]: `var(--mantine-color-${accent}-6)` } as React.CSSProperties}
  >
    <span className="bgl-source-icon">
      {image ? (
        <img src={image} alt={label} />
      ) : (
        <Icon icon={icon} width={40} color="currentColor" />
      )}
    </span>
    <span className="bgl-source-title">{label}</span>
    <span className="bgl-source-desc">{description}</span>
    <span className="bgl-source-pill">
      {badge}
      <ArrowRight size={14} strokeWidth={2} aria-hidden />
    </span>
  </button>
);

interface ChoiceScreenProps {
  onManual: () => void;
  onCatalog: () => void;
}

const MANUAL_COPY =
  'Choose a component type, connect your data, and configure the design step by step.';
const CATALOG_COPY =
  'Depictio recognizes the bioinformatics tools behind your data and suggests ready-to-add visualizations.';

const GlassChoiceScreen: React.FC<ChoiceScreenProps> = ({ onManual, onCatalog }) => (
  <section className="bgl-choice">
    <div className="bgl-choice-hero">
      <h1 className="bgl-choice-title">Add a component</h1>
      <p className="bgl-choice-lead">
        Build one from scratch, or pick a pre-configured visualization Depictio recognized from the
        tools in your project's data.
      </p>
    </div>
    <div className="bgl-choice-grid">
      <GlassChoiceCard
        source={COMPONENT_SOURCE.manual}
        description={MANUAL_COPY}
        badge="Manual"
        testId="component-source-manual"
        onClick={onManual}
      />
      <GlassChoiceCard
        source={COMPONENT_SOURCE.catalog}
        description={CATALOG_COPY}
        badge="Catalog"
        testId="component-source-catalog"
        onClick={onCatalog}
      />
    </div>
    <p className="bgl-choice-note">
      <Info size={14} strokeWidth={1.8} aria-hidden />
      Catalog suggestions come from the tool outputs found in this project's ingested data
      collections.
    </p>
  </section>
);

const ChoiceScreen: React.FC<ChoiceScreenProps> = (props) => {
  const glass = useGlassPages();
  return glass ? <GlassChoiceScreen {...props} /> : <ClassicChoiceScreen {...props} />;
};

const ClassicChoiceScreen: React.FC<ChoiceScreenProps> = ({ onManual, onCatalog }) => (
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
          description={MANUAL_COPY}
          badge="Manual"
          testId="component-source-manual"
          onClick={onManual}
        />
        <ChoiceCard
          source={COMPONENT_SOURCE.catalog}
          description={CATALOG_COPY}
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
