import { Group, Title, Text, ActionIcon, Tooltip, Anchor } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useColorScheme } from '../hooks/useColorScheme';

/**
 * Top bar (height 56). Left: the Tools Catalog mark (depictio pinwheel + hammer,
 * theme-agnostic) and the "Depictio Tools Studio" wordmark in Virgil. Right: a
 * compact Docs link and the dark-mode toggle. Neutral chrome — the brand colour
 * comes from the logo and the component-type cards.
 */
export default function AppHeader() {
  const { colorScheme, toggle } = useColorScheme();
  return (
    <Group
      h={56}
      px="lg"
      justify="space-between"
      wrap="nowrap"
      style={{ borderBottom: '1px solid var(--app-border-color)' }}
    >
      <Group gap="sm" wrap="nowrap">
        {/* Colored, transparent mark — reads on light and dark, no swap needed. */}
        <img
          src={`${import.meta.env.BASE_URL}logos/tools_catalog_logo.png`}
          alt="Depictio Tools Studio"
          height={30}
          width={30}
          style={{ objectFit: 'contain' }}
        />
        <div style={{ lineHeight: 1.05 }}>
          <Title order={4} style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
            Depictio Tools Studio
          </Title>
          <Text size="xs" c="dimmed">
            Contribute a tool to the catalog
          </Text>
        </div>
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
            Docs
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
