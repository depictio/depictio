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
