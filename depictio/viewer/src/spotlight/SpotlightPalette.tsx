import React, { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Box,
  Group,
  Kbd,
  Loader,
  Modal,
  Text,
  TextInput,
  ThemeIcon,
  UnstyledButton,
  useMantineColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  buildSpotlightIndex,
  componentTypeVisual,
  groupSpotlightHits,
  searchSpotlight,
  useBranding,
  Z_LAYERS,
} from 'depictio-react-core';
import type {
  DashboardSummary,
  SpotlightGroup,
  SpotlightHit,
  SpotlightTab,
  TextRange,
} from 'depictio-react-core';

import { resolveTabColor, resolveTabIcon, tabImageSrc } from '../chrome/Sidebar';
import { dashboardLinkClickHandler } from '../dashboards/lib/dashboardLinks';
import { searchShortcutLabel } from './shortcut';
import './spotlight.css';

/**
 * The search palette: one field, results as you type, grouped by tab.
 *
 * Shaped after Spotlight and the command palettes readers already know: it
 * opens on a keystroke with the field focused, the arrow keys walk the
 * results, Enter opens one and Esc closes it all. The field is a combobox over
 * a listbox, so a screen reader hears the highlighted row as it moves.
 *
 * Results are drawn, not decided, here: ranking and grouping are
 * `searchSpotlight` / `groupSpotlightHits` in react-core. Each row is a real
 * link (the tab's address, with the component to land on), so a middle-click
 * or Cmd+click opens it in a new browser tab like a sidebar pill does; a plain
 * click and Enter go through `onPick`.
 */

/** `text` with `ranges` emphasised. */
const Emphasis: React.FC<{ text: string; ranges: TextRange[] }> = ({ text, ranges }) => {
  if (ranges.length === 0) return <>{text}</>;
  const parts: React.ReactNode[] = [];
  let at = 0;
  ranges.forEach(([a, b], i) => {
    if (a > at) parts.push(text.slice(at, a));
    parts.push(
      <mark key={i} className="depictio-spotlight-mark">
        {text.slice(a, b)}
      </mark>,
    );
    at = b;
  });
  if (at < text.length) parts.push(text.slice(at));
  return <>{parts}</>;
};

/** A tab's icon as the sidebar draws it: its image, or its Iconify glyph in
 *  its colour. */
const TabGlyph: React.FC<{ tab: DashboardSummary | undefined; size: number }> = ({
  tab,
  size,
}) => {
  const brand = useBranding();
  const { colorScheme } = useMantineColorScheme();
  if (!tab) {
    return (
      <ThemeIcon variant="light" color="gray" size={size} radius="md">
        <Icon icon="mdi:tab" width={size * 0.56} />
      </ThemeIcon>
    );
  }
  const isParent = !tab.parent_dashboard_id;
  const image = tabImageSrc(tab, isParent, colorScheme === 'dark');
  return (
    <ThemeIcon variant="light" color={resolveTabColor(tab, isParent, brand)} size={size} radius="md">
      {image ? (
        <img
          src={image}
          alt=""
          style={{ width: size * 0.56, height: size * 0.56, objectFit: 'contain' }}
        />
      ) : (
        <Icon icon={resolveTabIcon(tab, isParent)} width={size * 0.56} />
      )}
    </ThemeIcon>
  );
};

/** A component's type as its row's icon. A MultiQC report wears MultiQC's
 *  logo, as its tile and its tab do, on a neutral tile: the type palette's
 *  orange chart glyph is meant for a dot or a badge, and here it read as some
 *  other figure. */
const ComponentGlyph: React.FC<{ type: string }> = ({ type }) => {
  const { colorScheme } = useMantineColorScheme();
  if (type === 'multiqc') {
    return (
      <ThemeIcon variant="light" color="gray" size={32} radius="md">
        <img
          src={
            colorScheme === 'dark'
              ? '/dashboard/logos/multiqc_icon_white.svg'
              : '/dashboard/logos/multiqc_icon_dark.svg'
          }
          alt=""
          style={{ width: 18, height: 18, objectFit: 'contain' }}
        />
      </ThemeIcon>
    );
  }
  const visual = componentTypeVisual(type);
  return (
    <ThemeIcon variant="light" color={visual.color} size={32} radius="md">
      <Icon icon={visual.icon} width={18} />
    </ThemeIcon>
  );
};

/** What the dimmed line names a matched column by. */
const SNIPPET_PREFIX: Partial<Record<string, string>> = {
  column: 'Column: ',
};

