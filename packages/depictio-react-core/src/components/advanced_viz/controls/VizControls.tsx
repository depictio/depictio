import React, { createContext, useContext } from 'react';
import {
  Box,
  Divider,
  Group,
  MultiSelect,
  NumberInput,
  Paper,
  SegmentedControl,
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  type MultiSelectProps,
  type NumberInputProps,
  type SegmentedControlProps,
  type SelectProps,
  type SliderProps,
  type SwitchProps,
} from '@mantine/core';

/**
 * One layout for every advanced-viz control, wherever it is drawn: the strip
 * under the title, the side rail, the Settings popover and the inspector.
 *
 * The rules, so a tile reads as one grid rather than a pile of widgets:
 *
 *  - every control is `size="xs"` and sits in a cell at least one xs input
 *    tall, its content centred in that band, so a Switch, a slider and a
 *    number box line up on one row;
 *  - only dropdowns (`VizSelect`, `VizMultiSelect`) carry a title above the
 *    input. Everything else is labelled on its own row: a Switch by its own
 *    label, the rest by a compact label to the left (`VizInlineField`), which
 *    is also the control's aria-label;
 *  - width belongs to the container, not the renderer, so the wrappers take
 *    no `w`: cells fill the grid column in the strip and the full width in a
 *    column.
 *
 * Renderers hand the frame a *fragment* of these, never a pre-arranged Stack,
 * so the container decides the arrangement (`VizControlsGrid`).
 */

/**
 * Mantine's xs input height (its `--input-height-xs`, which Mantine only
 * defines on input elements), the band every control cell is centred in.
 */
export const VIZ_CONTROL_HEIGHT = 'calc(1.875rem * var(--mantine-scale))';


function ariaFrom(label: React.ReactNode, explicit?: string): string | undefined {
  if (explicit) return explicit;
  return typeof label === 'string' || typeof label === 'number' ? String(label) : undefined;
}

/** A control box one input tall with its content vertically centred. */
export const VizControlCell: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Box style={{ display: 'flex', alignItems: 'center', minHeight: VIZ_CONTROL_HEIGHT, minWidth: 0 }}>
    {children}
  </Box>
);

/**
 * Which container the controls are drawn in, published by `VizControlsGrid`.
 * Only the grid itself reads it today; the fields lay out the same way in
 * both, which is what keeps the strip and the popover looking alike.
 */
const VizControlsLayoutContext = createContext<'strip' | 'column'>('column');

export function useVizControlsLayout(): 'strip' | 'column' {
  return useContext(VizControlsLayoutContext);
}

/** Width of a compact inline control (number box, text or colour input). */
export const VIZ_COMPACT_CONTROL_PX = 110;
/** Width of an inline slider: long enough to drag with some precision. */
export const VIZ_SLIDER_CONTROL_PX = 140;

/**
 * One control row: the label takes the space left on the left, wrapping onto
 * a second line rather than truncating (the full text is also its tooltip),
 * and the control sits at a fixed width on the right, so every control in a
 * column shares one right edge. The row is at least one input tall and its
 * content vertically centred.
 *
 * `controlWidth` is a pixel width, `'auto'` for a control that sizes to its
 * own content (a labelled SegmentedControl), or `'fill'` for one that takes
 * the whole row (an unlabelled SegmentedControl).
 */
export const VizInlineField: React.FC<{
  label?: React.ReactNode;
  controlWidth?: number | 'auto' | 'fill';
  children: React.ReactNode;
}> = ({ label, controlWidth = VIZ_COMPACT_CONTROL_PX, children }) => (
  <Box
    style={{
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'center',
      gap: 'var(--mantine-spacing-xs)',
      minHeight: VIZ_CONTROL_HEIGHT,
      minWidth: 0,
    }}
  >
    {label !== undefined && label !== null && label !== '' ? (
      <Text
        size="xs"
        fw={500}
        lineClamp={2}
        title={typeof label === 'string' ? label : undefined}
        // Wraps between words only: a label squeezed by a wide control
        // must not break "Highlight" into "Highligh / t". A zero basis lets it
        // take whatever the control leaves; when even its longest word does
        // not fit (a segmented control in the 220 px rail), the row wraps and
        // the control drops onto its own line instead of overflowing.
        style={{
          flex: '1 1 0',
          minWidth: 'min-content',
          wordBreak: 'normal',
          overflowWrap: 'normal',
        }}
      >
        {label}
      </Text>
    ) : null}
    <Box
      style={{
        flex:
          controlWidth === 'fill'
            ? '1 1 0'
            : controlWidth === 'auto'
              ? '0 1 auto'
              : `0 1 ${controlWidth}px`,
        width: typeof controlWidth === 'number' ? controlWidth : undefined,
        minWidth: 0,
        marginLeft: 'auto',
      }}
    >
      {children}
    </Box>
  </Box>
);

