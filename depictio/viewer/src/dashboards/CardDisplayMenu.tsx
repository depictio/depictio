import React from 'react';
import {
  ActionIcon,
  Box,
  Checkbox,
  Divider,
  Menu,
  SegmentedControl,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import type { CardBadge, CardsPerRow } from './hooks/useDashboardViewPrefs';
import { CARD_BADGES, CARDS_PER_ROW_OPTIONS } from './hooks/useDashboardViewPrefs';

export interface CardDisplayMenuProps {
  cardsPerRow: CardsPerRow;
  cardBadges: CardBadge[];
  onCardsPerRowChange: (value: CardsPerRow) => void;
  onCardBadgesChange: (badges: CardBadge[]) => void;
}

const BADGE_LABELS: Record<CardBadge, string> = {
  project: 'Project',
  template: 'Template',
  owner: 'Owner',
  visibility: 'Visibility',
  modified: 'Last modified',
  tabs: 'Tabs',
};

const CARDS_PER_ROW_DATA = CARDS_PER_ROW_OPTIONS.map((value) => ({
  value: String(value),
  label: value === 'auto' ? 'Auto' : String(value),
}));

/**
 * Thumbnails-view layout options: how many cards share a row, and which
 * metadata badges each card shows under its title.
 *
 * The menu stays open across clicks (`closeOnItemClick={false}`) so several
 * badges can be toggled in one go while the grid reflows behind it, which is
 * the quickest way to judge a layout.
 */
const CardDisplayMenu: React.FC<CardDisplayMenuProps> = ({
  cardsPerRow,
  cardBadges,
  onCardsPerRowChange,
  onCardBadgesChange,
}) => {
  const accent = useBrandAccents();
  const customised =
    cardsPerRow !== 'auto' || CARD_BADGES.some((b) => !cardBadges.includes(b));

  // Rebuilt from CARD_BADGES rather than appended to, so the stored selection
  // always follows the card's own badge order.
  const toggleBadge = (badge: CardBadge) => {
    const next = new Set(cardBadges);
    if (next.has(badge)) next.delete(badge);
    else next.add(badge);
    onCardBadgesChange(CARD_BADGES.filter((b) => next.has(b)));
  };

  return (
    <Menu
      shadow="md"
      width={260}
      closeOnItemClick={false}
      withinPortal
      position="bottom-end"
    >
      <Menu.Target>
        <Tooltip label="Card display" withinPortal>
          <ActionIcon
            variant={customised ? 'light' : 'default'}
            color={customised ? accent.tertiary : undefined}
            size="lg"
            radius="md"
            aria-label="Card display"
          >
            <Icon icon="mdi:card-bulleted-settings-outline" width={18} />
          </ActionIcon>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Cards per row</Menu.Label>
        <Box px="sm" pb="xs">
          <SegmentedControl
            size="xs"
            fullWidth
            value={String(cardsPerRow)}
            onChange={(v) =>
              onCardsPerRowChange(
                CARDS_PER_ROW_OPTIONS.find((o) => String(o) === v) ?? 'auto',
              )
            }
            data={CARDS_PER_ROW_DATA}
            aria-label="Cards per row"
          />
        </Box>
        <Divider my={4} />
        <Menu.Label>Show on cards</Menu.Label>
        {CARD_BADGES.map((badge) => (
          <Menu.Item key={badge} onClick={() => toggleBadge(badge)}>
            {/* Presentational, as in ColumnPicker: the row's onClick owns the
                toggle, and swallowing the input's own click stops the label's
                re-dispatched click from toggling a second time. */}
            <Checkbox
              size="xs"
              checked={cardBadges.includes(badge)}
              readOnly
              onClick={(e) => e.stopPropagation()}
              label={BADGE_LABELS[badge]}
              styles={{ label: { cursor: 'pointer' }, input: { cursor: 'pointer' } }}
            />
          </Menu.Item>
        ))}
        <Divider my={4} />
        <Menu.Item
          leftSection={<Icon icon="mdi:restore" width={14} />}
          disabled={!customised}
          onClick={() => {
            onCardsPerRowChange('auto');
            onCardBadgesChange([...CARD_BADGES]);
          }}
        >
          Reset to defaults
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
};

export default CardDisplayMenu;
