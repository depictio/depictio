import React from 'react';
import { Tooltip } from '@mantine/core';
import { useBrandScopeAttributes } from 'depictio-react-core';
import {
  ArrowLeft,
  BookOpenText,
  ChevronRight,
  LogIn,
  Moon,
  Sun,
  UserRound,
  X,
  type LucideIcon,
} from 'lucide-react';

import DepictioRose from '../../../components/rose/DepictioRose';
import BrandLogo from '../../BrandLogo';
import { useBrandLogoMode } from '../../useBrandLogoMode';
import { useColorScheme } from '../../../hooks/useColorScheme';
import { getEmbedColorScheme } from '../../../lib/embedColorScheme';
import { useCurrentUser } from '../../../hooks/useCurrentUser';
import type { HeaderModel } from '../../Header';
import type { TabNavModel } from '../../Sidebar';
import { cn } from './cn';
import { STROKE } from './icons';

/* -------------------------------------------------------------------- tile */

interface TileProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  icon: LucideIcon;
  label: string;
  /** A rail tile, a top bar key (icon), or a labelled sheet row. */
  place?: 'rail' | 'top' | 'sheet';
}

/** A control that is not a chrome action (the theme switch), drawn like the
 *  rail's own keys. */
export const Tile = React.forwardRef<HTMLButtonElement, TileProps>(function Tile(
  { icon: I, label, place = 'rail', className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      data-hy-place={place}
      data-hy-look="icon"
      className={cn(
        'hy-key hy-key--icon',
        place === 'sheet'
          ? 'hy-key--sheet hy-key--labelled'
          : place === 'top'
            ? 'hy-key--top hy-key--square'
            : 'hy-key--rail hy-key--square',
        className,
      )}
      {...rest}
    >
      <I size={place === 'sheet' ? 18 : place === 'top' ? 18 : 20} strokeWidth={STROKE} aria-hidden className="hy-glyph" />
      {place === 'sheet' && <span className="hy-key-label">{label}</span>}
    </button>
  );
});

/* -------------------------------------------------------------- rail tabs */

const tabTint = (color: string) =>
  ({
    ['--gl-tab-color' as string]: `var(--mantine-color-${color}-5)`,
    ['--gl-tab-ink' as string]: `light-dark(var(--mantine-color-${color}-7), var(--mantine-color-${color}-3))`,
  }) as React.CSSProperties;

/** The tabs as icons, one tile each, a short rule between groups. */
export const RailTabs: React.FC<{ nav: TabNavModel }> = ({ nav }) => (
  <>
    {nav.sections.map((section, i) => (
      <React.Fragment key={section.group ?? `__ungrouped_${i}`}>
        {i > 0 && <div className="hy-sep" role="separator" aria-label={section.group ?? undefined} />}
        {section.items.map((tab) => (
          <Tooltip
            key={tab.id}
            label={
              section.group ? (
                <span>
                  <span className="hy-tip-eyebrow">{section.group}</span>
                  {tab.label}
                </span>
              ) : (
                tab.label
              )
            }
            withArrow
            openDelay={150}
          >
            <a
              href={tab.href}
              className="hy-tab"
              data-active={tab.active || undefined}
              aria-current={tab.active ? 'page' : undefined}
              aria-label={tab.label}
              style={tabTint(tab.color)}
            >
              {tab.icon}
            </a>
          </Tooltip>
        ))}
      </React.Fragment>
    ))}
  </>
);

/** The tabs with their names and groups: the Tabs drawer, the phone sheet. */
export const TabList: React.FC<{
  nav: TabNavModel;
  onNavigate?: () => void;
  /** The Guide and the way home as a last section (the phone sheet); the
   *  desktop sidebar has rows of its own for both. */
  tools?: boolean;
}> = ({ nav, onNavigate, tools = true }) => (
  <nav className="hy-tablist" aria-label="Tabs">
    {nav.sections.map((section, i) => (
      <div key={section.group ?? `__ungrouped_${i}`} className="hy-tablist-section">
        {section.group && <div className="hy-eyebrow hy-tablist-group">{section.group}</div>}
        {section.items.map((tab) => (
          <a
            key={tab.id}
            href={tab.href}
            className="hy-tablist-item"
            data-active={tab.active || undefined}
            aria-current={tab.active ? 'page' : undefined}
            onClick={onNavigate}
            style={tabTint(tab.color)}
          >
            <span className="hy-tablist-icon">{tab.icon}</span>
            <span className="hy-tablist-label">{tab.label}</span>
          </a>
        ))}
      </div>
    ))}
    {tools && <div className="hy-tablist-section">
      {nav.guide && (
        <a
          href={nav.guide.href}
          onClick={(e) => {
            nav.guide?.onClick(e);
            onNavigate?.();
          }}
          className="hy-tablist-item hy-tablist-quiet"
          data-active={nav.guide.open || undefined}
        >
          <span className="hy-tablist-icon">
            <BookOpenText size={17} strokeWidth={1.9} aria-hidden />
          </span>
          <span className="hy-tablist-label">Guide</span>
        </a>
      )}
      <a href={nav.backHref} className="hy-tablist-item hy-tablist-quiet">
        <span className="hy-tablist-icon">
          <ArrowLeft size={16} strokeWidth={1.9} aria-hidden />
        </span>
        <span className="hy-tablist-label">All dashboards</span>
      </a>
    </div>}
  </nav>
);