/** A row that spans the whole grid: section headings, hints, dividers. */
export const VizFullRow: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Box style={{ gridColumn: '1 / -1', minWidth: 0 }}>{children}</Box>
);

export type VizSwitchProps = Omit<SwitchProps, 'size'>;

/**
 * A Switch carrying its own label on the left and its track on the right, so
 * the tracks share the right edge the other controls line up on.
 */
const SWITCH_STYLES = {
  root: { width: '100%' },
  body: { justifyContent: 'space-between', alignItems: 'center' },
  labelWrapper: { minWidth: 0 },
} as const;

export const VizSwitch: React.FC<VizSwitchProps> = (props) => (
  <VizControlCell>
    <Switch labelPosition="left" styles={SWITCH_STYLES} {...props} size="xs" />
  </VizControlCell>
);

export type VizNumberInputProps = Omit<NumberInputProps, 'size' | 'w'>;

/** A NumberInput with its label inline on the left. */
export const VizNumberInput: React.FC<VizNumberInputProps> = ({
  label,
  'aria-label': ariaLabel,
  ...rest
}) => (
  <VizInlineField label={label}>
    <NumberInput {...rest} size="xs" aria-label={ariaFrom(label, ariaLabel)} />
  </VizInlineField>
);

export type VizSliderProps = Omit<SliderProps, 'size' | 'w' | 'label' | 'thumbLabel'> & {
  /** Inline label on the left (not Mantine's thumb label). */
  label?: React.ReactNode;
  /**
   * Mantine's thumb tooltip, forwarded as Slider `label`. (Mantine's own
   * `thumbLabel`, the thumb's aria-label, is set from `label` instead.)
   */
  thumbLabel?: React.ReactNode | ((value: number) => React.ReactNode);
};

/** A Slider with its label inline on the left. */
export const VizSlider: React.FC<VizSliderProps> = ({
  label,
  thumbLabel,
  'aria-label': ariaLabel,
  ...rest
}) => (
  <VizInlineField label={label} controlWidth={VIZ_SLIDER_CONTROL_PX}>
    <Slider
      {...rest}
      {...(thumbLabel !== undefined ? { label: thumbLabel } : {})}
      size="xs"
      aria-label={ariaFrom(label, ariaLabel)}
      thumbLabel={ariaFrom(label, ariaLabel)}
    />
  </VizInlineField>
);

export type VizSegmentedProps = Omit<SegmentedControlProps, 'size' | 'w'> & {
  /** Inline label on the left; also the control's aria-label. */
  label?: React.ReactNode;
  'aria-label'?: string;
};

/**
 * Mantine's xs SegmentedControl is a couple of pixels taller than an xs input
 * (its label padding plus the track padding). Pinned to the input height so a
 * segmented row and a number box beside it share top and bottom edges.
 */
export const VIZ_SEGMENTED_STYLES = {
  root: { height: VIZ_CONTROL_HEIGHT, padding: 3 },
  label: {
    height: '100%',
    paddingBlock: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
} as const;

/** A SegmentedControl, full width of its cell, labelled inline. */
export const VizSegmented: React.FC<VizSegmentedProps> = ({
  label,
  'aria-label': ariaLabel,
  fullWidth = true,
  ...rest
}) => (
  <VizInlineField label={label} controlWidth={label ? 'auto' : 'fill'}>
    <SegmentedControl
      {...rest}
      size="xs"
      fullWidth={fullWidth}
      aria-label={ariaFrom(label, ariaLabel)}
      styles={VIZ_SEGMENTED_STYLES}
    />
  </VizInlineField>
);

export type VizSelectProps = Omit<SelectProps, 'size' | 'w'>;

/**
 * A dropdown's title sits tight on its own input (a few px), while rows are
 * spaced wider (`ROW_GAP`), so a title never reads as belonging to the
 * control above it. A renderer's own `styles` still win.
 */
const DROPDOWN_STYLES = { label: { marginBottom: 4 } } as const;

/** A Select: the one kind of control that keeps its title above the input. */
export const VizSelect: React.FC<VizSelectProps> = ({ comboboxProps, ...rest }) => (
  <Select
    styles={DROPDOWN_STYLES}
    {...rest}
    size="xs"
    comboboxProps={{ withinPortal: true, ...comboboxProps }}
  />
);

export type VizMultiSelectProps = Omit<MultiSelectProps, 'size' | 'w'>;

/** A MultiSelect, titled above like `VizSelect`. */
export const VizMultiSelect: React.FC<VizMultiSelectProps> = ({ comboboxProps, ...rest }) => (
  <MultiSelect
    styles={DROPDOWN_STYLES}
    {...rest}
    size="xs"
    comboboxProps={{ withinPortal: true, ...comboboxProps }}
  />
);

/** Space between two control rows: wider than a title-to-input gap. */
const ROW_GAP = 'var(--mantine-spacing-sm)';
/** Space between two strip cells, and between two strip groups. */
const COLUMN_GAP = 'var(--mantine-spacing-md)';
/** Widest a strip cell grows to, so one control never stretches a whole row. */
const STRIP_MAX_CELL_PX = 320;
/** Width of a dropdown in the strip. */
const STRIP_DROPDOWN_PX = 200;

/**
 * The renderer's controls as a flat list: fragments (and the conditional
 * nulls inside them) unwrapped, so the strip can size each control as its own
 * cell whatever nesting the renderer used.
 */
function flattenControls(children: React.ReactNode): React.ReactElement[] {
  const out: React.ReactElement[] = [];
  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child)) return;
    if (child.type === React.Fragment) {
      out.push(...flattenControls((child.props as { children?: React.ReactNode }).children));
    } else {
      out.push(child);
    }
  });
  return out;
}

