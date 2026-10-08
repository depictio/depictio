/**
 * Shared layout for a panel of settings grouped into collapsible sections.
 *
 * Used by the Settings drawer and by every component builder's control column,
 * so both read as the same kind of thing: a list of sections, each headed by
 * an icon, a title and a one-line subtitle saying what it controls, and inside
 * each one a column of fields, each a label, a short dimmed description, then
 * the control.
 *
 * - `SectionAccordion` is the container (a Mantine `Accordion`, separated
 *   variant, several sections open at once).
 * - `SettingsSection` is one item in it.
 * - `Field` / `SwitchField` lay out one setting inside a section.
 * - `useOpenSections` keeps which sections are open, remembered in
 *   localStorage under a caller-chosen key.
 * - `GatedButton` / `DisabledReason` show why an action is unavailable: on
 *   hover, and in a dimmed line that stays readable without a pointer.
 * - `EmptyState` / `ErrorAlert` are a section's nothing-here-yet and
 *   something-failed states.
 */
import React from 'react';
import {
  Accordion,
  Alert,
  Button,
  Group,
  Stack,
  Switch,
  Text,
  ThemeIcon,
  Tooltip,
  type AlertProps,
  type ButtonProps,
} from '@mantine/core';
import type { MantineColor } from '@mantine/core';
import { Icon } from '@iconify/react';

import { Z_LAYERS } from 'depictio-react-core';

// ---------------------------------------------------------------------------
// Section header
// ---------------------------------------------------------------------------

/**
 * Header of one section: icon, title, and a one-line subtitle saying what the
 * section is for. Every section uses this one, so a panel reads as a list of
 * like things rather than a stack of ad-hoc headings.
 *
 * `color` tints the icon for a dialog with its own accent (the section modal's
 * grape); without it the icon takes the theme's primary colour.
 */
export const SectionHeader: React.FC<{
  icon: string;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  color?: MantineColor;
}> = ({ icon, title, subtitle, color }) => (
  <Group gap="sm" wrap="nowrap" align="center">
    <ThemeIcon variant="light" size="md" radius="md" color={color}>
      <Icon icon={icon} width={16} />
    </ThemeIcon>
    <Stack gap={0} style={{ minWidth: 0 }}>
      <Text size="sm" fw={600} lh={1.3}>
        {title}
      </Text>
      {subtitle && (
        <Text size="xs" c="dimmed" lh={1.3}>
          {subtitle}
        </Text>
      )}
    </Stack>
  </Group>
);

// ---------------------------------------------------------------------------
// Fields
// ---------------------------------------------------------------------------

/**
 * One setting inside a section: label, a short dimmed description, then the
 * control. `inline` puts the control to the right of the text instead (for a
 * switch), keeping the same label / description pair.
 *
 * Mantine inputs that take their own `label` / `description` already render
 * this same stack (sm 500 label, xs dimmed description), so they need no
 * wrapper; this is for the controls that do not (segmented controls,
 * sliders, switches, custom widgets).
 */
export const Field: React.FC<{
  label: React.ReactNode;
  description?: React.ReactNode;
  /** id of the control the label names (for a switch, whose own label is not used). */
  htmlFor?: string;
  inline?: boolean;
  testId?: string;
  children: React.ReactNode;
}> = ({ label, description, htmlFor, inline = false, testId, children }) => {
  const text = (
    <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
      <Text
        size="sm"
        fw={500}
        lh={1.3}
        component={htmlFor ? 'label' : 'div'}
        htmlFor={htmlFor}
        style={htmlFor ? { cursor: 'pointer' } : undefined}
      >
        {label}
      </Text>
      {description && (
        <Text size="xs" c="dimmed" lh={1.35}>
          {description}
        </Text>
      )}
    </Stack>
  );
  if (inline) {
    return (
      <Group gap="md" wrap="nowrap" align="flex-start" justify="space-between" data-testid={testId}>
        {text}
        <div style={{ flexShrink: 0, paddingTop: 2 }}>{children}</div>
      </Group>
    );
  }
  return (
    <Stack gap={6} data-testid={testId}>
      {text}
      {children}
    </Stack>
  );
};

/** A switch laid out as a Field: the text on the left labels it. */
export const SwitchField: React.FC<{
  label: React.ReactNode;
  description?: React.ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  testId?: string;
}> = ({ label, description, checked, onChange, disabled, testId }) => {
  const id = React.useId();
  return (
    <Field label={label} description={description} htmlFor={id} inline>
      <Switch
        id={id}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.currentTarget.checked)}
        data-testid={testId}
      />
    </Field>
  );
};

// ---------------------------------------------------------------------------
// Unavailable actions
// ---------------------------------------------------------------------------

export type GatedButtonProps = ButtonProps &
  Omit<React.ComponentPropsWithoutRef<'button'>, keyof ButtonProps> & {
    /** Why the action is unavailable; null or empty when it is available. */
    reason?: string | null;
  };

/**
 * A button that stays visible when the action is unavailable and says why on
 * hover. A natively disabled button swallows the pointer events a tooltip
 * needs, so this one is marked `data-disabled` and `aria-disabled` instead
 * (Mantine's documented pattern) and ignores clicks while gated. Pair it with
 * a `DisabledReason` line for readers without a pointer.
 */
