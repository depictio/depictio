import { Anchor, Badge, Box, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

const LINKS = [
  { label: 'Docs', href: 'https://depictio.github.io/depictio-docs/stable/catalog/' },
  { label: 'Catalog', href: 'https://github.com/depictio/depictio/tree/main/depictio/catalog' },
  { label: 'Report an issue', href: 'https://github.com/depictio/depictio/issues/new' },
];

/**
 * Footer bar. Rendered inside `AppShell.Footer`, so it is pinned to the bottom
 * of the viewport and stays visible while the wizard scrolls between it and the
 * header. AppShell reserves the matching padding on the main column, so nothing
 * ever hides behind it.
 *
 * Full-bleed on the header's own `px="lg"` gutter rather than inside a
 * `Container`: a centred container is narrower than the bar it sits in, and the
 * width it gave away is what squeezed the beta badge out of view and wrapped
 * "Report an issue" onto a second line. So everything on the right is `nowrap`
 * and unshrinkable, and the privacy note on the left is the single flexible
 * part: it truncates, then drops entirely below `md`.
 *
 * A static site published from a build has no other way to say *which* build
 * you are looking at, so the bar carries both versions: Tool Studio's own
 * (packages/tool-studio/package.json, bumped with `pnpm --filter tool-studio run
 * bump <patch|minor|major>`) and the depictio release it was cut from
 * (.bumpversion.cfg), which pins the catalog schema the export has to satisfy.
 * The deploy commit follows them in parentheses on the same line, so the two
 * versions read as one pair and the sha as their qualifier rather than a third
 * peer; it appears only when the Pages workflow provides GITHUB_SHA. All three
 * are injected at build time, see vite.config.ts. That single line is what the
 * shell's footer height is sized to.
 *
 * The beta badge sits with those versions rather than in the header: it qualifies
 * this build, and the reader who wants to know how finished the app is looks in
 * the same place as the one asking which build they are on.
 */
export default function AppFooter() {
  const sha = __BUILD_SHA__;
  return (
    <Box component="footer" h="100%" px="lg" style={{ display: 'flex', alignItems: 'center' }}>
      <Group justify="space-between" align="center" gap="md" wrap="nowrap" w="100%">
        <Group gap={6} wrap="nowrap" visibleFrom="md" style={{ minWidth: 0 }}>
          <Icon icon="mdi:shield-lock-outline" width={15} style={{ flexShrink: 0 }} />
          <Text size="xs" c="dimmed" lineClamp={1}>
            Runs entirely in your browser. Your file is parsed locally and only ever leaves this
            page if you open a pull request.
          </Text>
        </Group>
        <Group gap="md" wrap="nowrap" ml="auto" style={{ flexShrink: 0 }}>
          <Group gap={8} wrap="nowrap" align="center">
            <Badge size="xs" variant="light" color="brand" radius="sm" style={{ flexShrink: 0 }}>
              beta
            </Badge>
            <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
              Studio v{__STUDIO_VERSION__} · depictio v{__DEPICTIO_VERSION__}
              {sha ? ` (${sha})` : ''}
            </Text>
          </Group>
          {LINKS.map(({ label, href }) => (
            <Anchor
              key={href}
              size="xs"
              c="dimmed"
              href={href}
              target="_blank"
              rel="noreferrer"
              style={{ whiteSpace: 'nowrap' }}
            >
              {label}
            </Anchor>
          ))}
        </Group>
      </Group>
    </Box>
  );
}
