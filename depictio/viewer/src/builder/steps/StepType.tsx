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
import { useGlassPages } from '../../chrome/variants/glass/pages';
import { stepAfterType, useBuilderStore } from '../store/useBuilderStore';
import MultiQCLogo from '../shared/MultiQCLogo';
import { COMPONENT_TYPES } from '../componentTypes';
import type { ComponentTypeMeta } from '../componentTypes';
import type { ComponentType } from '../store/useBuilderStore';

const StepType: React.FC = () => {
  const componentType = useBuilderStore((s) => s.componentType);
  const setComponentType = useBuilderStore((s) => s.setComponentType);
  const setStep = useBuilderStore((s) => s.setStep);
  const dcConfigType = useBuilderStore((s) => s.dcConfigType);
  const glass = useGlassPages();

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
    // Mirror Dash: card click immediately advances to the next step. Text
    // components skip Data Source (hidden for text) and land on the step
    // after it (Describe in AI mode, Design otherwise), matching the
    // Next-button + stepper-click handlers in CreateComponentPage.
    setStep(stepAfterType(t));
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
        data-tour-id="component-type-grid"
        className={glass ? 'bgl-type-grid' : undefined}
        style={
          glass
            ? undefined
            : {
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: '1.5rem',
                maxWidth: 900,
                width: '100%',
                margin: '2rem auto',
                padding: '0 1rem',
              }
        }
      >
        {cards.map((t, i) => (
          <TypeCard
            key={t.type}
            meta={t}
            disabled={t.disabled}
            selected={componentType === t.type}
            onClick={() => !t.disabled && onPick(t.type as ComponentType)}
            style={i === lastIndexInCol2 && !glass ? { gridColumn: '2' } : undefined}
            lastInMiddle={i === lastIndexInCol2}
          />
        ))}
      </div>
    </Stack>
  );
};

/** What a TypeCard needs: the builder's meta, or a synthetic entry such as
 *  the Describe step's "Auto" tile (hence `type: string`). */
export type TypeCardMeta = Omit<ComponentTypeMeta, 'type'> & { type: string };

export interface TypeCardProps {
  meta: TypeCardMeta;
  selected: boolean;
  /** Dimmed and inert. Surfaces that offer every type (the AI Describe step)
   *  simply leave it out. */
  disabled?: boolean;
  onClick: () => void;
  style?: React.CSSProperties;
  /** The odd card out of a three-column grid, centred under the rest. */
  lastInMiddle?: boolean;
  /** Dense variant (icon tile + label, no description) for surfaces that
   *  show the whole type set next to other controls, like the AI Describe
   *  step. Same meta, same selection treatment, same test id. */
  compact?: boolean;
  /** Overrides the default `component-type-<type>` test id. */
  testId?: string;
  /** Accent colour of the selected border; the manual grid keeps blue. */
  accent?: string;
}

export const TypeCard: React.FC<TypeCardProps> = ({
  meta,
  selected,
  disabled = false,
  onClick,
  style,
  lastInMiddle,
  compact = false,
  testId,
  accent = 'blue',
}) => {
  const glass = useGlassPages();
  const tile = compact ? 36 : 48;
  // The dense Describe-step tile has no Glass form: it sits beside other controls.
  if (glass && !compact) {
    return (
      <button
        type="button"
        className="bgl-tile component-selection-card"
        // Type-scoped hook for e2e, as on the Classic card below.
        data-testid={testId ?? `component-type-${meta.type}`}
        data-selected={selected || undefined}
        data-col2={lastInMiddle || undefined}
        aria-pressed={selected}
        aria-disabled={disabled || undefined}
        onClick={onClick}
        style={{ ['--bgl-tint' as string]: meta.iconBg } as React.CSSProperties}
      >
        <span className="bgl-tile-icon" data-brand={meta.type === 'multiqc' ? '' : undefined}>
          {meta.type === 'multiqc' ? (
            <MultiQCLogo size={34} />
          ) : (
            <Icon icon={meta.icon} width={26} color="currentColor" />
          )}
        </span>
        <span className="bgl-tile-label">{meta.label}</span>
        <span className="bgl-tile-desc">{meta.description}</span>
      </button>
    );
  }
  return (
    <Card
      withBorder
      radius="md"
      p={compact ? 'xs' : 'lg'}
      shadow={selected ? 'md' : 'sm'}
      onClick={onClick}
      className="component-selection-card"
      // Type-scoped hook for e2e: several cards mention another card's label in
      // their description ("Interactive data visualizations" on Figure,
      // "Interactive image grid" on Image), so a text filter over
      // .component-selection-card cannot address one card unambiguously.
      data-testid={testId ?? `component-type-${meta.type}`}
      style={{
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        textAlign: 'center',
        transition: 'transform 0.2s ease, box-shadow 0.2s ease',
        transform: selected ? 'translateY(-2px)' : undefined,
        borderColor: selected ? `var(--mantine-color-${accent}-5)` : undefined,
        borderWidth: selected ? 2 : 1,
        height: '100%',
        ...style,
      }}
    >
      <Stack gap={compact ? 4 : 'sm'} align="center">
        <Center
          style={{
            width: tile,
            height: tile,
            borderRadius: compact ? 10 : 12,
            background: meta.iconBg,
            margin: compact ? '0 auto' : '0 auto 1rem auto',
          }}
        >
          {meta.type === 'multiqc' ? (
            <MultiQCLogo size={tile - 4} />
          ) : (
            <Icon icon={meta.icon} width={compact ? 20 : 24} color="white" />
          )}
        </Center>
        <Text fw={compact ? 600 : 700} size={compact ? 'sm' : 'lg'} ta="center">
          {meta.label}
        </Text>
        {!compact && (
          <Text size="sm" c="gray" ta="center" mt="xs">
            {meta.description}
          </Text>
        )}
      </Stack>
    </Card>
  );
};

export default StepType;
