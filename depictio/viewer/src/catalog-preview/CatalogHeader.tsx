/**
 * The catalog's top bar in Paper: depictio's Paper bar (`hy-top`, from
 * chrome/variants/glass/layout.css), drawn the way Tool Studio draws its own
 * (packages/tool-studio AppHeader). The rose on the left, a rule, "Tools
 * catalog" in the bar's title type with where the reader is after it, then the
 * "Powered by depictio" credit and the icon keys. Below `sm` the bar turns
 * compact, like the dashboards' bar.
 *
 * The bundle runs without a server (a file, the docs, an iframe), so nothing
 * here reads one: the credit's wordmark is the inlined logo, and the rose is
 * the bundled custom element.
 */
import React from 'react';
import { Tooltip } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import { BookOpen, ChevronRight, Moon, SquarePen, Sun } from 'lucide-react';

import DepictioRose from '../components/rose/DepictioRose';
import { LOGO_SRC } from './shared';
import { currentCatalogTheme, setCatalogTheme } from './siteTheme';

/** depictio's hairline stroke for chrome glyphs (glass/icons.tsx). */
const STROKE = 1.6;

export const DOCS_URL = 'https://depictio.github.io/depictio-docs/stable/catalog/';
export const CATALOG_SOURCE_URL = 'https://github.com/depictio/depictio/tree/main/depictio/catalog';
export const TOOL_STUDIO_URL = 'https://depictio.github.io/depictio-tool-studio/';

/** A key of the top bar: the dashboards' `hy-key--top`, named by a tooltip. */
function TopKey({
  label,
  href,
  className,
  children,
}: {
  label: string;
  href: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Tooltip label={label} withArrow openDelay={250}>
      <a
        className={`hy-key hy-key--top${className ? ` ${className}` : ''}`}
        href={href}
        target="_blank"
        rel="noreferrer"
        aria-label={label}
      >
        {children}
      </a>
    </Tooltip>
  );
}

/** The rose, still at rest and opening into petals on hover, as in the app's bar. */
function BrandRose({ size, label }: { size: number; label: string }) {
  const [hovered, setHovered] = React.useState(false);
  return (
    <span
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ display: 'inline-flex' }}
    >
      <DepictioRose mode={hovered ? 'petals' : 'logo'} size={size} label={label} />
    </span>
  );
}

/** Light/dark switch. Only on the catalog site opened on its own: the
 *  single-file gallery has its theme baked in, and inside the docs' iframe the
 *  docs own the theme and pass it as `?theme=`. */
function ThemeKey() {
  const g = (window as { __CATALOG_PREVIEW__?: { lazyOutputs?: boolean } }).__CATALOG_PREVIEW__;
  let framed = false;
  try {
    framed = window.self !== window.top;
  } catch {
    framed = true;
  }
  if (!g?.lazyOutputs || framed) return null;
  const dark = currentCatalogTheme() === 'dark';
  const label = dark ? 'Switch to light theme' : 'Switch to dark theme';
  return (
    <Tooltip label={label} withArrow openDelay={250}>
      <button
        type="button"
        className="hy-key hy-key--top"
        aria-label={label}
        data-testid="catalog-theme-toggle"
        onClick={() => setCatalogTheme(dark ? 'light' : 'dark')}
      >
        {dark ? (
          <Sun size={21} strokeWidth={STROKE} aria-hidden />
        ) : (
          <Moon size={21} strokeWidth={STROKE} aria-hidden />
        )}
      </button>
    </Tooltip>
  );
}

export default function CatalogHeader({
  context,
  onHome,
  extras,
}: {
  /** Where the reader is, after "Tools catalog": the counts, or an output. */
  context?: React.ReactNode;
  /** Makes the rose and "Tools catalog" lead back to the catalog. */
  onHome?: () => void;
  /** Controls of the page itself (the view switch), before the keys. */
  extras?: React.ReactNode;
}) {
  const compact = useMediaQuery('(max-width: 47.99em)') ?? false;
  const markSize = compact ? 28 : 34;
  const home = (e: React.MouseEvent) => {
    e.preventDefault();
    onHome?.();
  };

  return (
    <header
      className={`hy-top cp-hy-top${compact ? ' hy-top--compact' : ''}`}
      data-testid="catalog-header"
    >
      {onHome ? (
        <Tooltip label="All tools" withArrow openDelay={400}>
          <a
            href="#"
            className="hy-top-brand hy-top-brand--mark"
            onClick={home}
            aria-label="Back to the catalog"
          >
            <BrandRose size={markSize} label="" />
          </a>
        </Tooltip>
      ) : (
        <span className="hy-top-brand hy-top-brand--mark">
          <BrandRose size={markSize} label="depictio" />
        </span>
      )}
      <span className="hy-top-rule" aria-hidden />
      <div className={`hy-top-title${context ? '' : ' hy-top-title--solo'}`}>
        {onHome ? (
          <a href="#" className="hy-top-dash cp-top-home" onClick={home}>
            Tools catalog
          </a>
        ) : (
          <span className="hy-top-dash">Tools catalog</span>
        )}
        {context && (
          <>
            <ChevronRight className="hy-top-chev" size={16} strokeWidth={2} aria-hidden />
            <span className="hy-top-tab">{context}</span>
          </>
        )}
      </div>
      <span className="hy-flex" />
      {extras && <div className="cp-top-extras">{extras}</div>}
      {!compact && (
        <span className="hy-top-powered">
          <a
            className="cp-powered"
            href="https://depictio.github.io/depictio-docs/"
            target="_blank"
            rel="noopener noreferrer"
          >
            <span>Powered by</span>
            <img src={LOGO_SRC} alt="Depictio" height={20} />
          </a>
        </span>
      )}
      <div className="hy-top-keys">
        <ThemeKey />
        <TopKey label="Add a tool in Tool Studio" href={TOOL_STUDIO_URL}>
          <SquarePen size={21} strokeWidth={STROKE} aria-hidden />
        </TopKey>
        <TopKey label="Documentation" href={DOCS_URL} className="cp-key-wide">
          <BookOpen size={21} strokeWidth={STROKE} aria-hidden />
        </TopKey>
        <TopKey label="Catalog source on GitHub" href={CATALOG_SOURCE_URL} className="cp-key-wide">
          <Icon icon="mdi:github" width={21} height={21} aria-hidden />
        </TopKey>
      </div>
    </header>
  );
}
