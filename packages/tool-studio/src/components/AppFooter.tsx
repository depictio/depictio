import { Anchor, Box, Container, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

/**
 * Footer bar. Rendered inside `AppShell.Footer`, so it is pinned to the bottom
 * of the viewport and stays visible while the wizard scrolls between it and the
 * header. AppShell reserves the matching padding on the main column, so nothing
 * ever hides behind it.
 *
 * That pinning is also why everything here is one non-wrapping row of `xs` text
 * sized to the shell's declared height: a second line would overflow the bar
 * rather than push the page. The privacy note is the part that goes when the
 * viewport is too narrow to hold both halves.
 *
 * A static site published from a build has no other way to say *which* build
 * you are looking at, so the bar carries both versions: Tool Studio's own
 * (packages/tool-studio/package.json, bumped by hand when the app changes)
 * and the depictio release it was cut from (.bumpversion.cfg), which pins the
 * catalog schema the export has to satisfy. The deploy commit is added when the
 * Pages workflow provides GITHUB_SHA. All three are injected at build time, see
 * vite.config.ts.
 */
export default function AppFooter() {
  const sha = __BUILD_SHA__;
  return (
    <Box component="footer" h="100%" style={{ display: 'flex', alignItems: 'center' }}>
      <Container size="lg" w="100%">
        <Group justify="space-between" align="center" gap="md" wrap="nowrap">
          <Group gap={6} wrap="nowrap" visibleFrom="md">
            <Icon icon="mdi:shield-lock-outline" width={15} />
            <Text size="xs" c="dimmed" lineClamp={1}>
              Runs entirely in your browser. Your file is parsed locally and only ever leaves this
              page if you open a pull request.
            </Text>
          </Group>
          <Group gap="md" wrap="nowrap" ml="auto">
            <Text size="xs" c="dimmed">
              Studio v{__STUDIO_VERSION__} · depictio v{__DEPICTIO_VERSION__}
              {sha ? ` · ${sha}` : ''}
            </Text>
            <Anchor
              size="xs"
              c="dimmed"
              href="https://depictio.github.io/depictio-docs/stable/catalog/"
              target="_blank"
              rel="noreferrer"
            >
              Docs
            </Anchor>
            <Anchor
              size="xs"
              c="dimmed"
              href="https://github.com/depictio/depictio/tree/main/depictio/catalog"
              target="_blank"
              rel="noreferrer"
            >
              Catalog
            </Anchor>
            <Anchor
              size="xs"
              c="dimmed"
              href="https://github.com/depictio/depictio/issues/new"
              target="_blank"
              rel="noreferrer"
            >
              Report an issue
            </Anchor>
          </Group>
        </Group>
      </Container>
    </Box>
  );
}