/**
 * The strip: a wrapping row of cells bottom-aligned, so a titled dropdown's
 * input sits on the line of the inline controls next to it. Each control is a
 * cell of its own content width (dropdowns a fixed 200 px); a group is one
 * segment of the row (its caption over its own cells, captions aligned on top,
 * inputs on the bottom), and groups sit side by side while they fit; a narrow
 * tile wraps down to one control per line.
 */
const StripFlow: React.FC<{ children: React.ReactNode; testId?: string }> = ({
  children,
  testId,
}) => (
  <Box
    data-testid={testId}
    style={{
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'flex-end',
      rowGap: ROW_GAP,
      columnGap: COLUMN_GAP,
      minWidth: 0,
    }}
  >
    {flattenControls(children).map((child, i) => {
      // Cells keep their content width, so a label stays next to its own
      // control instead of drifting across a stretched cell. Dropdowns have no
      // content width of their own and get a fixed one.
      const style: React.CSSProperties =
        child.type === VizControlGroup
          ? { flex: '0 1 auto', alignSelf: 'stretch', minWidth: 0, maxWidth: '100%' }
          : child.type === VizFullRow
            ? { flex: '1 1 100%', minWidth: 0 }
            : child.type === VizSelect || child.type === VizMultiSelect
              ? // A width, not a flex-basis: the browser sizes a group from
                // its cells' content widths, and a dropdown has none.
                { flex: '0 1 auto', width: STRIP_DROPDOWN_PX, minWidth: 0 }
              : { flex: '0 1 auto', minWidth: 0, maxWidth: STRIP_MAX_CELL_PX };
      return (
        <Box key={child.key ?? i} style={style}>
          {child}
        </Box>
      );
    })}
  </Box>
);

/**
 * The container every surface lays controls out in.
 *
 * `strip` is the wrapping row drawn under a tile's title (`StripFlow`).
 * `column` is a stack for the rail, the popover and the inspector: one row
 * per control, rows spaced wider than a title is from its input.
 *
 * `framed` draws the block as its own bordered, tinted panel with a small
 * caption, so inside a tile it never blends into the title, badges or
 * figure. Surfaces that are already a controls panel (the popover, the
 * inspector tab) leave it off. `headerAction` sits at the right of that
 * caption (the placement picker).
 */
export const VizControlsGrid: React.FC<{
  layout: 'strip' | 'column';
  framed?: boolean;
  title?: string;
  headerAction?: React.ReactNode;
  children: React.ReactNode;
  'data-testid'?: string;
}> = ({
  layout,
  framed = false,
  title = 'Controls',
  headerAction,
  children,
  'data-testid': testId,
}) => {
  const innerTestId = framed ? undefined : testId;
  const body = (
    <VizControlsLayoutContext.Provider value={layout}>
      {layout === 'strip' ? (
        <StripFlow testId={innerTestId}>{children}</StripFlow>
      ) : (
        <Stack gap={ROW_GAP} data-testid={innerTestId}>
          {children}
        </Stack>
      )}
    </VizControlsLayoutContext.Provider>
  );
  if (!framed) return body;
  return (
    <Paper
      withBorder
      radius="sm"
      p="xs"
      bg="var(--mantine-color-default-hover)"
      data-testid={testId}
    >
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" gap="xs">
          <Text size="xs" fw={600} c="dimmed">
            {title}
          </Text>
          {headerAction}
        </Group>
        <Divider />
        {body}
      </Stack>
    </Paper>
  );
};

/**
 * A named group of related controls ("Labels", "Markers", "Colour"...): a
 * captioned divider over its own rows. In a column it spans the full width;
 * in the strip it is one segment of the row. Used where a renderer has more
 * than a handful of controls, so a reader can tell the groups apart.
 */
export function VizControlGroup({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}): React.ReactElement {
  const layout = useVizControlsLayout();
  return (
    <Box style={{ gridColumn: '1 / -1', minWidth: 0, height: '100%' }}>
      <Stack gap="xs" justify="space-between" h="100%">
        <Divider label={title} labelPosition="left" />
        <VizControlsGrid layout={layout}>{children}</VizControlsGrid>
      </Stack>
    </Box>
  );
}