const ResultRow: React.FC<{
  hit: SpotlightHit;
  id: string;
  active: boolean;
  summary: DashboardSummary | undefined;
  href: string;
  onPick: () => void;
  onHover: () => void;
}> = ({ hit, id, active, summary, href, onPick, onHover }) => {
  const { entry, snippet } = hit;
  // Tab, then section, then the words that matched: where it is before what
  // it says.
  const where = [entry.kind === 'component' ? entry.tabLabel : null, entry.section]
    .filter(Boolean)
    .join(' · ');
  return (
    <UnstyledButton
      component="a"
      href={href}
      id={id}
      role="option"
      aria-selected={active}
      tabIndex={-1}
      data-active={active || undefined}
      className="depictio-spotlight-row"
      onClick={dashboardLinkClickHandler(onPick)}
      onMouseMove={active ? undefined : onHover}
    >
      <Group gap="sm" wrap="nowrap">
        {entry.kind === 'component' ? (
          <ComponentGlyph type={entry.componentType ?? ''} />
        ) : (
          <TabGlyph tab={summary} size={32} />
        )}
        <Box style={{ flex: 1, minWidth: 0 }}>
          <Text size="sm" fw={500} truncate>
            <Emphasis text={entry.title} ranges={hit.titleRanges} />
          </Text>
          {(where || snippet) && (
            <Text size="xs" c="dimmed" truncate>
              {where}
              {where && snippet ? ' · ' : null}
              {snippet && (
                <>
                  {SNIPPET_PREFIX[snippet.field] ?? null}
                  <Emphasis text={snippet.text} ranges={snippet.ranges} />
                </>
              )}
            </Text>
          )}
        </Box>
        <Badge variant="light" color="gray" size="sm" radius="sm" visibleFrom="xs" style={{ flexShrink: 0 }}>
          {entry.kindLabel}
        </Badge>
      </Group>
    </UnstyledButton>
  );
};

const GroupHeader: React.FC<{ group: SpotlightGroup; summary: DashboardSummary | undefined }> = ({
  group,
  summary,
}) => (
  <Group gap={8} px={10} pt={10} pb={4} wrap="nowrap" role="presentation">
    <TabGlyph tab={summary} size={20} />
    <Text size="xs" fw={700} c="dimmed" tt="uppercase" truncate style={{ minWidth: 0 }}>
      {group.tabLabel}
    </Text>
    {group.isCurrent && (
      <Badge size="xs" variant="light" style={{ flexShrink: 0 }}>
        This tab
      </Badge>
    )}
  </Group>
);

export interface SpotlightPaletteProps {
  opened: boolean;
  onClose: () => void;
  /** The family with its components, from `useSpotlightTabs`. */
  tabs: SpotlightTab[];
  /** The family's summaries, for the tabs' icons and colours. */
  summaries: DashboardSummary[];
  currentId: string | null;
  /** Tabs still loading, and tabs that could not be, for the footer. */
  pending: number;
  failed: number;
  /** Where a result's link points. */
  hrefFor: (hit: SpotlightHit) => string;
  onPick: (hit: SpotlightHit) => void;
}

