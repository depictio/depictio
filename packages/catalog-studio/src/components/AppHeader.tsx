import { Group, Title, ActionIcon, Tooltip, Anchor, Badge } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useColorScheme } from '../hooks/useColorScheme';

/**
 * Light top bar (height 50, mirrors the viewer's AppShell.Header). Left: the
 * depictio wordmark + a Virgil "Catalog Studio" title. Right: a "no backend"
 * badge, a docs link, and the dark-mode toggle.
 */
export default function AppHeader() {
  const { colorScheme, toggle } = useColorScheme();
  // logo_black/logo_white read on light/dark surfaces respectively; swap by
  // CSS display so both are cached and there's no flash on toggle.
  return (
    <Group h={50} px="md" justify="space-between" wrap="nowrap" style={{ borderBottom: '1px solid var(--app-border-color)' }}>
      <Group gap="sm" wrap="nowrap">
        {/* base-relative asset — Vite prepends '/depictio/' at build. */}
        <img src={`${import.meta.env.BASE_URL}logos/logo_black.svg`} alt="Depictio" height={22} style={{ display: colorScheme === 'dark' ? 'none' : 'block' }} />
        <img src={`${import.meta.env.BASE_URL}logos/logo_white.svg`} alt="Depictio" height={22} style={{ display: colorScheme === 'dark' ? 'block' : 'none' }} />
        <Title order={4} style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
          Catalog Studio
        </Title>
        <Badge size="xs" variant="light" color="gray">
          no backend
        </Badge>
      </Group>
      <Group gap="xs" wrap="nowrap">
        <Anchor
          href="https://github.com/depictio/depictio/tree/main/depictio/catalog"
          target="_blank"
          rel="noreferrer"
          size="sm"
          c="dimmed"
        >
          <Group gap={4} wrap="nowrap">
            <Icon icon="mdi:book-open-variant" width={16} />
            Catalog docs
          </Group>
        </Anchor>
        <Tooltip label={colorScheme === 'dark' ? 'Light mode' : 'Dark mode'}>
          <ActionIcon variant="subtle" color="gray" onClick={toggle} aria-label="Toggle color scheme">
            <Icon icon={colorScheme === 'dark' ? 'mdi:weather-sunny' : 'mdi:weather-night'} width={20} />
          </ActionIcon>
        </Tooltip>
      </Group>
    </Group>
  );
}
