import React, { useMemo, useState } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Collapse,
  Divider,
  Group,
  Loader,
  Modal,
  NavLink,
  Progress,
  ScrollArea,
  Stack,
  Text,
  Textarea,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { componentTypeVisual } from 'depictio-react-core';

import { sectionIconId } from '../componentVisuals';
import { AI_COLOR } from '../icons';

/** One generated tile of the draft, as the review addresses it. */
export interface DraftTile {
  /** Generation handle: what the review and regenerate routes address the
   *  tile by. The canvas addresses it by `componentId` instead. */
  tag: string;
  componentId: string;
  /** What to call the tile in the list. The host falls back to the tag on a
   *  component that carries no title of its own. */
  title: string;
  componentType: string;
  /** Section the tile sits in, filter-panel folds included: their rationale
   *  is worth showing even though a fold cannot be regenerated as a section
   *  (see `sectionRegenerable`). */
  section: string | null;
  /** Tab the tile lives on, for a draft that spans a tab family. Null on a
   *  single-tab draft, which is what the generator produces today: the tab
   *  level of the list then has one member and is not drawn. */
  tab?: string | null;
  /** The planner's brief for this tile, stamped on it at generation time.
   *  Null on a draft made before the planner was asked to explain itself. */
  intent: string | null;
  reviewed: boolean;
}

/**
 * One section of the draft as the panel draws it: the planner's reason for it,
 * plus the icon and the colour the dashboard itself renders that section with.
 * The two come from different places (the run record and the section spec on
 * the document), and the host merges them so the panel matches the canvas.
 */
export interface DraftReviewSection {
  name: string;
  kind: 'filter' | 'grid';
  /** One sentence on why the planner asked for the section. */
  rationale?: string | null;
  /** Iconify id from the section's own spec. */
  icon?: string | null;
  /** Mantine palette name from the section's own spec. */
  color?: string | null;
}

export interface DraftReviewPanelProps {
  /** The draft's generated tiles in reading order (filter panel first, then
   *  each grid section), as the host reads them off the dashboard. */
  tiles: DraftTile[];
  /** Index of the tile under review, owned by the host so the canvas and the
   *  panel cannot disagree about which one it is. */
  currentIndex: number;
  /** The draft's sections. Drives each group heading (its own icon and
   *  colour) and the quoted rationale under the cursor. A section missing
   *  from the list still gets a heading, drawn generically. */
  sections?: DraftReviewSection[];
  onSelect: (index: number) => void;
  onClose: () => void;
  onKeep: (tile: DraftTile) => void | Promise<void>;
  onRemove: (tile: DraftTile) => void | Promise<void>;
  /** Settle every tile at once: mark them all reviewed, or take every mark
   *  back. Absent on a host that cannot, which takes the control off the
   *  panel. */
  onKeepAll?: (keep: boolean) => void | Promise<void>;
  /** Drop every generated tile. The dashboard itself survives; deleting it is
   *  the banner's Discard. */
  onRemoveAll?: () => void | Promise<void>;
  onRegenerate: (tile: DraftTile, instruction: string) => void | Promise<void>;
  /** Absent on a host that cannot refill a whole section, which is what
   *  takes the secondary regenerate action off the panel. */
  onRegenerateSection?: (tile: DraftTile, instruction: string) => void | Promise<void>;
  /** A regeneration is in flight; every decision goes inert. */
  busy?: boolean;
  /** Last regeneration failure, reported under the actions. */
  error?: string | null;
}

/** The tiles of one section, in the order the plan put them. */
interface ReviewGroup {
  /** Fold key, unique across tabs: two tabs may hold sections of one name. */
  key: string;
  /** Null on a tile the generator left unsectioned. */
  name: string | null;
  label: string;
  /** The section's own icon, or the generic one for its kind. */
  icon: string;
  /** Mantine palette name, or null for a section with no colour of its own. */
  color: string | null;
  items: { tile: DraftTile; index: number }[];
}

/** The sections of one tab. Drawn as a fold of its own only when the draft
 *  actually spans tabs, so a single-tab draft keeps a flat list of sections. */
