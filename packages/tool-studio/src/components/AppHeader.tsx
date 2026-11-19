import React from 'react';
import { Badge, Popover, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { BookOpen, ChevronRight, Info, Moon, ShieldCheck, Sun } from 'lucide-react';
import { StaticBadgeProvider } from 'depictio-react-core';
import PoweredBy from 'depictio-chrome/PoweredBy';
import DepictioRose from '../../../../depictio/viewer/src/components/rose/DepictioRose';
import { useColorScheme } from '../hooks/useColorScheme';
import { useStudioStore } from '../state/useStudioStore';

/** depictio's hairline stroke for chrome glyphs (glass/icons.tsx). */
const STROKE = 1.6;

export const DOCS_URL = 'https://depictio.github.io/depictio-docs/stable/catalog/';
export const CATALOG_URL = 'https://github.com/depictio/depictio/tree/main/depictio/catalog';
export const ISSUES_URL = 'https://github.com/depictio/depictio/issues/new';

/** The privacy promise, said once and reused wherever it is shown. */
export const PRIVACY_LINE =
  'Runs entirely in your browser. Your file is parsed locally and only ever leaves this page if you open a pull request.';

type TopKeyProps = {
  label: string;
  tip?: string;
  /** No tooltip while what the key opens is showing. */
  tipDisabled?: boolean;
  href?: string;
  onClick?: () => void;
  className?: string;
  children: React.ReactNode;
} & { [attr: `data-${string}`]: string | undefined };

/** A key of the top bar: the dashboards' `hy-key--top` (layout.css), named by
 *  a tooltip as depictio names its icon keys. */
const TopKey = React.forwardRef<HTMLElement, TopKeyProps>(function TopKey(
  { label, tip, tipDisabled, href, onClick, className, children, ...rest },
  ref,
) {
  const cls = `hy-key hy-key--top${className ? ` ${className}` : ''}`;
  return (
    <Tooltip label={tip ?? label} withArrow openDelay={250} opened={tipDisabled ? false : undefined}>
      {href ? (
        <a
          ref={ref as React.Ref<HTMLAnchorElement>}
          className={cls}
          href={href}
          target="_blank"
          rel="noreferrer"
          aria-label={label}
          {...rest}
        >
          {children}
        </a>
      ) : (
        <button
          ref={ref as React.Ref<HTMLButtonElement>}
          type="button"
          className={cls}
          onClick={onClick}
          aria-label={label}
          {...rest}
        >
          {children}
        </button>
      )}
    </Tooltip>
  );
});

/**
 * Which build this is, and where to go from here. depictio's static bundle has
 * no footer, so what the Studio's footer used to carry (the beta status, both
 * versions, the docs and issue links, the privacy line) sits behind this key,
 * the way the serverless bar keeps its settings behind one. The deploy commit
 * follows the versions only when the Pages workflow provides GITHUB_SHA; all
 * three are injected at build time (vite.config.ts).
 */
function AboutKey() {
  const sha = __BUILD_SHA__;
  const [opened, setOpened] = React.useState(false);
  return (
    <Popover
      position="bottom-end"
      width={330}
      offset={10}
      onOpen={() => setOpened(true)}
      onClose={() => setOpened(false)}
    >
      <Popover.Target>
        <TopKey
          label="About Tool Studio"
          tipDisabled={opened}
          data-testid="about-key"
        >
          <Info size={21} strokeWidth={STROKE} aria-hidden />
        </TopKey>
      </Popover.Target>
      <Popover.Dropdown className="ts-about" p="md">
        <Stack gap={10}>
          <Text component="div" fw={700} size="sm">
            Tool Studio{' '}
            <Badge size="xs" variant="light" color="violet" ml={4} style={{ verticalAlign: 'middle' }}>
              beta
            </Badge>
          </Text>
          <Text size="xs" c="dimmed" data-testid="build-versions">
            Studio v{__STUDIO_VERSION__} · depictio v{__DEPICTIO_VERSION__}
            {sha ? ` (${sha})` : ''}
          </Text>
          <div className="ts-about-row">
            <ShieldCheck size={15} strokeWidth={1.8} aria-hidden />
            <span>{PRIVACY_LINE}</span>
          </div>
          <nav className="ts-about-links" aria-label="Tool Studio links">
            <a href={DOCS_URL} target="_blank" rel="noreferrer">
              Docs
            </a>
            <a href={CATALOG_URL} target="_blank" rel="noreferrer">
              Catalog
            </a>
            <a href={ISSUES_URL} target="_blank" rel="noreferrer">
              Report an issue
            </a>
          </nav>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}

/**
 * The top bar: depictio's Paper bar, as the serverless bundles draw it
 * (`hy-top` in chrome/variants/glass/layout.css). The rose on the left (the
 * way back to the start screen once a draft is open), the Studio's name in the
 * bar's title type with the current step after it, the "Powered by depictio"
 * credit, then the keys: the docs, the catalog on GitHub, About and the theme.
 * Below `sm` it turns compact, like the dashboards' bar.
 */
export default function AppHeader({ context, compact }: { context?: string; compact: boolean }) {
  const { colorScheme, toggle } = useColorScheme();
  const dark = colorScheme === 'dark';
  // The mark is the way back to the start screen. `showIntro` keeps the draft,
  // so re-reading what the app does never costs the work in progress.
  const started = useStudioStore((s) => s.started);
  const showIntro = useStudioStore((s) => s.showIntro);
  const [hovered, setHovered] = React.useState(false);
  const markSize = compact ? 28 : 34;

  return (
    <header className={`hy-top${compact ? ' hy-top--compact' : ''}`} data-testid="app-header">
      {started ? (
        <Tooltip label="What this app does" withArrow openDelay={400}>
          <button
            type="button"
            className="hy-top-brand hy-top-brand--mark"
            onClick={showIntro}
            aria-label="Back to the start screen"
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
          >
            <DepictioRose mode={hovered ? 'petals' : 'logo'} size={markSize} label="" />
          </button>
        </Tooltip>
      ) : (
        <span className="hy-top-brand hy-top-brand--mark">
          <DepictioRose mode="logo" size={markSize} label="depictio" />
        </span>
      )}
      <span className="hy-top-rule" aria-hidden />
      <div className={`hy-top-title${context ? '' : ' hy-top-title--solo'}`}>
        <span className="hy-top-dash">Tool Studio</span>
        {context && (
          <>
            <ChevronRight className="hy-top-chev" size={16} strokeWidth={2} aria-hidden />
            <span className="hy-top-tab">{context}</span>
          </>
        )}
      </div>
      <span className="hy-flex" />
      {/* The credit always shows here, as in a static bundle: the Studio, like
          a bundle, has no app rail carrying the wordmark. The provider is the
          bundle's "no server" signal, which is also what makes the wordmark
          load from the bundled asset rather than from a server path. */}
      <span className="hy-top-powered">
        <StaticBadgeProvider tiers={{}}>
          <PoweredBy always />
        </StaticBadgeProvider>
      </span>
      <div className="hy-top-keys">
        <TopKey label="Documentation" href={DOCS_URL} className="ts-key-wide">
          <BookOpen size={21} strokeWidth={STROKE} aria-hidden />
        </TopKey>
        <TopKey label="Catalog source on GitHub" href={CATALOG_URL} className="ts-key-wide">
          <Icon icon="mdi:github" width={21} height={21} aria-hidden />
        </TopKey>
        <AboutKey />
        <TopKey
          label="Toggle color scheme"
          tip={dark ? 'Switch to light theme' : 'Switch to dark theme'}
          onClick={toggle}
          data-testid="theme-toggle"
        >
          {dark ? (
            <Sun size={21} strokeWidth={STROKE} aria-hidden />
          ) : (
            <Moon size={21} strokeWidth={STROKE} aria-hidden />
          )}
        </TopKey>
      </div>
    </header>
  );
}
