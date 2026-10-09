import React from 'react';
import { Tooltip } from '@mantine/core';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import type {
  ChromeButtonGroupRenderProps,
  ChromeButtonRenderProps,
  ChromeIconName,
} from 'depictio-react-core';

import { cn } from './cn';
import { Glyph } from './icons';

/**
 * Where a control sits decides its shape:
 * - `rail`   a row of the sidebar (icon and name; the name folds away when
 *            the sidebar collapses to its rail);
 * - `top`    a square key on the right of the top bar;
 * - `dock`   a key in the floating action dock;
 * - `tabbar` a cell of the phone's bottom bar (icon over a short name);
 * - `sheet`  a labelled row of a bottom sheet;
 * - `bar`    anything else: the phone top bar, panel headers, filter strips.
 */
export type Place = 'rail' | 'top' | 'dock' | 'tabbar' | 'sheet' | 'bar';

export const placeOf = (group: string | null): Place => {
  if (!group) return 'bar';
  if (group === 'rail' || group === 'top' || group === 'tabbar' || group === 'sheet') return group;
  if (group.startsWith('dock')) return 'dock';
  return 'bar';
};

type Look = 'primary' | 'icon' | 'on' | 'chip' | 'chipOn' | 'danger';

/** Short names for the phone bar, where a sentence cannot fit. */
const SHORT: Partial<Record<ChromeIconName, string>> = {
  menu: 'Tabs',
  search: 'Search',
  filters: 'Filters',
  comments: 'Comments',
  analysis: 'Analysis',
  settings: 'Settings',
  add: 'Add',
  view: 'Exit edit',
  edit: 'Edit',
  save: 'Save',
  more: 'More',
};

/** Glass's dock keeps every key to its glyph; the mode keys are named in full
 *  by their tooltip. */
const DOCK_TIP: Partial<Record<ChromeIconName, string>> = {
  edit: 'Edit dashboard',
  save: 'Save dashboard',
  view: 'Exit edit mode',
};

const ICON_PX: Record<Place, number> = { rail: 19, top: 18, dock: 19, tabbar: 21, sheet: 18, bar: 16 };

/** Class names only: every surface, size and colour lives in the CSS
 *  (glass.css, layout.css). */
const LOOK_CLASS: Record<Look, string> = {
  primary: 'hy-key--primary',
  icon: 'hy-key--icon',
  on: 'hy-key--on',
  chip: 'hy-key--chip',
  chipOn: 'hy-key--chip hy-key--on',
  danger: 'hy-key--danger',
};
const key = ({ place, look, labelled }: { place: Place; look: Look; labelled: boolean }) =>
  `hy-key hy-key--${place} ${LOOK_CLASS[look]} ${labelled ? 'hy-key--labelled' : 'hy-key--square'}`;

/** Glass's spring: quick, a little give, no wobble. */
const SPRING = { type: 'spring', stiffness: 520, damping: 30, mass: 0.6 } as const;
const POP = { type: 'spring', stiffness: 640, damping: 24 } as const;

/**
 * Glass's chrome button, placed by its group (rail, top bar, dock, phone
 * bar, sheet): a motion pill that lifts under the pointer, squishes when
 * pressed and grows a lit well when a mode turns on.
 */
