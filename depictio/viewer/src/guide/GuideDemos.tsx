/**
 * The Guide's smaller demos: the tab list and "Your view", built from the
 * same pieces as the real controls. They act on themselves only. The demos
 * made of the dashboard's own components are in `demos/`.
 */
import React, { useState } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Group,
  SegmentedControl,
  Stack,
  Tabs,
  Text,
  useComputedColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { UI_SCALE_STEPS, useBranding } from 'depictio-react-core';
import type { GuideModel } from 'depictio-react-core';

type GuideTab = GuideModel['tabs']['groups'][number]['tabs'][number];

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

/** A tab's icon, as the sidebar draws it: its image, else its icon in its colour. */
const TabIcon: React.FC<{ tab: GuideTab; color: string; isDark: boolean }> = ({
  tab,
  color,
  isDark,
}) => {
  const image = tabImageSrc(tab.tab, tab.isMain, isDark, tab.isCurrent);
  return image ? (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 18,
        height: 18,
        flexShrink: 0,
      }}
    >
      <img src={image} alt="" style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
    </span>
  ) : (
    <Icon
      icon={resolveTabIcon(tab.tab, tab.isMain)}
      width={18}
      height={18}
      style={{
        flexShrink: 0,
        color: tab.isCurrent ? 'var(--mantine-color-white)' : `var(--mantine-color-${color}-6)`,
      }}
    />
  );
};

/**
 * The sidebar's tab list, drawn as the sidebar draws it: a column the
 * sidebar's width, its "Tabs" heading, its group headings, and the same pills
 * (Sidebar.tsx `renderTab`) with the tab you are on filled in. Beside it, what
 * the tab under the pointer holds: its subtitle, which the sidebar has no room
 * for.
 *
 * Each pill is the tab's real link: a click opens it, a middle-click opens it
 * in a new browser tab. The current tab's pill closes the Guide instead of
 * reloading the page.
 */
export const TabPillsDemo: React.FC<{
  model: GuideModel;
  mode: 'view' | 'edit';
  onCurrent: () => void;
}> = ({ model, mode, onCurrent }) => {
  const brand = useBranding();
  const isDark = useComputedColorScheme('light') === 'dark';
  const current = model.tabs.current;
  const [pointedId, setPointedId] = useState<string | null>(null);
  const all = model.tabs.groups.flatMap((g) => g.tabs);
  const pointed = all.find((t) => t.id === pointedId) ?? all.find((t) => t.isCurrent) ?? all[0];
  const pointedColor = pointed ? resolveTabColor(pointed.tab, pointed.isMain, brand) : 'gray';
  return (
    <Group gap="md" align="flex-start" wrap="wrap">
      <Box className="depictio-guide-sidebar" p="md" data-testid="guide-tabs-sidebar">
        <Stack gap={4}>
          <Text c="dimmed" size="xs" tt="uppercase" fw={700} mb={4}>
            Tabs
          </Text>
          <Tabs
            className="depictio-chrome-tabs"
            orientation="vertical"
            variant="pills"
            placement="left"
            value={current?.id ?? null}
            styles={{
              list: { gap: 4, border: 'none', width: '100%' },
              tab: { justifyContent: 'flex-start', width: '100%' },
              tabLabel: { flex: 1, minWidth: 0 },
            }}
          >
            <Tabs.List aria-label="This dashboard's tabs">
              {model.tabs.groups.map((g) => (
                <React.Fragment key={g.group ?? '__ungrouped'}>
                  {g.group && (
                    <Text c="dimmed" size="xs" tt="uppercase" fw={700} pl="xs" mt={6} truncate="end">
                      {g.group}
                    </Text>
                  )}
                  {g.tabs.map((t) => {
                    const color = resolveTabColor(t.tab, t.isMain, brand);
                    return (
                      <Tabs.Tab
                        key={t.id}
                        value={t.id}
                        color={color}
                        pl="xs"
                        leftSection={<TabIcon tab={t} color={color} isDark={isDark} />}
                        onMouseEnter={() => setPointedId(t.id)}
                        onFocus={() => setPointedId(t.id)}
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
                      </Tabs.Tab>
                    );
                  })}
                </React.Fragment>
              ))}
            </Tabs.List>
          </Tabs>
        </Stack>
      </Box>
      {pointed && (
        <Stack gap={6} style={{ flex: '1 1 220px', minWidth: 0 }} data-testid="guide-tabs-pointed">
          <Text size="xs" c="dimmed">
            {pointedId ? 'The tab under the pointer' : 'Point at a tab to see what it holds'}
          </Text>
          <Group gap={8} wrap="nowrap">
            <Icon
              icon={resolveTabIcon(pointed.tab, pointed.isMain)}
              width={18}
              height={18}
              style={{ flexShrink: 0, color: `var(--mantine-color-${pointedColor}-6)` }}
            />
            <Text size="sm" fw={600}>
              {pointed.label}
              {pointed.isCurrent ? ' · you are here' : ''}
            </Text>
          </Group>
          {pointed.subtitle && (
            <Text size="sm" c="dimmed" lh={1.45}>
              {pointed.subtitle}
            </Text>
          )}
        </Stack>
      )}
    </Group>
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
          data-guide-show
        />
        <ActionIcon.Group data-guide-show>
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