/* ------------------------------------------------------------- side rows */

/** A sidebar row that is not a chrome action (the Guide, the way home, the
 *  collapse switch): icon and name, the name folding away with the sidebar,
 *  a tooltip standing in for it then. */
export const SideRow: React.FC<{
  icon: React.ReactNode;
  label: string;
  /** The sidebar shows names. */
  open: boolean;
  href?: string;
  onClick?: (e: React.MouseEvent<HTMLAnchorElement>) => void;
  active?: boolean;
  tooltip?: string;
  testId?: string;
  ariaExpanded?: boolean;
}> = ({ icon, label, open, href, onClick, active, tooltip, testId, ariaExpanded }) => {
  const body = (
    <>
      <span className="hy-row-icon">{icon}</span>
      <span className="hy-row-label">{label}</span>
    </>
  );
  const shared = {
    className: 'hy-row',
    'data-active': active || undefined,
    'aria-label': label,
    'data-testid': testId,
  };
  const el = href ? (
    <a href={href} onClick={onClick} {...shared}>
      {body}
    </a>
  ) : (
    <button
      type="button"
      onClick={onClick as unknown as React.MouseEventHandler<HTMLButtonElement>}
      aria-expanded={ariaExpanded} {...shared}>
      {body}
    </button>
  );
  return (
    <Tooltip label={tooltip ?? label} withArrow openDelay={200} disabled={open}>
      {el}
    </Tooltip>
  );
};

/* ------------------------------------------------------- theme and profile */

export const ThemeTile: React.FC<{ place?: 'rail' | 'top' | 'sheet' }> = ({ place = 'rail' }) => {
  const { colorScheme, setColorScheme } = useColorScheme();
  // Inside a dashboard BrandScope the nested provider's own scheme can drift
  // from the app's (it never sees a borrowed ?theme=); the scope attributes
  // carry the app-level scheme, which is the one on screen.
  const scope = useBrandScopeAttributes();
  const scoped = scope !== null;
  const dark = (scope ? scope['data-mantine-color-scheme'] : colorScheme) === 'dark';
  const label = dark ? 'Switch to light theme' : 'Switch to dark theme';
  const flip = () => {
    const next = dark ? 'light' : 'dark';
    setColorScheme(next);
    // A dashboard with its own brand runs inside a nested MantineProvider
    // (BrandScope) whose setColorScheme never reaches <html> or the app-level
    // provider, so the app provider has to be told separately.
    if (!scoped) return;
    if (getEmbedColorScheme()) {
      // Borrowed scheme (?theme= or an embed): the app manager ignores every
      // update while borrowing, so carry the choice in the URL and reload.
      const url = new URL(window.location.href);
      if (url.searchParams.has('theme') || !/(^#|&)theme=/.test(url.hash)) {
        url.searchParams.set('theme', next);
      } else {
        const hash = new URLSearchParams(url.hash.slice(1));
        hash.set('theme', next);
        url.hash = hash.toString();
      }
      window.location.replace(url.toString());
      return;
    }
    // Mantine's root manager listens for `storage` events on its key, so
    // replaying the write as one lets the app provider follow.
    try {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: 'mantine-color-scheme-value',
          newValue: next,
          storageArea: window.localStorage,
        }),
      );
    } catch {
      // storage disabled: the scoped toggle still applies inside the dashboard
    }
  };
  const tile = (
    <Tile
      place={place}
      icon={dark ? Sun : Moon}
      label={place === 'sheet' ? (dark ? 'Light theme' : 'Dark theme') : label}
      onClick={flip}
      data-testid="theme-toggle"
    />
  );
  return place !== 'sheet' ? (
    <Tooltip label={label} withArrow openDelay={300}>
      {tile}
    </Tooltip>
  ) : (
    tile
  );
};

