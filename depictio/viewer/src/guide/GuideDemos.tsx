/**
 * The Guide's live demos: small working copies of the real controls, built
 * from the same Mantine pieces and, where the dashboard has them, its real
 * names, icons and colours. They act on themselves only — nothing here
 * filters, folds or saves anything on the dashboard.
 */
import React, { useState } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Group,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  useComputedColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  UI_SCALE_STEPS,
  useBranding,
  useGroupingColor,
  useGroupingColorVar,
} from 'depictio-react-core';
import type { GuideModel } from 'depictio-react-core';

import { resolveTabColor, resolveTabIcon, tabImageSrc } from '../chrome/Sidebar';
import { dashboardHref, dashboardLinkClickHandler } from '../dashboards/lib/dashboardLinks';
import { CONTENT_WIDTHS, type ContentWidth } from '../hooks/useContentWidthPref';

/** The inset a demo sits in, labelled so it reads as something to try. */
export const DemoFrame: React.FC<{ label?: string; children: React.ReactNode }> = ({
  label = 'Try it',
  children,
}) => (
  <Box className="depictio-guide-demo" p="md">
    <Text size="xs" c="dimmed" tt="uppercase" fw={700} mb="xs" style={{ letterSpacing: '0.06em' }}>
      {label}
    </Text>
    {children}
  </Box>
);

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

/**
 * The dashboard's tabs as the sidebar draws them — same icon, colour and
 * active fill — with each tab's subtitle under its name. Each pill is the tab's
 * real link: a click opens it, a middle-click opens it in a new browser tab.
 * The current tab's pill closes the Guide instead of reloading the page.
 */
export const TabPillsDemo: React.FC<{
  model: GuideModel;
  mode: 'view' | 'edit';
  onCurrent: () => void;
}> = ({ model, mode, onCurrent }) => {
  const brand = useBranding();
  const isDark = useComputedColorScheme('light') === 'dark';
  const currentId = model.tabs.current?.id ?? null;
  return (
    <Tabs
      value={currentId}
      variant="pills"
      orientation="vertical"
      className="depictio-chrome-tabs depictio-guide-tabs"
      styles={{ root: { display: 'block' }, list: { border: 'none', width: '100%' } }}
    >
      <Tabs.List aria-label="This dashboard's tabs">
        {model.tabs.groups.map((g) => (
          <React.Fragment key={g.group ?? '__ungrouped'}>
            {g.group && (
              <Text
                className="depictio-guide-tabs-heading"
                c="dimmed"
                size="xs"
                tt="uppercase"
                fw={700}
                pl="xs"
              >
                {g.group}
              </Text>
            )}
            {g.tabs.map((t) => {
              const color = resolveTabColor(t.tab, t.isMain, brand);
              const image = tabImageSrc(t.tab, t.isMain, isDark, t.isCurrent);
              return (
                <Tabs.Tab
                  key={t.id}
                  value={t.id}
                  color={color}
                  pl="xs"
                  leftSection={
                    image ? (
                      <img
                        src={image}
                        alt=""
                        width={18}
                        height={18}
                        style={{ objectFit: 'contain', display: 'block' }}
                      />
                    ) : (
                      <Icon
                        icon={resolveTabIcon(t.tab, t.isMain)}
                        width={18}
                        height={18}
                        style={{
                          flexShrink: 0,
                          color: t.isCurrent
                            ? 'var(--mantine-color-white)'
                            : `var(--mantine-color-${color}-6)`,
                        }}
                      />
                    )
                  }
                  renderRoot={(props) => (
                    <a
                      {...props}
                      href={dashboardHref(t.id, mode)}
                      onClick={t.isCurrent ? dashboardLinkClickHandler(onCurrent) : undefined}
                    />
                  )}
                  aria-current={t.isCurrent ? 'page' : undefined}
                >
                  <span className="depictio-chrome-tab-label">{t.label}</span>
                  {t.subtitle && <span className="depictio-guide-tab-subtitle">{t.subtitle}</span>}
                </Tabs.Tab>
              );
            })}
          </React.Fragment>
        ))}
      </Tabs.List>
    </Tabs>
  );
};

// ---------------------------------------------------------------------------
// Analysis
// ---------------------------------------------------------------------------

/**
 * The header's Analysis button and what turning it on does to the tiles: the
 * ones a selection can be made on get the dashed outline and the group marker,
 * in the same colour as the real ones.
 */