interface ReviewTabGroup {
  key: string;
  label: string;
  sections: ReviewGroup[];
}

/** Size and radius shared by every button in the panel, so the three
 *  decisions and the regenerate form read as one set of controls rather than
 *  as three surfaces that happen to sit together. */
const BUTTON_SIZE = 'sm';
const BUTTON_RADIUS = 'sm';

/**
 * One fold of the list: a tab or a section, with how far its own review has
 * got. Both levels share it so a nested fold reads as the same control one
 * step in, and the count is the reason to open a fold that is shut.
 */
const FoldHeader: React.FC<{
  icon: string;
  /** Mantine palette name from the section's spec; null draws it neutral. */
  color: string | null;
  label: string;
  tiles: DraftTile[];
  open: boolean;
  onToggle: () => void;
  testId: string;
}> = ({ icon, color, label, tiles, open, onToggle, testId }) => {
  const reviewed = tiles.filter((t) => t.reviewed).length;
  return (
    <UnstyledButton
      onClick={onToggle}
      w="100%"
      px="sm"
      py={4}
      data-testid={testId}
      data-open={open ? 'true' : 'false'}
      data-label={label}
    >
      <Group gap={6} wrap="nowrap">
        <Box c="dimmed" style={{ display: 'inline-flex' }}>
          <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={14} height={14} />
        </Box>
        <Box c={color ?? 'dimmed'} style={{ display: 'inline-flex' }}>
          <Icon icon={icon} width={13} height={13} />
        </Box>
        <Text
          size="xs"
          c={color ?? 'dimmed'}
          tt="uppercase"
          fw={700}
          truncate
          style={{ flex: 1, minWidth: 0 }}
        >
          {label}
        </Text>
        {/* Reviewed over total, in the same order the header above the list
            says it, so one glance answers "what is left in here". */}
        <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
          {reviewed}/{tiles.length}
        </Text>
      </Group>
    </UnstyledButton>
  );
};

/**
 * Right-hand panel that carries the whole review of an AI draft.
 *
 * It sits in the editor's aside, the same slot and the same width as the
 * inspector, so the canvas narrows rather than being covered: the point of
 * the review is judging the tiles, and nothing may sit on top of them. Every
 * earlier shape (icons in the tile chrome, a bar inside the banner, a dock
 * floating over the canvas) either crowded the tiles or scrolled away from
 * them.
 *
 * The list is the map of the draft, grouped by section in plan order; the
 * block under it is the tile the cursor is on, pinned to the bottom so the
 * three decisions are reachable however long the list gets.
 */
