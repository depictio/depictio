/**
 * The Glass page shell: the management pages (dashboards, projects, admin,
 * about, profile) in the language of the Glass dashboard chrome.
 *
 *  ┌──────────────────────────────────────────────────────────────┐
 *  │ ✿ depictio │ ▣ Projects › TREC 2024        Powered by  ☾ (TW) │ top bar
 *  ├──────────────┬───────────────────────────────────────────────┤
 *  │ WORKSPACE  ⇤ │  ▣  Projects                   [⌕][⚲][↗] [+ New]│ page head
 *  │ ▣ Dashboards │     The data behind your dashboards.          │
 *  │ ▣ Projects   │  ┌──────────────── glass card ───────────────┐│
 *  │ ⚙ Admin      │  │                                           ││
 *  │ ? About      │  └───────────────────────────────────────────┘│
 *  │ ──────────── │                                               │
 *  │ ● Online     │                                               │
 *  └──────────────┴───────────────────────────────────────────────┘
 *
 * The sidebar navigates and folds to an icon rail (its own key at its head;
 * the logo only goes home). The top bar says where the reader is. Below `sm`
 * the sidebar becomes a frosted bottom bar and the top bar turns compact.
 * The layout is CSS only (pages.css), so nothing re-renders on resize.
 */
import React from 'react';
import { Menu, Tooltip } from '@mantine/core';
import { useReducedMotion } from 'motion/react';
import {
  ChevronRight,
  Compass,
  FolderKanban,
  Info,
  LayoutDashboard,
  LogIn,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  Sun,
  UserRound,
  type LucideIcon,
} from 'lucide-react';

import DepictioRose from '../../../../components/rose/DepictioRose';
import BrandLogo from '../../../BrandLogo';
import PoweredBy from '../../../PoweredBy';
import { useBrandLogoMode } from '../../../useBrandLogoMode';
import { useAppNavEntries, type SidebarSection } from '../../../AppSidebar';
import { useColorScheme } from '../../../../hooks/useColorScheme';
import { useCurrentUser } from '../../../../hooks/useCurrentUser';
import { useServerStatus } from '../../../../hooks/useServerStatus';
import { dispatchWalkthroughRestart } from '../../../../walkthrough';
import { usePageMark } from './useGlassPages';
import './pages.css';

export const STROKE = 1.6;

/** One Lucide glyph per section, in the Glass hairline stroke. */
export const SECTION_ICON: Record<SidebarSection, LucideIcon> = {
  dashboards: LayoutDashboard,
  projects: FolderKanban,
  admin: ShieldCheck,
  about: Info,
  profile: UserRound,
  'cli-agents': Compass,
};

/** The section's hue: its icon ink and the active row's tick. */
const SECTION_TINT: Record<SidebarSection, string> = {
  dashboards: 'var(--depictio-brand-tertiary)',
  projects: 'var(--depictio-brand-secondary)',
  admin: 'var(--depictio-brand-primary)',
  about: 'var(--mantine-color-gray-6)',
  profile: 'var(--depictio-brand-primary)',
  'cli-agents': 'var(--mantine-color-violet-6)',
};

const SECTION_LABEL: Record<SidebarSection, string> = {
  dashboards: 'Dashboards',
  projects: 'Projects',
  admin: 'Administration',
  about: 'About',
  profile: 'Profile',
  'cli-agents': 'CLI agents',
};

const tint = (section: SidebarSection) =>
  ({ ['--gp-tint' as string]: SECTION_TINT[section] }) as React.CSSProperties;

const SIDE_KEY = 'depictio-glass-pages-sidebar';

function readOpen(): boolean {
  try {
    return localStorage.getItem(SIDE_KEY) !== '0';
  } catch {
    return true;
  }
}

export interface Crumb {
  label: string;
  href?: string;
}

export interface GlassPageProps {
  section: SidebarSection;
  /** The page heading. */
  title: React.ReactNode;
  /** One line under the heading: what the page is for. */
  description?: React.ReactNode;
  /** The trail after the section in the top bar (the section links home). */
  crumbs?: Crumb[];
  /** The page's own actions, right of the heading (primary last). */
  actions?: React.ReactNode;
  /** Attributes for the heading (a walkthrough anchor). */
  titleProps?: Record<string, string>;
  children: React.ReactNode;
}

/* ----------------------------------------------------------------- keys */

/** An icon key with a tooltip: the top bar's and the sidebar's controls. */
export const GlassKey = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; icon: LucideIcon; tip?: string }
>(function GlassKey({ label, icon: I, tip, className, ...rest }, ref) {
  return (
    <Tooltip label={tip ?? label} withArrow openDelay={250}>
      <button
        ref={ref}
        type="button"
        aria-label={label}
        className={className ? `gp-key ${className}` : 'gp-key'}
        {...rest}
      >
        <I size={18} strokeWidth={STROKE} aria-hidden />
      </button>
    </Tooltip>
  );
});

const ThemeKey: React.FC = () => {
  const { colorScheme, toggle } = useColorScheme();
  const dark = colorScheme === 'dark';
  return (
    <GlassKey
      label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
      icon={dark ? Sun : Moon}
      onClick={toggle}
      data-testid="theme-toggle"
    />
  );
};

