import React from 'react';
import { ActionIcon, Badge, Button, Indicator, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useMediaQuery } from '@mantine/hooks';

import { ChromeGroupContext } from './ChromeButtonGroup';
import { useChromeStyle, useChromeTones } from './chromeStyle';
import type { ChromeIconName, ChromeRole } from './chromeStyle';

export interface ChromeButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'color' | 'children'> {
  /** What the action is for; the active chrome style decides how it looks. */
  role?: ChromeRole;
  /** Accessible name, and the visible label unless `iconOnly`. */
  label: string;
  /** A semantic slot of the style's icon set, or a literal Iconify id. */
  icon: ChromeIconName | (string & {});
  /** Trailing icon (slot or Iconify id), e.g. a menu chevron. */
  rightIcon?: ChromeIconName | (string & {});
  /** Count badged on the control; hidden at 0. */
  badge?: number | null;
  /** `toggle` only: the mode is on. */
  active?: boolean;
  /** Draw the icon alone, the label going to the tooltip. */
  iconOnly?: boolean;
  /** Labelled above `sm`, icon-only below it. */
  collapse?: boolean;
  /** Tooltip text. Defaults to the label when the label is not visible;
   *  `null` turns it off. */
  tooltip?: React.ReactNode | null;
  /** Renders a link instead of a button. */
  href?: string;
  target?: string;
  rel?: string;
  /** Overrides the visible label (e.g. a label that swaps without reflowing). */
  children?: React.ReactNode;
  /** Overrides the right section (badge / right icon). */
  rightSection?: React.ReactNode;
  [dataAttr: `data-${string}`]: string | number | boolean | undefined;
}

function useIcon(name: string | undefined): string | undefined {
  const { icons } = useChromeStyle();
  if (!name) return undefined;
  return (icons as Record<string, string>)[name] ?? name;
}

/**
 * The one button of the dashboard chrome. Every header, sidebar and filter
 * action goes through it, so a role always looks the same wherever it sits and
 * a chrome style can restyle all of them at once.
 */
export const ChromeButton = React.forwardRef<HTMLButtonElement, ChromeButtonProps>(
  function ChromeButton(
    {
      role = 'secondary',
      label,
      icon,
      rightIcon,
      badge,
      active = false,
      iconOnly: iconOnlyProp = false,
      collapse = false,
      tooltip,
      href,
      target,
      rel,
      className,
      children,
      rightSection,
      ...rest
    },
    ref,
  ) {
    const style = useChromeStyle();
    const tones = useChromeTones();
    const group = React.useContext(ChromeGroupContext);
    const roleStyle = style.roles[role];
    // A style may keep labels on the primary action only, or on none: every
    // collapsible action then draws as its icon, named by the tooltip.
    const labels = style.actionLabels ?? 'all';
    const iconOnly =
      iconOnlyProp ||
      (collapse && (labels === 'none' || (labels === 'primary' && role !== 'primary')));
    const isActive = role === 'toggle' && active;
    const variant = isActive ? (roleStyle.activeVariant ?? 'filled') : roleStyle.variant;
    const color = tones[isActive ? (roleStyle.activeTone ?? roleStyle.tone) : roleStyle.tone];
    const iconId = useIcon(icon);
    const rightIconId = useIcon(rightIcon);
    const px = style.iconSize;
    // A collapsed label only needs the tooltip where it is collapsed.
    const narrow = useMediaQuery('(max-width: 48em)', false, { getInitialValueInEffect: false });

    const shared = {
      ref,
      className: ['dc-action', className].filter(Boolean).join(' '),
      'data-role': role,
      'data-active': isActive || undefined,
      'data-group': group ?? undefined,
      color,
      variant,
      radius: style.radius,
      ...(href ? { component: 'a' as const, href, target, rel } : {}),
      ...rest,
    };

    const hasBadge = typeof badge === 'number' && badge > 0;
    const tip =
      tooltip === null ? null : (tooltip ?? (iconOnly || (collapse && narrow) ? label : null));
    const Custom = style.components?.Button;
    let control: React.ReactElement;
    if (Custom) {
      const slots = style.icons as Record<string, string>;
      control = (
        <Custom
          ref={ref}
          {...rest}
          className={shared.className}
          data-role={role}
          data-active={isActive || undefined}
          data-collapse={collapse || undefined}
          data-group={group ?? undefined}
          aria-label={rest['aria-label'] ?? (iconOnly || collapse || children ? label : undefined)}
          hasTooltip={Boolean(tip)}
          group={group}
          chromeRole={role}
          roleStyle={roleStyle}
          tones={tones}
          tone={isActive ? (roleStyle.activeTone ?? roleStyle.tone) : roleStyle.tone}
          label={label}
          icon={iconId!}
          iconSlot={icon in slots ? (icon as ChromeIconName) : null}
          rightIcon={rightIconId}
          rightIconSlot={rightIcon && rightIcon in slots ? (rightIcon as ChromeIconName) : null}
          badge={hasBadge ? (badge as number) : 0}
          active={isActive}
          iconOnly={iconOnly}
          collapse={collapse}
          href={href}
          target={target}
          rel={rel}
          rightSection={rightSection}
        >
          {children ?? label}
        </Custom>
      );
    } else if (iconOnly) {
      control = (
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        <ActionIcon
          {...(shared as any)}
          size={`input-${style.controlSize}`}
          aria-label={rest['aria-label'] ?? label}
        >
          <Indicator
            label={badge}
            size={14}
            disabled={!hasBadge}
            offset={2}
            color={tones.primary}
            inline
          >
            <Icon icon={iconId!} width={px + 2} height={px + 2} />
          </Indicator>
        </ActionIcon>
      );
    } else {
      control = (
        <Button
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          {...(shared as any)}
          size={style.controlSize}
          data-collapse={collapse || undefined}
          aria-label={rest['aria-label'] ?? (collapse || children ? label : undefined)}
          leftSection={<Icon icon={iconId!} width={px} height={px} />}
          rightSection={
            rightSection ??
            (hasBadge ? (
              <Badge
                size="xs"
                circle
                variant={variant === 'filled' ? 'white' : 'filled'}
                color={color}
                className="dc-action-badge"
              >
                {badge}
              </Badge>
            ) : rightIconId ? (
              <Icon icon={rightIconId} width={px - 2} height={px - 2} />
            ) : undefined)
          }
        >
          <span className="dc-action-label">{children ?? label}</span>
        </Button>
      );
    }

    if (!tip) return control;
    return (
      <Tooltip label={tip} withArrow openDelay={300} events={{ hover: true, focus: true, touch: false }}>
        {control}
      </Tooltip>
    );
  },
);

export default ChromeButton;
