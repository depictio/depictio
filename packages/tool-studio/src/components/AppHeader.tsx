import { ActionIcon, Group, Text, Title, Tooltip, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useColorScheme } from '../hooks/useColorScheme';
import { HEADING_FONT } from '../theme';
import { useStudioStore } from '../state/useStudioStore';

/**
 * Top bar (height 56). Left: the depictio Catalog mark (depictio pinwheel + hammer,
 * theme-agnostic) and the "Depictio Tool Studio" wordmark in the display face
 * (`HEADING_FONT`), the same one the start screen's title uses. Right:
 * icon-only links to the documentation and to the catalog source on GitHub, then
 * the dark-mode toggle. The two destinations are different (prose guide vs the
 * committed entries), so both are offered rather than one standing in for the
 * other. Neutral chrome — the brand colour comes from the logo and the
 * component-type cards.
 */
export default function AppHeader() {
  const { colorScheme, toggle } = useColorScheme();
  // The wordmark is the way back to the start screen. `showIntro` keeps the
  // draft, so re-reading what the app does never costs the work in progress.
  const started = useStudioStore((s) => s.started);
  const showIntro = useStudioStore((s) => s.showIntro);
  return (
    <Group
      h={56}
      px="lg"
      justify="space-between"
      wrap="nowrap"
      style={{ borderBottom: '1px solid var(--app-border-color)' }}
    >
      <Tooltip label="What this app does" disabled={!started} openDelay={400}>
        <UnstyledButton
          onClick={started ? showIntro : undefined}
          style={{ cursor: started ? 'pointer' : 'default' }}
          aria-label={started ? 'Back to the start screen' : undefined}
        >
          <Group gap="sm" wrap="nowrap">
            {/* Colored, transparent mark — reads on light and dark, no swap needed. */}
            <img
              src={`${import.meta.env.BASE_URL}logos/tools_catalog_logo.png`}
              alt="Depictio Tool Studio"
              height={30}
              width={30}
              style={{ objectFit: 'contain' }}
            />
            <div style={{ lineHeight: 1.05, textAlign: 'left' }}>
              <Title order={4} style={{ fontFamily: HEADING_FONT, fontWeight: 600 }}>
                Depictio Tool Studio
              </Title>
              <Text size="xs" c="dimmed">
                Contribute a tool to the catalog
              </Text>
            </div>
          </Group>
        </UnstyledButton>
      </Tooltip>
      <Group gap="xs" wrap="nowrap">
        <Tooltip label="Documentation">
          <ActionIcon
            component="a"
            href="https://depictio.github.io/depictio-docs/stable/catalog/"
            target="_blank"
            rel="noreferrer"
            variant="subtle"
            color="gray"
            aria-label="Documentation"
          >
            <Icon icon="mdi:book-open-variant" width={20} />
          </ActionIcon>
        </Tooltip>
        <Tooltip label="Catalog source on GitHub">
          <ActionIcon
            component="a"
            href="https://github.com/depictio/depictio/tree/main/depictio/catalog"
            target="_blank"
            rel="noreferrer"
            variant="subtle"
            color="gray"
            aria-label="Catalog source on GitHub"
          >
            <Icon icon="mdi:github" width={20} />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={colorScheme === 'dark' ? 'Light mode' : 'Dark mode'}>
          <ActionIcon variant="subtle" color="gray" onClick={toggle} aria-label="Toggle color scheme">
            <Icon icon={colorScheme === 'dark' ? 'mdi:weather-sunny' : 'mdi:weather-night'} width={20} />
          </ActionIcon>
        </Tooltip>
      </Group>
    </Group>
  );
}