export const GatedButton = React.forwardRef<HTMLButtonElement, GatedButtonProps>(
  ({ reason, onClick, ...props }, ref) => {
    const gated = Boolean(reason);
    return (
      <Tooltip
        label={reason ?? ''}
        disabled={!gated}
        withArrow
        multiline
        maw={280}
        zIndex={Z_LAYERS.tooltip}
      >
        <Button
          ref={ref}
          {...props}
          data-disabled={gated || undefined}
          aria-disabled={gated || undefined}
          onClick={(event) => {
            if (gated) {
              event.preventDefault();
              return;
            }
            onClick?.(event);
          }}
        />
      </Tooltip>
    );
  },
);
GatedButton.displayName = 'GatedButton';

/** The dimmed line under an unavailable action, saying why. Renders nothing
 *  when there is no reason. */
export const DisabledReason: React.FC<{
  reason: string | null | undefined;
  icon?: string;
  testId?: string;
}> = ({ reason, icon = 'mdi:lock-outline', testId }) =>
  reason ? (
    <Group gap={6} wrap="nowrap" align="flex-start" c="dimmed" data-testid={testId}>
      <Icon icon={icon} width={14} style={{ flexShrink: 0, marginTop: 2 }} />
      <Text size="xs" c="dimmed" lh={1.35}>
        {reason}
      </Text>
    </Group>
  ) : null;

// ---------------------------------------------------------------------------
// Empty and failed states
// ---------------------------------------------------------------------------

/** What a section shows when it has nothing to act on yet: a dimmed glyph, a
 *  short title, and a line saying why and what to do about it. */
export const EmptyState: React.FC<{
  icon: string;
  title: React.ReactNode;
  testId?: string;
  children: React.ReactNode;
}> = ({ icon, title, testId, children }) => (
  <Group gap="sm" wrap="nowrap" align="flex-start" data-testid={testId}>
    <ThemeIcon variant="light" color="gray" size="lg" radius="md">
      <Icon icon={icon} width={20} />
    </ThemeIcon>
    <Stack gap={2} style={{ minWidth: 0 }}>
      <Text size="sm" fw={500}>
        {title}
      </Text>
      <Text size="xs" c="dimmed" lh={1.35}>
        {children}
      </Text>
    </Stack>
  </Group>
);

/** A load or an action that failed, with the server's message as the body.
 *  Takes every `Alert` prop except the look, such as a `title` or a
 *  `data-testid`. */
export const ErrorAlert: React.FC<Omit<AlertProps, 'color' | 'variant' | 'icon'>> = (props) => (
  <Alert
    color="red"
    variant="light"
    icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
    {...props}
  />
);

// ---------------------------------------------------------------------------
// Accordion
// ---------------------------------------------------------------------------

/**
 * The section container: several sections open at once, separated cards, and
 * a flex gap rather than the separated variant's md margin between items, so
 * a panel stays compact.
 */
export const SectionAccordion: React.FC<{
  value: string[];
  onChange: (value: string[]) => void;
  testId?: string;
  children: React.ReactNode;
}> = ({ value, onChange, testId, children }) => (
  <Accordion
    multiple
    variant="separated"
    radius="md"
    chevronPosition="right"
    value={value}
    onChange={onChange}
    data-testid={testId}
    style={{ display: 'flex', flexDirection: 'column', gap: 'var(--mantine-spacing-xs)' }}
    styles={{
      item: { marginTop: 0 },
      control: { paddingInline: 'var(--mantine-spacing-sm)' },
      label: { paddingBlock: 'var(--mantine-spacing-xs)' },
      content: {
        paddingInline: 'var(--mantine-spacing-sm)',
        paddingTop: 'var(--mantine-spacing-xs)',
        paddingBottom: 'var(--mantine-spacing-sm)',
      },
    }}
  >
    {children}
  </Accordion>
);

/** One section: a `SectionHeader` control over a panel of fields. */
export const SettingsSection: React.FC<{
  value: string;
  icon: string;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  color?: MantineColor;
  testId?: string;
  children: React.ReactNode;
}> = ({ value, icon, title, subtitle, color, testId, children }) => (
  <Accordion.Item value={value} data-testid={testId}>
    <Accordion.Control>
      <SectionHeader icon={icon} title={title} subtitle={subtitle} color={color} />
    </Accordion.Control>
    <Accordion.Panel>{children}</Accordion.Panel>
  </Accordion.Item>
);

// ---------------------------------------------------------------------------
// Remembered open state
// ---------------------------------------------------------------------------

function readStored(storageKey: string): string[] | null {
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.every((v) => typeof v === 'string')) {
        return parsed as string[];
      }
    }
  } catch {
    // Storage blocked or corrupt: fall back to the defaults.
  }
  return null;
}

function writeStored(storageKey: string, value: string[]) {
  try {
    localStorage.setItem(storageKey, JSON.stringify(value));
  } catch {
    // Remembering the open sections is a convenience; ignore failures.
  }
}

/**
 * Which sections of a `SectionAccordion` are open, remembered per browser
 * under `storageKey`.
 *
 * Without a stored value the panel opens on `defaults`. `pinned` sections are
 * open on every mount whatever was remembered: a builder's required section
 * must not start folded because it was folded on the last component.
 */
export function useOpenSections(
  storageKey: string,
  defaults: string[],
  pinned: string[] = [],
): [string[], (value: string[]) => void] {
  const [open, setOpen] = React.useState<string[]>(() => {
    const stored = readStored(storageKey) ?? defaults;
    return [...new Set([...pinned, ...stored])];
  });
  const onChange = React.useCallback(
    (value: string[]) => {
      setOpen(value);
      writeStored(storageKey, value);
    },
    [storageKey],
  );
  return [open, onChange];
}