function initials(email: string): string {
  const local = (email.split('@')[0] || email).replace(/[^a-zA-Z0-9._-]/g, '');
  const parts = local.split(/[._-]+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

/** The reader: initials (or a figure) opening Profile and the tour. */
const ProfileKey: React.FC = () => {
  const { user, authMode, isPublicMode, isDemoMode, loading } = useCurrentUser();
  if (loading) return <span className="gp-avatar gp-avatar--idle" aria-hidden />;
  if (!user && authMode === 'standard' && !isPublicMode && !isDemoMode) {
    return (
      <Tooltip label="Sign in" withArrow>
        <a href="/auth/login" className="gp-avatar" aria-label="Sign in">
          <LogIn size={16} strokeWidth={1.9} aria-hidden />
        </a>
      </Tooltip>
    );
  }
  const name =
    authMode === 'single_user'
      ? 'Single user mode'
      : authMode === 'unauthenticated'
        ? 'Unauthenticated mode'
        : (user?.email ?? 'Guest');
  const mono = user && authMode === 'standard' ? initials(user.email) : null;
  const tourId: 'public' | 'builder' = isPublicMode || isDemoMode ? 'public' : 'builder';
  return (
    <Menu position="bottom-end" width={240} withArrow={false} offset={8}>
      <Menu.Target>
        <button type="button" className="gp-avatar" aria-label={`Account: ${name}`}>
          {mono ?? <UserRound size={16} strokeWidth={1.9} aria-hidden />}
        </button>
      </Menu.Target>
      <Menu.Dropdown>
        <div className="gp-menu-who">
          <span className="gp-menu-who-name">{name}</span>
          {user?.is_admin && <span className="gp-menu-who-role">Administrator</span>}
        </div>
        <Menu.Divider />
        <Menu.Item component="a" href="/profile" leftSection={<UserRound size={16} strokeWidth={STROKE} />}>
          Profile
        </Menu.Item>
        <Menu.Item
          leftSection={<Compass size={16} strokeWidth={STROKE} />}
          onClick={() => dispatchWalkthroughRestart(tourId)}
        >
          {tourId === 'public' ? 'Take the demo tour' : 'Take the builder tour'}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
};

/* -------------------------------------------------------------- top bar */

/** Home: the rose in its own colours and the wordmark in Virgil, or the
 *  instance's own logo. Hovering fans the rose out. */
export const HomeMark: React.FC<{ height: number; href?: string }> = ({ height, href = '/dashboards' }) => {
  const mode = useBrandLogoMode();
  const reduce = useReducedMotion();
  const [fan, setFan] = React.useState(false);
  if (mode === 'none') return null;
  const on = (v: boolean) => () => setFan(v && !reduce);
  return (
    <Tooltip label="All dashboards" withArrow openDelay={400}>
      <a
        href={href}
        className="gp-brand"
        aria-label="depictio: all dashboards"
        onMouseEnter={on(true)}
        onMouseLeave={on(false)}
        onFocus={on(true)}
        onBlur={on(false)}
      >
        {mode === 'inherit' ? (
          <>
            <DepictioRose mode={fan ? 'fan' : 'logo'} size={height + 4} label="" />
            <span className="gp-wordmark" style={{ fontSize: height }}>
              depictio
            </span>
          </>
        ) : (
          <BrandLogo height={height} width="auto" testId="glass-pages-logo" />
        )}
      </a>
    </Tooltip>
  );
};

const TopBar: React.FC<{ section: SidebarSection; crumbs: Crumb[] }> = ({ section, crumbs }) => {
  const Icon = SECTION_ICON[section];
  const trail: Crumb[] = [{ label: SECTION_LABEL[section], href: `/${section === 'admin' ? 'admin' : section}` }, ...crumbs];
  return (
    <header className="gp-top">
      <HomeMark height={24} />
      <span className="gp-top-rule" aria-hidden />
      <nav className="gp-trail" aria-label="You are here">
        <span className="gp-trail-icon" style={tint(section)} aria-hidden>
          <Icon size={16} strokeWidth={1.8} />
        </span>
        {trail.map((c, i) => {
          const last = i === trail.length - 1;
          return (
            <React.Fragment key={`${c.label}-${i}`}>
              {i > 0 && <ChevronRight className="gp-trail-chev" size={14} strokeWidth={2} aria-hidden />}
              {last || !c.href ? (
                <span className="gp-trail-here" aria-current={last ? 'page' : undefined} title={c.label}>
                  {c.label}
                </span>
              ) : (
                <a className="gp-trail-link" href={c.href} title={c.label}>
                  {c.label}
                </a>
              )}
            </React.Fragment>
          );
        })}
      </nav>
      <span className="gp-flex" />
      <span className="gp-top-powered">
        <PoweredBy />
      </span>
      <div className="gp-top-keys">
        <ThemeKey />
        <ProfileKey />
      </div>
    </header>
  );
};

/* -------------------------------------------------------------- sidebar */

const StatusFoot: React.FC<{ open: boolean }> = ({ open }) => {
  const { status, version } = useServerStatus();
  const { isPublicMode, isDemoMode, isSingleUserMode } = useCurrentUser();
  const online = status === 'online';
  const label = online ? (version ? `Online · v${version}` : 'Online') : status === 'unknown' ? 'Checking server' : 'Server offline';
  const mode = isDemoMode ? 'Demo mode' : isPublicMode ? 'Public mode' : isSingleUserMode ? 'Single user mode' : null;
  return (
    <div className="gp-side-foot">
      <Tooltip label={online ? 'Server online' : label} withArrow disabled={open} position="right">
        <div className="gp-status" data-state={status} aria-label={label}>
          <span className="gp-status-dot" aria-hidden />
          <span className="gp-status-text">{label}</span>
        </div>
      </Tooltip>
      {mode && open && <span className="gp-mode">{mode}</span>}
    </div>
  );
};

const Sidebar: React.FC<{ section: SidebarSection; open: boolean; onToggle: () => void }> = ({
  section,
  open,
  onToggle,
}) => {
  const entries = useAppNavEntries();
  return (
    <nav className="gp-side" aria-label="Main" data-testid="app-sidebar">
      <div className="gp-side-head">
        {open && <span className="gp-eyebrow">Workspace</span>}
        <span className="gp-flex" />
        <Tooltip label={open ? 'Collapse sidebar' : 'Expand sidebar'} withArrow openDelay={200} position="right">
          <button
            type="button"
            className="gp-fold"
            aria-label={open ? 'Collapse sidebar' : 'Expand sidebar'}
            aria-expanded={open}
            onClick={onToggle}
          >
            {open ? (
              <PanelLeftClose size={18} strokeWidth={STROKE} aria-hidden />
            ) : (
              <PanelLeftOpen size={18} strokeWidth={STROKE} aria-hidden />
            )}
          </button>
        </Tooltip>
      </div>
      <div className="gp-side-rows">
        {entries.map((entry) => {
          const key = entry.key as SidebarSection;
          const Icon = SECTION_ICON[key];
          const active = key === section;
          return (
            <Tooltip key={entry.href} label={entry.label} withArrow position="right" disabled={open} openDelay={150}>
              <a
                href={entry.href}
                className="gp-row"
                data-active={active || undefined}
                aria-current={active ? 'page' : undefined}
                aria-label={entry.label}
                style={tint(key)}
              >
                <span className="gp-row-icon">
                  <Icon size={19} strokeWidth={STROKE} aria-hidden />
                </span>
                <span className="gp-row-label">{entry.label}</span>
              </a>
            </Tooltip>
          );
        })}
      </div>
      <span className="gp-flex-col" />
      <div className="gp-rule" role="separator" />
      <StatusFoot open={open} />
    </nav>
  );
};

/** The phone's bottom bar: the same entries, icon over name. */
const PhoneBar: React.FC<{ section: SidebarSection }> = ({ section }) => {
  const entries = useAppNavEntries();
  return (
    <nav className="gp-tabbar" aria-label="Main">
      {entries.map((entry) => {
        const key = entry.key as SidebarSection;
        const Icon = SECTION_ICON[key];
        const active = key === section;
        return (
          <a
            key={entry.href}
            href={entry.href}
            className="gp-tabbar-key"
            data-active={active || undefined}
            aria-current={active ? 'page' : undefined}
            style={tint(key)}
          >
            <Icon size={20} strokeWidth={STROKE} aria-hidden />
            <span>{entry.key === 'admin' ? 'Admin' : entry.label}</span>
          </a>
        );
      })}
    </nav>
  );
};

/* ---------------------------------------------------------------- shell */

const GlassPage: React.FC<GlassPageProps> = ({
  section,
  title,
  description,
  crumbs = [],
  actions,
  titleProps,
  children,
}) => {
  usePageMark(section);
  const [open, setOpen] = React.useState(readOpen);
  const toggle = () =>
    setOpen((v) => {
      try {
        localStorage.setItem(SIDE_KEY, v ? '0' : '1');
      } catch {
        // The choice lasts for this page only.
      }
      return !v;
    });
  const Icon = SECTION_ICON[section];

  return (
    <div
      className="gp-shell"
      data-testid="app-shell"
      data-side={open ? 'open' : 'folded'}
      data-section={section}
    >
      <TopBar section={section} crumbs={crumbs} />
      <Sidebar section={section} open={open} onToggle={toggle} />
      <main className="gp-main">
        <div className="gp-page">
          <div className="gp-head">
            <span className="gp-head-icon" style={tint(section)} aria-hidden>
              <Icon size={22} strokeWidth={1.7} />
            </span>
            <div className="gp-head-text">
              <h1 className="gp-title" {...titleProps}>
                {title}
              </h1>
              {description && <p className="gp-desc">{description}</p>}
            </div>
            {actions && <div className="gp-head-actions">{actions}</div>}
          </div>
          {children}
        </div>
      </main>
      <PhoneBar section={section} />
    </div>
  );
};

export default GlassPage;