export const AnalysisDemo: React.FC = () => {
  const [on, setOn] = useState(false);
  const color = useGroupingColor();
  const colorVar = useGroupingColorVar();
  const tiles: { label: string; selectable: boolean; kind: 'dots' | 'bars' | 'value' }[] = [
    { label: 'Scatter', selectable: true, kind: 'dots' },
    { label: 'Bar chart', selectable: false, kind: 'bars' },
    { label: 'Map', selectable: true, kind: 'dots' },
  ];
  return (
    <Stack gap="sm">
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm" c="dimmed">
          In the header
        </Text>
        <Button
          size="xs"
          color={color}
          variant={on ? 'filled' : 'light'}
          leftSection={<Icon icon="mdi:select-group" width={14} height={14} />}
          onClick={() => setOn((v) => !v)}
          aria-pressed={on}
        >
          Analysis
        </Button>
      </Group>
      <SimpleGrid
        cols={3}
        spacing="xs"
        style={{ '--depictio-grouping-color': colorVar } as React.CSSProperties}
      >
        {tiles.map((t) => (
          <Box
            key={t.label}
            className={'depictio-guide-tile' + (on && t.selectable ? ' is-selectable' : '')}
            h={76}
          >
            {t.kind === 'dots' ? (
              <Box className="depictio-guide-dots" style={{ position: 'absolute', inset: 0 }}>
                {[
                  [18, 60],
                  [30, 40],
                  [44, 55],
                  [58, 30],
                  [70, 48],
                  [80, 22],
                ].map(([x, y], i) => (
                  <span key={i} style={{ left: `${x}%`, top: `${y}%` }} />
                ))}
              </Box>
            ) : (
              <Box className="depictio-guide-bars" pt={22} pb={6}>
                {[40, 70, 55].map((h, i) => (
                  <span key={i} style={{ height: `${h}%` }} />
                ))}
              </Box>
            )}
            <Text size="10px" c="dimmed" style={{ position: 'absolute', left: 8, top: 6 }}>
              {t.label}
            </Text>
            {on && t.selectable && (
              <Box style={{ position: 'absolute', right: 6, top: 4, color: colorVar }}>
                <Icon icon="mdi:select-group" width={16} height={16} />
              </Box>
            )}
          </Box>
        ))}
      </SimpleGrid>
      <Text size="xs" c="dimmed" mih={18} aria-live="polite">
        {on
          ? 'Outlined tiles take a selection: lasso some points, then save them as a group.'
          : 'Turn it on to see which tiles take a selection.'}
      </Text>
    </Stack>
  );
};

// ---------------------------------------------------------------------------
// Your view
// ---------------------------------------------------------------------------

/** What the two "Your view" settings do, on a page in miniature. */
export const YourViewDemo: React.FC = () => {
  const [width, setWidth] = useState<ContentWidth>('full');
  const [step, setStep] = useState(UI_SCALE_STEPS.indexOf(1));
  const scale = UI_SCALE_STEPS[step];
  const share: Record<ContentWidth, number> = { full: 100, wide: 86, comfortable: 70, compact: 60 };
  return (
    <Stack gap="sm">
      <Group gap="sm" justify="space-between" wrap="wrap">
        <SegmentedControl
          size="xs"
          value={width}
          onChange={(v) => setWidth(v as ContentWidth)}
          data={CONTENT_WIDTHS.map((w) => ({ value: w.value, label: w.label }))}
        />
        <ActionIcon.Group>
          <ActionIcon
            variant="default"
            size="input-xs"
            aria-label="Decrease font size"
            disabled={step === 0}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
          >
            <Icon icon="mdi:format-font-size-decrease" width={14} />
          </ActionIcon>
          <Button
            variant="default"
            size="compact-xs"
            h="var(--input-height-xs)"
            style={{ pointerEvents: 'none' }}
            tabIndex={-1}
          >
            {Math.round(scale * 100)}%
          </Button>
          <ActionIcon
            variant="default"
            size="input-xs"
            aria-label="Increase font size"
            disabled={step === UI_SCALE_STEPS.length - 1}
            onClick={() => setStep((s) => Math.min(UI_SCALE_STEPS.length - 1, s + 1))}
          >
            <Icon icon="mdi:format-font-size-increase" width={14} />
          </ActionIcon>
        </ActionIcon.Group>
      </Group>
      <Box className="depictio-guide-tile" h={96} p={8}>
        <Box
          mx="auto"
          h="100%"
          style={{
            width: `${share[width]}%`,
            transition: 'width 200ms ease',
            borderInline: width === 'full' ? undefined : '1px dashed var(--mantine-color-default-border)',
            paddingInline: 8,
            overflow: 'hidden',
          }}
        >
          <Text fw={700} style={{ fontSize: 13 * scale, lineHeight: 1.3 }}>
            A tab
          </Text>
          <Text c="dimmed" style={{ fontSize: 11 * scale, lineHeight: 1.4 }}>
            Its figures, tables and cards, at the width and size you pick.
          </Text>
        </Box>
      </Box>
    </Stack>
  );
};
