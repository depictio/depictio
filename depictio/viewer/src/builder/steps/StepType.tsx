/**
 * Step 0: pick a component type. Mirrors
 * depictio/dash/layouts/stepper_parts/part_two.py:_build_component_selection_layout.
 *
 * Layout:
 *  - section title "Select Component Type" (order=3) + description
 *  - Divider
 *  - 3-col CSS grid, gap 1.5rem, max 900px, centered
 *  - if cards.length % 3 == 1, the last card sits in column 2 (middle)
 *  - clicking a card immediately advances to step 1
 */
import React, { useMemo } from 'react';
import {
  Card,
  Center,
  Divider,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { useBuilderStore } from '../store/useBuilderStore';
import { COMPONENT_TYPES } from '../componentTypes';
import type { ComponentTypeMeta } from '../componentTypes';
import type { ComponentType } from '../store/useBuilderStore';

const StepType: React.FC = () => {
  const componentType = useBuilderStore((s) => s.componentType);
  const setComponentType = useBuilderStore((s) => s.setComponentType);
  const setStep = useBuilderStore((s) => s.setStep);
  const dcConfigType = useBuilderStore((s) => s.dcConfigType);

  // For consistency with Dash, the type grid is type-first; data is picked in
  // the next step. dcConfigType is null at this point unless edit mode.
  const cards = useMemo(() => {
    return COMPONENT_TYPES.map((t) => {
      const disabled =
        t.type === 'figure' && dcConfigType?.toLowerCase() === 'multiqc';
      return { ...t, disabled };
    });
  }, [dcConfigType]);

  const lastIndexInCol2 = cards.length % 3 === 1 ? cards.length - 1 : -1;

  const onPick = (t: ComponentType) => {
    setComponentType(t);
    // Mirror Dash: card click immediately advances to the next step.
    setStep(1);
  };

  return (
    <Stack gap="md" justify="center" align="center" pt="md">
      <Stack gap="xs" align="center">
        <Title order={3} ta="center" fw={700} mb="xs">
          Select Component Type
        </Title>
        <Text size="sm" c="gray" ta="center" mb="lg">
          Choose the type of component you want to add to your dashboard
        </Text>
      </Stack>
      <Divider variant="solid" w="100%" />

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: '1.5rem',
          maxWidth: 900,
          width: '100%',
          margin: '2rem auto',
          padding: '0 1rem',
        }}
      >
        {cards.map((t, i) => (
          <TypeCard
            key={t.type}
            meta={t}
            disabled={t.disabled}
            selected={componentType === t.type}
            onClick={() => !t.disabled && onPick(t.type as ComponentType)}
            style={i === lastIndexInCol2 ? { gridColumn: '2' } : undefined}
          />
        ))}
      </div>
    </Stack>
  );
};

interface TypeCardProps {
  meta: ComponentTypeMeta;
  selected: boolean;
  disabled: boolean;
  onClick: () => void;
  style?: React.CSSProperties;
}

const TypeCard: React.FC<TypeCardProps> = ({
  meta,
  selected,
  disabled,
  onClick,
  style,
}) => {
  return (
    <Card
      withBorder
      radius="md"
      p="lg"
      shadow={selected ? 'md' : 'sm'}
      onClick={onClick}
      className="component-selection-card"
      style={{
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        textAlign: 'center',
        transition: 'transform 0.2s ease, box-shadow 0.2s ease',
        transform: selected ? 'translateY(-2px)' : undefined,
        borderColor: selected ? 'var(--mantine-color-blue-5)' : undefined,
        borderWidth: selected ? 2 : 1,
        height: '100%',
        ...style,
      }}
    >
      <Stack gap="sm" align="center">
        <Center
          style={{
            width: 48,
            height: 48,
            borderRadius: 12,
            background: meta.iconBg,
            margin: '0 auto 1rem auto',
          }}
        >
          {meta.type === 'multiqc' ? (
            <img
              src="/dashboard-beta/logos/multiqc_icon_dark.svg"
              alt="MultiQC"
              className="multiqc-icon-themed"
              style={{ width: 44, height: 44, objectFit: 'contain' }}
            />
          ) : (
            <Icon icon={meta.icon} width={24} color="white" />
          )}
        </Center>
        <Text fw={700} size="lg" ta="center">
          {meta.label}
        </Text>
        <Text size="sm" c="gray" ta="center" mt="xs">
          {meta.description}
        </Text>
      </Stack>
    </Card>
  );
};

export default StepType;