const DraftReviewPanel: React.FC<DraftReviewPanelProps> = ({
  tiles,
  currentIndex,
  sections,
  onSelect,
  onClose,
  onKeep,
  onRemove,
  onKeepAll,
  onRemoveAll,
  onRegenerate,
  onRegenerateSection,
  busy = false,
  error,
}) => {
  const [regenerateOpen, setRegenerateOpen] = useState(false);
  const [instruction, setInstruction] = useState('');
  const [removeAllOpen, setRemoveAllOpen] = useState(false);

  // The host owns the cursor, but a list that just lost a tile can reach the
  // panel one render before the clamp does, so read it defensively.
  const index = Math.min(Math.max(currentIndex, 0), Math.max(0, tiles.length - 1));
  const current: DraftTile | undefined = tiles[index];

  const reviewedCount = tiles.filter((t) => t.reviewed).length;
  // Removing a tile is a decision too, so a draft whose leftovers were all
  // deleted counts as fully reviewed: the total only ever counts what is left.
  const allReviewed = tiles.length === 0 || reviewedCount === tiles.length;
  const reviewedPct = tiles.length > 0 ? Math.min(100, (reviewedCount / tiles.length) * 100) : 0;

  const sectionByName = useMemo(() => {
    const byName = new Map<string, DraftReviewSection>();
    for (const s of sections ?? []) byName.set(s.name, s);
    return byName;
  }, [sections]);

  /** Grouped by tab, then by section, both in first-appearance order. The
   *  tile list arrives in plan order, so that is the plan's own order:
   *  filter panel first, then each grid section. */
  const tabGroups = useMemo<ReviewTabGroup[]>(() => {
    const tabsByKey = new Map<string, ReviewTabGroup>();
    const sectionsByKey = new Map<string, ReviewGroup>();
    const ordered: ReviewTabGroup[] = [];
    tiles.forEach((tile, i) => {
      const tabKey = tile.tab ?? '';
      let tab = tabsByKey.get(tabKey);
      if (!tab) {
        tab = { key: `tab:${tabKey}`, label: tile.tab ?? 'This tab', sections: [] };
        tabsByKey.set(tabKey, tab);
        ordered.push(tab);
      }
      const sectionKey = `${tabKey}\u0000${tile.section ?? ''}`;
      let group = sectionsByKey.get(sectionKey);
      if (!group) {
        const spec = tile.section ? sectionByName.get(tile.section) : undefined;
        group = {
          key: `section:${sectionKey}`,
          name: tile.section,
          label: tile.section ?? 'Unsectioned',
          icon: sectionIconId(spec?.icon, spec?.kind),
          color: spec?.color || null,
          items: [],
        };
        sectionsByKey.set(sectionKey, group);
        tab.sections.push(group);
      }
      group.items.push({ tile, index: i });
    });
    return ordered;
  }, [tiles, sectionByName]);

  /** The tab level is a fold only when there is more than one tab to fold:
   *  a single-tab draft would otherwise pay a click and a heading for a
   *  grouping that groups nothing. */
  const tabbed = tabGroups.length > 1;

  // Folds are open until closed, so `collapsed` holds only what the reviewer
  // shut. The two folds around the cursor are forced open whatever it says:
  // the tile under review has to be visible in the list that names it.
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const toggleFold = (key: string) =>
    setCollapsed((state) => ({ ...state, [key]: !state[key] }));

  const cursorKeys = useMemo(() => {
    for (const tab of tabGroups) {
      for (const section of tab.sections) {
        if (section.items.some((item) => item.index === index)) {
          return { tab: tab.key, section: section.key };
        }
      }
    }
    return { tab: '', section: '' };
  }, [tabGroups, index]);

  const foldOpen = (key: string) =>
    key === cursorKeys.tab || key === cursorKeys.section || !collapsed[key];

  const brief = (current?.intent ?? '').trim();
  const currentSection = current?.section ? sectionByName.get(current.section) : undefined;
  const sectionRationale = (currentSection?.rationale ?? '').trim();
  const currentType = componentTypeVisual(current?.componentType ?? '');
  // Grid sections only: the section regenerate re-runs the layout pass for a
  // row of boxes, and a filter-panel control's section is a fold of the left
  // panel. Its rationale still shows above, it just has no section to refill.
  const sectionRegenerable =
    Boolean(current?.section) &&
    current?.componentType !== 'interactive' &&
    Boolean(onRegenerateSection);

  /** Next tile still to review, wrapping past the end so a reviewer who
   *  started in the middle still lands on whatever is left behind them.
   *  Stays put once nothing is left. */
  const advanceFrom = (from: number) => {
    for (let step = 1; step < tiles.length; step += 1) {
      const next = (from + step) % tiles.length;
      if (!tiles[next].reviewed) {
        onSelect(next);
        return;
      }
    }
  };

  const keepCurrent = () => {
    if (!current) return;
    const wasReviewed = current.reviewed;
    void onKeep(current);
    // Keeping a tile is the click that finishes it, so the cursor moves on by
    // itself: twelve tiles are twelve clicks, not twenty four. Undoing a Keep
    // reopens the tile instead, so that one stays put.
    if (!wasReviewed) advanceFrom(index);
  };

  const removeCurrent = () => {
    if (!current) return;
    // No `onSelect`: the removed tile leaves the list, so this same slot now
    // holds the one after it. The host clamps when the last tile goes.
    void onRemove(current);
  };

  const regenerateCurrent = () => {
    if (!current) return;
    setRegenerateOpen(false);
    // The cursor does not move: the result of the regeneration is the thing
    // the reviewer was about to judge.
    void onRegenerate(current, instruction.trim());
  };

  const regenerateCurrentSection = () => {
    if (!current || !onRegenerateSection) return;
    setRegenerateOpen(false);
    void onRegenerateSection(current, instruction.trim());
  };

  return (
    <Stack gap={0} h="100%" data-testid="draft-review-panel">
      {/* Same header shape as the inspector, close control included: the two
          panels share the aside, so they have to be opened and dismissed the
          same way. */}
      <Group justify="space-between" wrap="nowrap" px="sm" py="xs">
        <Stack gap={0} style={{ minWidth: 0 }}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            AI draft
          </Text>
          <Text size="sm" fw={600} truncate>
            Review draft
          </Text>
        </Stack>
        <Tooltip label="Close review" withArrow>
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            onClick={onClose}
            aria-label="Close review"
            data-testid="draft-review-close"
          >
            <Icon icon="mdi:close" width={16} />
          </ActionIcon>
        </Tooltip>
      </Group>

      <Stack gap={4} px="sm" pb="xs">
        <Text size="xs" c="dimmed" data-testid="draft-review-position">
          {reviewedCount} of {tiles.length} reviewed
        </Text>
        <Progress
          value={reviewedPct}
          size="xs"
          color={AI_COLOR}
          aria-label={`${reviewedCount} of ${tiles.length} components reviewed`}
        />
        {/* The whole draft in one click, for the reviewer who has read the
            page rather than the list. Keep-all flips to its undo once
            everything is through, because a bulk action needs one. */}
        {tiles.length > 0 && (onKeepAll || onRemoveAll) && (
          <Group gap="xs" wrap="nowrap">
            {onKeepAll && (
              <Button
                size="compact-xs"
                variant="subtle"
                color="teal"
                leftSection={<Icon icon="mdi:check-all" width={14} />}
                disabled={busy}
                onClick={() => void onKeepAll(!allReviewed)}
                data-testid="draft-review-keep-all"
              >
                {allReviewed ? 'Unkeep all' : 'Keep all'}
              </Button>
            )}
            {onRemoveAll && (
              <Button
                size="compact-xs"
                variant="subtle"
                color="red"
                leftSection={<Icon icon="mdi:delete-sweep-outline" width={14} />}
                disabled={busy}
                onClick={() => setRemoveAllOpen(true)}
                data-testid="draft-review-remove-all"
              >
                Remove all
              </Button>
            )}
          </Group>
        )}
      </Stack>

      <Divider />

      {/* The map of the draft. Scrolls on its own so the decisions below stay
          put however many components the plan asked for. */}
      <ScrollArea type="auto" style={{ flex: 1, minHeight: 0 }}>
        <Stack gap="xs" py="xs">
          {tabGroups.map((tab) => (
            <Stack key={tab.key} gap={0}>
              {tabbed && (
                <FoldHeader
                  icon="mdi:tab"
                  color={null}
                  label={tab.label}
                  tiles={tab.sections.flatMap((s) => s.items.map((i) => i.tile))}
                  open={foldOpen(tab.key)}
                  onToggle={() => toggleFold(tab.key)}
                  testId="draft-review-tab"
                />
              )}
              <Collapse in={!tabbed || foldOpen(tab.key)}>
                <Stack gap="xs">
                  {tab.sections.map((group) => (
                    <Stack key={group.key} gap={0}>
                      {/* The section as the dashboard draws it: its own icon
                          and its own colour, so the list is recognisably the
                          same dashboard the reviewer is scrolling. */}
                      <FoldHeader
                        icon={group.icon}
                        color={group.color}
                        label={group.label}
                        tiles={group.items.map((i) => i.tile)}
                        open={foldOpen(group.key)}
                        onToggle={() => toggleFold(group.key)}
                        testId="draft-review-section"
                      />
                      <Collapse in={foldOpen(group.key)}>
                        {group.items.map(({ tile, index: tileIndex }) => {
                          const visual = componentTypeVisual(tile.componentType);
                          return (
                            <NavLink
                              key={tile.tag}
                              active={tileIndex === index}
                              color={AI_COLOR}
                              label={
                                <Text size="sm" truncate title={tile.title}>
                                  {tile.title}
                                </Text>
                              }
                              // The type is the icon and the colour the
                              // builder's type grid and the catalog picker
                              // already use for it, which says more in one
                              // glyph than a second line of label did.
                              leftSection={
                                <Tooltip
                                  label={visual.label}
                                  withArrow
                                  position="right"
                                  openDelay={400}
                                >
                                  <Box c={visual.color} style={{ display: 'inline-flex' }}>
                                    <Icon icon={visual.icon} width={16} height={16} />
                                  </Box>
                                </Tooltip>
                              }
                              // Reviewed on the trailing edge, where the checks
                              // line up as a column of progress against a
                              // ragged column of titles.
                              rightSection={
                                tile.reviewed ? (
                                  <Box c="teal" style={{ display: 'inline-flex' }}>
                                    <Icon icon="mdi:check-circle" width={15} height={15} />
                                  </Box>
                                ) : null
                              }
                              onClick={() => onSelect(tileIndex)}
                              data-testid="draft-review-item"
                              data-tag={tile.tag}
                              data-reviewed={tile.reviewed ? 'true' : 'false'}
                            />
                          );
                        })}
                      </Collapse>
                    </Stack>
                  ))}
                </Stack>
              </Collapse>
            </Stack>
          ))}
        </Stack>
      </ScrollArea>

      <Divider />

      {/* The tile under review and its verdicts, pinned under the list: the
          decision has to be one click away whatever the list is scrolled to. */}
      <Stack gap="xs" p="sm">
        {current && (
          <Stack gap={4}>
            <Group gap={6} wrap="nowrap">
              <Box c={currentType.color} style={{ display: 'inline-flex', flexShrink: 0 }}>
                <Icon icon={currentType.icon} width={16} height={16} />
              </Box>
              <Text
                size="sm"
                fw={600}
                truncate
                style={{ flex: '1 1 auto', minWidth: 0 }}
                title={current.title}
                data-testid="draft-review-current"
                data-tag={current.tag}
                data-reviewed={current.reviewed ? 'true' : 'false'}
              >
                {current.title}
              </Text>
              {busy && <Loader size="xs" color={AI_COLOR} />}
            </Group>
            <Group gap={4} wrap="nowrap">
              {current.section && (
                <>
                  <Box
                    c={currentSection?.color ?? 'dimmed'}
                    style={{ display: 'inline-flex', flexShrink: 0 }}
                  >
                    <Icon
                      icon={sectionIconId(currentSection?.icon, currentSection?.kind)}
                      width={12}
                      height={12}
                    />
                  </Box>
                  <Text size="xs" c="dimmed" truncate>
                    {current.section}
                  </Text>
                  <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                    ·
                  </Text>
                </>
              )}
              <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                {currentType.label}
              </Text>
            </Group>
            {/* The planner's own words, quoted rather than alerted: this is
                context for the decision, not something that went wrong. The
                border takes the AI colour off `c` so no colour is spelled out
                in the style. */}
            {(brief || sectionRationale) && (
              <Box
                pl="xs"
                c={AI_COLOR}
                style={{ borderInlineStart: '2px solid currentColor' }}
              >
                {/* Clamped, with the whole thing on the title: a long brief
                    would otherwise push the list up and the verdicts down. */}
                {brief && (
                  <Text size="xs" c="dimmed" lineClamp={3} title={brief}>
                    {`“${brief}”`}
                  </Text>
                )}
                {sectionRationale && (
                  <Text
                    size="xs"
                    c="dimmed"
                    mt={brief ? 2 : 0}
                    lineClamp={2}
                    title={sectionRationale}
                  >
                    {`${current.section}: “${sectionRationale}”`}
                  </Text>
                )}
              </Box>
            )}
          </Stack>
        )}

        {allReviewed || !current ? (
          <Group gap={6} wrap="nowrap">
            <Box c="teal" style={{ display: 'inline-flex' }}>
              <Icon icon="mdi:check-circle" width={16} height={16} />
            </Box>
            <Text size="sm">
              {tiles.length === 0
                ? 'No generated components left to review.'
                : `All ${tiles.length} generated component${
                    tiles.length === 1 ? '' : 's'
                  } reviewed.`}
            </Text>
          </Group>
        ) : (
          <Stack gap="xs">
            <Button
              size={BUTTON_SIZE}
              radius={BUTTON_RADIUS}
              fullWidth
              color="teal"
              leftSection={<Icon icon="mdi:check" width={16} />}
              disabled={busy}
              onClick={keepCurrent}
              data-testid="draft-review-keep"
            >
              {current.reviewed ? 'Reviewed, undo' : 'Keep'}
            </Button>
            <Button
              size={BUTTON_SIZE}
              radius={BUTTON_RADIUS}
              fullWidth
              variant="light"
              color={AI_COLOR}
              leftSection={<Icon icon="mdi:refresh" width={16} />}
              rightSection={
                <Icon icon={regenerateOpen ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={16} />
              }
              disabled={busy}
              onClick={() => setRegenerateOpen((o) => !o)}
              data-testid="draft-review-regenerate"
            >
              Regenerate
            </Button>
            {/* Inline rather than in a popover: the panel is the surface the
                reviewer is already looking at, and a dropdown over the canvas
                is the shape this replaced. */}
            {regenerateOpen && (
              <Stack gap="xs">
                <Textarea
                  label="Anything to change?"
                  description="Optional. Left empty, the component is filled again from the plan's own intent."
                  placeholder="e.g. use a box plot, group by cohort"
                  autosize
                  minRows={2}
                  maxRows={5}
                  value={instruction}
                  onChange={(e) => setInstruction(e.currentTarget.value)}
                  data-testid="draft-review-instruction"
                />
                <Button
                  size={BUTTON_SIZE}
                  radius={BUTTON_RADIUS}
                  fullWidth
                  color={AI_COLOR}
                  leftSection={<Icon icon="mdi:refresh" width={16} />}
                  disabled={busy}
                  onClick={regenerateCurrent}
                  data-testid="draft-review-regenerate-run"
                >
                  Regenerate this component
                </Button>
                {sectionRegenerable && (
                  <Button
                    size={BUTTON_SIZE}
                    radius={BUTTON_RADIUS}
                    fullWidth
                    variant="subtle"
                    color={AI_COLOR}
                    disabled={busy}
                    onClick={regenerateCurrentSection}
                    data-testid="draft-review-regenerate-section"
                  >
                    Regenerate the whole section
                  </Button>
                )}
              </Stack>
            )}
            <Button
              size={BUTTON_SIZE}
              radius={BUTTON_RADIUS}
              fullWidth
              variant="subtle"
              color="red"
              leftSection={<Icon icon="mdi:delete-outline" width={16} />}
              disabled={busy}
              onClick={removeCurrent}
              data-testid="draft-review-remove"
            >
              Remove
            </Button>
          </Stack>
        )}

        {error && (
          <Text size="xs" c="red">
            {error}
          </Text>
        )}
      </Stack>

      <Modal
        opened={removeAllOpen}
        onClose={() => setRemoveAllOpen(false)}
        title="Remove every generated component?"
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            All {tiles.length} generated component{tiles.length === 1 ? '' : 's'} are deleted
            from this dashboard. The dashboard itself stays, with whatever was added to it by
            hand; deleting the draft outright is <b>Discard</b> on the banner.
          </Text>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={() => setRemoveAllOpen(false)}>
              Keep reviewing
            </Button>
            <Button
              color="red"
              onClick={() => {
                setRemoveAllOpen(false);
                void onRemoveAll?.();
              }}
              data-testid="draft-review-remove-all-confirm"
            >
              Remove all
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
};

export default DraftReviewPanel;