function initials(email: string): string {
  const local = (email.split('@')[0] || email).replace(/[^a-zA-Z0-9._-]/g, '');
  const parts = local.split(/[._-]+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function useProfile() {
  const { user, authMode, isPublicMode, isDemoMode, loading } = useCurrentUser();
  const signIn = !loading && !user && authMode === 'standard' && !isPublicMode && !isDemoMode;
  const name =
    authMode === 'single_user'
      ? 'Single user mode'
      : authMode === 'unauthenticated'
        ? 'Unauthenticated mode'
        : user
          ? user.email
          : 'Guest';
  return {
    signIn,
    name,
    mono: user && authMode === 'standard' ? initials(user.email) : null,
  };
}

/** The reader: initials (or a figure) that open the profile page. */
export const ProfileTile: React.FC = () => {
  const p = useProfile();
  if (p.signIn) {
    return (
      <Tooltip label="Sign in" withArrow>
        <a href="/auth/login" className="hy-avatar" aria-label="Sign in">
          <LogIn size={16} strokeWidth={1.9} aria-hidden />
        </a>
      </Tooltip>
    );
  }
  return (
    <Tooltip label={`Profile: ${p.name}`} withArrow openDelay={300}>
      <a href="/profile" className="hy-avatar" aria-label={`Profile: ${p.name}`}>
        {p.mono ?? <UserRound size={16} strokeWidth={1.9} aria-hidden />}
      </a>
    </Tooltip>
  );
};

/** The same, as rows of the phone's More sheet. */
export const ProfileRows: React.FC = () => {
  const p = useProfile();
  if (p.signIn) {
    return (
      <a href="/auth/login" className="hy-sheet-link">
        <LogIn size={18} strokeWidth={STROKE} aria-hidden />
        <span>Sign in</span>
      </a>
    );
  }
  return (
    <>
      <a href="/profile" className="hy-sheet-link">
        <span className="hy-avatar hy-avatar--sm" aria-hidden>
          {p.mono ?? <UserRound size={14} strokeWidth={1.9} />}
        </span>
        <span className="hy-sheet-link-text">{p.name}</span>
      </a>
    </>
  );
};

/* ----------------------------------------------------------------- top bar */

/** Home, as the brand in scope draws it. The stock depictio brand is drawn
 *  here, not from the raster: the rose in its own colours and the wordmark
 *  in Virgil, inked by the theme so it reads on light and dark alike. An
 *  instance's (or dashboard's) own logo goes through `BrandLogo`, which picks
 *  its dark variant. */
const HomeMark: React.FC<{ home: string; height: number }> = ({ home, height }) => {
  const mode = useBrandLogoMode();
  const [fan, setFan] = React.useState(false);
  if (mode === 'none') return null;
  return (
    <Tooltip label="All dashboards" withArrow openDelay={400}>
      <a
        href={home}
        className="hy-top-brand"
        aria-label="depictio: all dashboards"
        onMouseEnter={() => setFan(true)}
        onMouseLeave={() => setFan(false)}
        onFocus={() => setFan(true)}
        onBlur={() => setFan(false)}
      >
        {mode === 'inherit' ? (
          <>
            <DepictioRose mode={fan ? 'fan' : 'logo'} size={height + 4} label="" />
            <span className="hy-wordmark" style={{ fontSize: height }}>
              depictio
            </span>
          </>
        ) : (
          <BrandLogo height={height} width="auto" testId="glass-logo" />
        )}
      </a>
    </Tooltip>
  );
};

/** The top bar's identity and place: the depictio logo and wordmark (or the
 *  instance's own logo), then where the reader is, dashboard and tab, with
 *  the load indicator. `after` takes the bar's keys on the right. */
export const TopBar: React.FC<{
  model: HeaderModel;
  home: string;
  compact?: boolean;
  /** The reader's compact page width: a lower bar. */
  dense?: boolean;
  editing?: boolean;
  after?: React.ReactNode;
}> = ({ model, home, compact, dense, editing, after }) => (
  <header className={cn('hy-top', compact && 'hy-top--compact')}>
    <HomeMark home={home} height={compact ? 20 : dense ? 22 : 25} />
    <span className="hy-top-rule" aria-hidden />
    <div
      className="hy-top-title dc-header"
      data-tour-id="header-title"
      style={{ ['--gl-title-color' as string]: model.titleColor } as React.CSSProperties}
    >
      {model.dashboardName && (
        <span className="hy-top-dash dc-header-title-parent" title={model.dashboardName}>
          {model.dashboardName}
        </span>
      )}
      {model.dashboardName && (
        <ChevronRight className="hy-top-chev" size={15} strokeWidth={2} aria-hidden />
      )}
      {model.tabIcon && <span className="hy-top-icon">{model.tabIcon}</span>}
      <h1 className="hy-top-tab dc-header-title" title={model.titleText}>
        <span className="dc-header-title-tab">{model.activeLabel}</span>
      </h1>
      {model.titleExtras && (
        <span className="hy-top-extras dc-header-title-extras">{model.titleExtras}</span>
      )}
    </div>
    {editing && <span className="hy-top-mode">Editing</span>}
    <span className="hy-flex" />
    {/* "Powered by depictio", when an instance logo has taken the left. */}
    {!compact && <span className="hy-top-powered">{model.poweredBy}</span>}
    {after}
  </header>
);

/* ------------------------------------------------------------ drawer head */

export const DrawerHead: React.FC<{
  title: string;
  meta?: React.ReactNode;
  onClose: () => void;
}> = ({ title, meta, onClose }) => (
  <div className="hy-drawer-head">
    <span className="hy-drawer-title">{title}</span>
    {meta}
    <span className="hy-flex" />
    <Tooltip label="Close panel (Esc)" withArrow openDelay={300}>
      <button type="button" className="hy-close" aria-label={`Close ${title.toLowerCase()}`} onClick={onClose}>
        <X size={16} strokeWidth={2} aria-hidden />
      </button>
    </Tooltip>
  </div>
);