export const GlassButton = React.forwardRef<HTMLButtonElement, ChromeButtonRenderProps>(
  function GlassButton(
    {
      chromeRole,
      roleStyle: _roleStyle,
      tones,
      tone: _tone,
      label,
      icon,
      iconSlot,
      rightIcon,
      rightIconSlot,
      badge,
      active,
      iconOnly,
      collapse: _collapse,
      hasTooltip,
      group,
      href,
      target,
      rel,
      children,
      rightSection,
      className,
      style,
      disabled,
      type,
      ...rest
    },
    ref,
  ) {
    const reduce = useReducedMotion();
    const place = placeOf(group);
    const isPrimary = chromeRole === 'primary';
    const on = chromeRole === 'toggle' && active;
    // Glass's dock: the mode key (Edit, Save) is a plain glyph like the
    // others, not a tinted pill; Save, the one that commits, wears the lit
    // well of a key that is on.
    const dockMode = place === 'dock' && isPrimary;
    const showLabel =
      place === 'sheet' ||
      place === 'tabbar' ||
      place === 'rail' ||
      ((place === 'bar' || place === 'dock') && !iconOnly && !dockMode);
    // A dock key carries its name folded: it opens out while the key is
    // engaged (a mode on, or its panel open), so a click visibly answers.
    const peek = place === 'dock' && !showLabel && !isPrimary;
    const look: Look = dockMode
      ? iconSlot === 'save'
        ? 'on'
        : 'icon'
      : isPrimary
      ? 'primary'
      : chromeRole === 'danger' && showLabel
        ? 'danger'
        : showLabel && place === 'bar'
          ? on
            ? 'chipOn'
            : 'chip'
          : on
            ? 'on'
            : 'icon';

    // The bottom bar and the sheets keep their names on a phone: the shared
    // rule that folds a collapsible label below `sm` must not reach them.
    const ownRest = { ...rest } as Record<string, unknown>;
    if (place === 'tabbar' || place === 'sheet') delete ownRest['data-collapse'];

    const p = tones.primary;
    const vars = {
      '--gl-tone': `var(--mantine-color-${p}-filled)`,
      '--gl-tone-soft': `color-mix(in srgb, var(--mantine-color-${p}-filled) 16%, transparent)`,
      '--gl-tone-ink': `light-dark(var(--mantine-color-${p}-7), var(--mantine-color-${p}-3))`,
      ...style,
    } as React.CSSProperties;

    const text =
      place === 'tabbar' ? ((iconSlot && SHORT[iconSlot]) ?? label) : (children ?? label);
    const labelNode = showLabel ? (
      <span className={cn('hy-key-label', place !== 'tabbar' && 'dc-action-label')}>{text}</span>
    ) : peek ? (
      <span className="hy-key-label hy-key-peek">{label}</span>
    ) : null;

    const inlineCount = badge > 0 && showLabel && place !== 'tabbar' && place !== 'rail';
    const right =
      rightSection != null ? (
        <span className="hy-key-right">{rightSection}</span>
      ) : inlineCount ? (
        <span className="hy-count">{badge}</span>
      ) : rightIcon && showLabel && place === 'bar' ? (
        <Glyph slot={rightIconSlot} id={rightIcon} size={12} className="hy-key-caret" />
      ) : null;

    const bubble =
      badge > 0 && !inlineCount ? (
        <AnimatePresence initial={false}>
          <motion.span
            key={badge}
            className="hy-bubble"
            initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.3 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={POP}
          >
            {badge > 99 ? '99+' : badge}
          </motion.span>
        </AnimatePresence>
      ) : null;

    // The lit well of a mode that is on grows in under the glyph.
    const well =
      on || look === 'on' || look === 'chipOn' ? (
        <motion.span
          aria-hidden
          className="hy-well"
          initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={POP}
        />
      ) : null;

    const content = (
      <>
        {well}
        <Glyph slot={iconSlot} id={icon} size={ICON_PX[place]} className="hy-glyph" />
        {labelNode}
        {right}
        {bubble}
        {on && place !== 'sheet' && place !== 'bar' && place !== 'rail' && <span className="hy-dot" aria-hidden />}
      </>
    );

    const classes = cn(
      key({ place, look, labelled: showLabel }),
      place === 'bar' && !showLabel && rightIcon && 'hy-key--menu',
      className,
    );
    const data = {
      'data-hy-place': place,
      'data-hy-look': look,
    };

    const lift = place === 'dock' ? -3 : place === 'top' ? -1 : 0;
    const motionProps =
      !reduce && !disabled
        ? {
            whileHover: lift ? { y: lift } : place === 'rail' ? { x: 2 } : { scale: 1.03 },
            whileTap: { scale: 0.92, y: 0 },
            transition: SPRING,
          }
        : {};

    if (href) {
      const A = motion.a as React.ElementType;
      return (
        <A
          ref={ref as unknown as React.Ref<HTMLAnchorElement>}
          href={disabled ? undefined : href}
          target={target}
          rel={rel}
          className={classes}
          style={vars}
          aria-disabled={disabled || undefined}
          {...data}
          {...motionProps}
          {...ownRest}
        >
          {content}
        </A>
      );
    }
    const B = motion.button as React.ElementType;
    const button = (
      <B
        ref={ref}
        type={type ?? 'button'}
        disabled={disabled}
        className={classes}
        style={vars}
        {...data}
        {...motionProps}
        {...ownRest}
      >
        {content}
      </B>
    );
    if (!dockMode || hasTooltip) return button;
    return (
      <Tooltip label={(iconSlot && DOCK_TIP[iconSlot]) ?? label} withArrow openDelay={300}>
        {button}
      </Tooltip>
    );
  },
);

/**
 * A run of related actions. On the rail a column, in the dock a cluster (the
 * dock draws the rules between clusters), on the phone bar a transparent run,
 * in a sheet a list; anywhere else a tray of loose pills on a frosted well.
 */
export const GlassButtonGroup: React.FC<ChromeButtonGroupRenderProps> = ({
  group,
  className,
  children,
}) => {
  const place = placeOf(group);
  if (place === 'tabbar') {
    return (
      <div role="group" data-group={group} style={{ display: 'contents' }}>
        {children}
      </div>
    );
  }
  return (
    <div role="group" data-group={group} data-hy-place={place} className={cn(className, `hy-group hy-group--${place}`)}>
      {children}
    </div>
  );
};
