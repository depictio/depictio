/**
 * What this app is, before any form.
 *
 * The wizard used to open straight on the Tool step: two panels of `slug` and
 * `path_glob` with the explanation squeezed into grey fine print above them.
 * Someone arriving from a link had to reverse-engineer what a catalog entry is
 * from the fields that build one. This screen answers that first: what an entry
 * does for people who run the tool, the four steps it takes, and what it does
 * not cover.
 *
 * Shown once per draft: `started` is persisted, so a refresh mid-entry returns
 * to the work rather than to the pitch, and `Start over` (which resets the
 * draft) brings the screen back.
 */
import {
  Box,
  Button,
  Code,
  Container,
  Group,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { HEADING_FONT } from '../theme';

/** One colour per step, carried by its icon tile, its border and the arrow
 *  that points into it, so the four are told apart at a glance rather than
 *  only read in order. */
const STEPS = [
  {
    icon: 'mdi:tools',
    color: 'violet',
    title: 'Tool',
    body: 'Name the tool and the output file this entry describes. nf-core, Snakemake and Galaxy prefill it from a URL.',
  },
  {
    icon: 'mdi:file-delimited-outline',
    color: 'blue',
    title: 'Fixture',
    body: 'Drop one sample of that file. It is read in this page, and ships with the entry as the example CI checks against.',
  },
  {
    icon: 'mdi:chart-box-outline',
    color: 'teal',
    title: 'Visualizations',
    body: "Bind its columns in depictio's own component builder: cards, figures, tables, filters, advanced plots.",
  },
  {
    icon: 'mdi:download',
    color: 'pink',
    title: 'Export',
    body: 'Download the entry as a zip, or sign in and open the pull request against depictio in one click.',
  },
] as const;

/** Connector geometry. Each box sits `INDENT` further right than the one above
 *  it, and the elbow that joins them drops from under the previous box, turns
 *  at the next box's vertical middle and points into its left edge. `GAP` is
 *  the breathing room between boxes, which is also the height the vertical
 *  segment has to cover before it reaches the box. */
const INDENT = 34;
const GAP = 16;
/** Where the vertical segment falls, measured from the box it points into. */
const ELBOW_X = 18;
/** All four boxes are this wide, whatever they say: same width, same height,
 *  each one shifted right by `INDENT`. Narrow enough that every sentence wraps
 *  onto a second line, which is what makes the four read as one series. */
const STEP_WIDTH = 740;
/** The staircase as a block, centred in the column. */
const CASCADE_WIDTH = STEP_WIDTH + 3 * INDENT;
/** The scope pair sits narrower than the cascade, as its footnote. */
const SCOPE_WIDTH = 700;

export default function StartScreen({ onStart, resuming }: { onStart: () => void; resuming?: boolean }) {
  return (
    /* One reading column. Only the title and the call to action are centred:
       centring the running text as well made every paragraph start at a
       different place, and the page read as unsettled. */
    <Container
      size="lg"
      pt="md"
      pb="lg"
      style={{
        minHeight: 'calc(100dvh - var(--app-shell-header-offset, 56px) - var(--app-shell-footer-offset, 44px))',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Stack gap="lg">
        <Stack gap="xs" maw={820} mx="auto">
          <Title
            order={1}
            fz={{ base: 26, sm: 31 }}
            fw={600}
            lh={1.25}
            ta="center"
            style={{ fontFamily: HEADING_FONT }}
          >
            Add a tool to the Depictio Tools Catalog
          </Title>
          <Text size="lg" c="dimmed" ta="center">
            An entry teaches depictio to recognise one output file of a tool and to turn it into
            ready-made dashboard components for everyone who runs it.
          </Text>
        </Stack>

      </Stack>

      {/* The steps sit in the middle band, centred in whatever height the
          intro and the footer-anchored block leave them. */}
      <Box style={{ flex: 1, display: 'flex', alignItems: 'center' }} py="lg">
        {/* A cascade: every box a step further in, joined by an elbow that
            drops from the one above and turns into the next box at its middle.
            The arrowhead is a CSS triangle rather than an icon glyph, because a
            glyph carries its own padding and never sits on the line. */}
        <Stack gap={GAP} w={CASCADE_WIDTH} mx="auto" maw="100%">
          {STEPS.map((s, i) => (
            <Box key={s.title} style={{ position: 'relative', paddingLeft: i * INDENT }}>
              {i > 0 && (
                <>
                  {/* Down from under the previous box... */}
                  <Box
                    style={{
                      position: 'absolute',
                      left: i * INDENT - ELBOW_X,
                      top: -GAP,
                      height: `calc(50% + ${GAP}px)`,
                      width: 2,
                      background: `var(--mantine-color-${s.color}-4)`,
                    }}
                  />
                  {/* ...then right, into this box's middle. */}
                  <Box
                    style={{
                      position: 'absolute',
                      left: i * INDENT - ELBOW_X,
                      top: '50%',
                      width: ELBOW_X - 6,
                      height: 2,
                      marginTop: -1,
                      background: `var(--mantine-color-${s.color}-4)`,
                    }}
                  />
                  <Box
                    style={{
                      position: 'absolute',
                      left: i * INDENT - 7,
                      top: '50%',
                      marginTop: -4,
                      width: 0,
                      height: 0,
                      borderTop: '4px solid transparent',
                      borderBottom: '4px solid transparent',
                      borderLeft: `6px solid var(--mantine-color-${s.color}-4)`,
                    }}
                  />
                </>
              )}
              <Paper
                withBorder
                radius="md"
                py="lg"
                px="lg"
                style={{
                  width: STEP_WIDTH,
                  maxWidth: '100%',
                  borderColor: `var(--mantine-color-${s.color}-3)`,
                }}
              >
                <Group gap="sm" wrap="nowrap" align="center">
                  <Box
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: 56,
                      height: 56,
                      flexShrink: 0,
                      borderRadius: 11,
                      background: `var(--mantine-color-${s.color}-light)`,
                      color: `var(--mantine-color-${s.color}-filled)`,
                    }}
                  >
                    <Icon icon={s.icon} width={31} />
                  </Box>
                  <div>
                    <Text fw={700} size="xl" lh={1.3}>
                      {i + 1}. {s.title}
                    </Text>
                    <Text size="md" c="dimmed" lh={1.4}>
                      {s.body}
                    </Text>
                  </div>
                </Group>
              </Paper>
            </Box>
          ))}
        </Stack>
      </Box>

      <Stack gap="md">
        {/* Scope, as two facing panels. Half the committed catalog outputs need
            a parsing recipe, and someone who came to describe one of those
            should learn it here, not three steps in with a file that will not
            parse. */}
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm" w={SCOPE_WIDTH} mx="auto" maw="100%">
          <Paper withBorder radius="md" p="md">
            <Group gap={8} wrap="nowrap" align="flex-start">
              <Icon
                icon="mdi:check-circle-outline"
                width={21}
                color="var(--mantine-color-teal-6)"
                style={{ marginTop: 2, flexShrink: 0 }}
              />
              <div>
                <Text fw={600} size="md">
                  Use this app
                </Text>
                <Text size="md" c="dimmed">
                  when the output file is already a table with a header row.
                </Text>
              </div>
            </Group>
          </Paper>
          <Paper withBorder radius="md" p="md">
            <Group gap={8} wrap="nowrap" align="flex-start">
              <Icon
                icon="mdi:minus-circle-outline"
                width={21}
                color="var(--mantine-color-dimmed)"
                style={{ marginTop: 2, flexShrink: 0 }}
              />
              <div>
                <Text fw={600} size="md">
                  Not yet
                </Text>
                <Text size="md" c="dimmed">
                  when it needs reshaping first: hand-written in{' '}
                  <Code fz="md">depictio/catalog/</Code>.
                </Text>
              </div>
            </Group>
          </Paper>
        </SimpleGrid>

        <Group justify="center">
          <Button
            size="lg"
            px={44}
            onClick={onStart}
            rightSection={<Icon icon="mdi:arrow-right" width={20} />}
            data-testid="start"
          >
            {resuming ? 'Continue' : 'Start'}
          </Button>
        </Group>
      </Stack>
    </Container>
  );
}