const SpotlightPalette: React.FC<SpotlightPaletteProps> = ({
  opened,
  onClose,
  tabs,
  summaries,
  currentId,
  pending,
  failed,
  hrefFor,
  onPick,
}) => {
  const [query, setQuery] = useState('');
  // Typing stays instant on a large family; the list follows a beat behind.
  const deferredQuery = useDeferredValue(query);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const shortcut = searchShortcutLabel();

  const index = useMemo(() => buildSpotlightIndex(tabs), [tabs]);
  const groups = useMemo(
    () =>
      groupSpotlightHits(
        searchSpotlight(index, deferredQuery),
        tabs.map((t) => ({ id: t.id, label: t.label })),
        currentId,
      ),
    [index, deferredQuery, tabs, currentId],
  );
  const flat = useMemo(() => groups.flatMap((g) => g.hits), [groups]);
  const summaryById = useMemo(
    () => new Map(summaries.map((s) => [s.dashboard_id, s])),
    [summaries],
  );

  // The highlighted row: the one the reader moved to while it is still listed,
  // else the first.
  const activePos = Math.max(
    0,
    flat.findIndex((h) => h.entry.key === activeKey),
  );
  const active = flat[activePos] ?? null;
  const optionId = (key: string) => `depictio-spotlight-${key.replace(/[^\w-]/g, '_')}`;

  // A new query starts from its best match.
  useEffect(() => {
    setActiveKey(null);
  }, [deferredQuery]);

  // Keep the highlighted row in view as the arrow keys walk the list.
  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>('[data-active]')
      ?.scrollIntoView({ block: 'nearest' });
  }, [active?.entry.key]);

  const move = (step: number) => {
    if (flat.length === 0) return;
    const next = (activePos + step + flat.length) % flat.length;
    setActiveKey(flat[next].entry.key);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing) return;
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        move(1);
        break;
      case 'ArrowUp':
        e.preventDefault();
        move(-1);
        break;
      case 'Enter':
        if (active) {
          e.preventDefault();
          onPick(active);
        }
        break;
      case 'k':
      case 'K':
        // The shortcut that opened the palette closes it again.
        if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey) {
          e.preventDefault();
          onClose();
        }
        break;
    }
  };

  const trimmed = deferredQuery.trim();

  return (
    <Modal.Root
      opened={opened}
      onClose={onClose}
      size="lg"
      yOffset="10vh"
      radius="lg"
      // Above drawers: the shortcut works with the filter drawer open too.
      zIndex={Z_LAYERS.nestedOverlay}
      transitionProps={{ transition: 'pop', duration: 120 }}
    >
      <Modal.Overlay backgroundOpacity={0.35} blur={2} />
      <Modal.Content aria-label="Search this dashboard" data-testid="dashboard-spotlight">
        <Modal.Body p={0}>
          <TextInput
            data-autofocus
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
            onKeyDown={onKeyDown}
            // Reopening keeps the last query, selected, so typing replaces it.
            onFocus={(e) => e.currentTarget.select()}
            placeholder="Search components, tabs, columns…"
            aria-label="Search this dashboard"
            role="combobox"
            aria-expanded
            aria-controls="depictio-spotlight-results"
            aria-activedescendant={active ? optionId(active.entry.key) : undefined}
            aria-autocomplete="list"
            autoComplete="off"
            spellCheck={false}
            size="lg"
            variant="unstyled"
            leftSection={<Icon icon="mdi:magnify" width={22} />}
            leftSectionWidth={52}
            rightSection={
              pending > 0 ? <Loader size="xs" aria-label="Loading other tabs" /> : undefined
            }
            classNames={{ input: 'depictio-spotlight-input' }}
          />
          <Box
            ref={listRef}
            id="depictio-spotlight-results"
            role="listbox"
            aria-label="Results"
            className="depictio-spotlight-results"
          >
            {flat.length === 0 ? (
              <Text size="sm" c="dimmed" ta="center" py="xl" px="md">
                {trimmed
                  ? `No component matches '${trimmed}'`
                  : 'This dashboard has no tabs to search yet.'}
              </Text>
            ) : (
              groups.map((group) => (
                <div key={group.tabId} role="group" aria-label={group.tabLabel}>
                  <GroupHeader group={group} summary={summaryById.get(group.tabId)} />
                  {group.hits.map((hit) => (
                    <ResultRow
                      key={hit.entry.key}
                      hit={hit}
                      id={optionId(hit.entry.key)}
                      active={hit === active}
                      summary={summaryById.get(hit.entry.tabId)}
                      href={hrefFor(hit)}
                      onPick={() => onPick(hit)}
                      onHover={() => setActiveKey(hit.entry.key)}
                    />
                  ))}
                  {group.more > 0 && (
                    <Text size="xs" c="dimmed" px={10} py={4}>
                      {group.more} more in this tab — add a word to narrow it down
                    </Text>
                  )}
                </div>
              ))
            )}
          </Box>
          <Group
            justify="space-between"
            gap="sm"
            px="md"
            py={8}
            wrap="nowrap"
            className="depictio-spotlight-footer"
          >
            <Text size="xs" c="dimmed" truncate>
              {pending > 0
                ? `Searching ${pending} more tab${pending === 1 ? '' : 's'}…`
                : failed > 0
                  ? `${failed} tab${failed === 1 ? '' : 's'} could not be searched`
                  : trimmed
                    ? `${flat.length} result${flat.length === 1 ? '' : 's'}`
                    : 'Type to search every tab'}
            </Text>
            <Group gap={10} wrap="nowrap" visibleFrom="sm" style={{ flexShrink: 0 }}>
              <Text size="xs" c="dimmed">
                <Kbd size="xs">↑</Kbd> <Kbd size="xs">↓</Kbd> move
              </Text>
              <Text size="xs" c="dimmed">
                <Kbd size="xs">↵</Kbd> open
              </Text>
              <Text size="xs" c="dimmed">
                <Kbd size="xs">esc</Kbd> close
              </Text>
              <Text size="xs" c="dimmed">
                <Kbd size="xs">{shortcut}</Kbd>
              </Text>
            </Group>
          </Group>
        </Modal.Body>
      </Modal.Content>
    </Modal.Root>
  );
};

export default SpotlightPalette;
