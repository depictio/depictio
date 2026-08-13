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
 * the sidebar becomes a paper bottom bar and the top bar turns compact.
 * The layout is CSS only (pages.css), so nothing re-renders on resize.
 */
import React from 'react';
import { MantineThemeContext, Tooltip, useMantineTheme } from '@mantine/core';
import type { MantineTheme } from '@mantine/core';
import { BRAND_PALETTES, brandAccent, useBranding } from 'depictio-react-core';
import {
  ChevronRight,
  Compass,
  FolderKanban,
  Globe,
  Info,
  LayoutDashboard,
  LogIn,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  Sun,
  UserRound,
  UsersRound,
  type LucideIcon,
} from 'lucide-react';

import BrandLogo from '../../../BrandLogo';
import PoweredBy from '../../../PoweredBy';
import { useBrandLogoMode } from '../../../useBrandLogoMode';
import { useAppNavEntries, type SidebarSection } from '../../../AppSidebar';
import { useColorScheme } from '../../../../hooks/useColorScheme';
import { SIGN_IN_PATH, rememberHere } from '../../../../auth/guestSignIn';
import { useCurrentUser } from '../../../../hooks/useCurrentUser';
import { useGuestSignIn } from '../../../../hooks/useGuestSignIn';
import { AvatarPicture, useAccountIdentity } from '../../../account';
import { ServerInfoPopover, UpdateDot } from '../../../server';
import { useServerStatus } from '../../../../hooks/useServerStatus';
import { usePageMark } from './useGlassPages';
import './pages.css';

export const STROKE = 1.6;

/** One Lucide glyph per section, in the Glass hairline stroke. */
export const SECTION_ICON: Record<SidebarSection, LucideIcon> = {
  dashboards: LayoutDashboard,
  projects: FolderKanban,
  groups: UsersRound,
  admin: ShieldCheck,
  about: Info,
  profile: UserRound,
};

/**
 * The section's Mantine palette: its icon ink, the active row's tick and, on
 * Dashboards and Projects, every primary control of the page. The two take
 * the logo's own petals (orange, teal) unless the instance brand sets its
 * tertiary / secondary colour, which then wins.
 */
export function useSectionPalettes(): Record<SidebarSection, string> {
  const brand = useBranding();
  return React.useMemo(
    () => ({
      dashboards: brandAccent(brand, 'tertiary', 'logoOrange'),
      projects: brandAccent(brand, 'secondary', 'logoTeal'),
      groups: 'grape',
      admin: BRAND_PALETTES.primary,
      about: 'gray',
      profile: BRAND_PALETTES.primary,
    }),
    [brand],
  );
}

const SECTION_LABEL: Record<SidebarSection, string> = {
  dashboards: 'Dashboards',
  projects: 'Projects',
  groups: 'Groups',
  admin: 'Administration',
  about: 'About',
  profile: 'Account settings',
};

/** Sections whose page controls wear the section's colour, not the primary. */
const OWN_TONE = new Set<SidebarSection>(['dashboards', 'projects']);

const PRIMARY_VARS = [
  ...Array.from({ length: 10 }, (_, i) => String(i)),
  'filled',
  'filled-hover',
  'light',
  'light-hover',
  'light-color',
] as const;

/**
 * Makes `palette` the primary colour of everything the page renders: a theme
 * for the controls that resolve `theme.primaryColor`, and the root
 * `--mantine-primary-color-*` variables for those that read them (portals
 * included, which is why they go on <html>).
 */
function useSectionTone(section: SidebarSection, palette: string): MantineTheme {
  const theme = useMantineTheme();
  const own = OWN_TONE.has(section);
  React.useEffect(() => {
    if (!own) return undefined;
    const root = document.documentElement.style;
    for (const v of PRIMARY_VARS) {
      root.setProperty(`--mantine-primary-color-${v}`, `var(--mantine-color-${palette}-${v})`);
    }
    return () => {
      for (const v of PRIMARY_VARS) root.removeProperty(`--mantine-primary-color-${v}`);
    };
  }, [own, palette]);
  return React.useMemo(
    () => (own ? { ...theme, primaryColor: palette } : theme),
    [own, palette, theme],
  );
}

const tint = (palette: string) =>
  ({ ['--gp-tint' as string]: `var(--mantine-color-${palette}-filled)` }) as React.CSSProperties;

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
        <I size={20} strokeWidth={STROKE} aria-hidden />
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

/** The reader: initials (or a figure) linking straight to Account settings. */
export const ProfileKey: React.FC = () => {
  const who = useAccountIdentity();
  if (who.loading) return <span className="gp-avatar gp-avatar--idle" aria-hidden />;
  if (who.signIn) {
    return (
      <Tooltip label="Sign in" withArrow>
        <a href={SIGN_IN_PATH} onClick={rememberHere} className="gp-avatar" aria-label="Sign in">
          <LogIn size={18} strokeWidth={1.9} aria-hidden />
        </a>
      </Tooltip>
    );
  }
  return (
    <Tooltip label="Account settings" withArrow>
      <a href="/profile" className="gp-avatar" aria-label="Account settings" data-testid="profile-key">
        {who.avatarUrl ? (
          <AvatarPicture src={who.avatarUrl} />
        ) : (
          (who.mono ?? <UserRound size={18} strokeWidth={1.9} aria-hidden />)
        )}
      </a>
    </Tooltip>
  );
};

/* -------------------------------------------------------------- top bar */

/** Home: the real depictio logo (the rose's petals move on hover), or the instance's
 *  own logo. */
export const HomeMark: React.FC<{ height: number; href?: string }> = ({ height, href = '/dashboards' }) => {
  const mode = useBrandLogoMode();
  if (mode === 'none') return null;
  return (
    <Tooltip label="All dashboards" withArrow openDelay={400}>
      <a href={href} className="gp-brand" aria-label="depictio: all dashboards">
        <BrandLogo height={height} width="auto" testId="glass-pages-logo" />
      </a>
    </Tooltip>
  );
};

const TopBar: React.FC<{ section: SidebarSection; crumbs: Crumb[] }> = ({ section, crumbs }) => {
  const Icon = SECTION_ICON[section];
  const palettes = useSectionPalettes();
  const trail: Crumb[] = [{ label: SECTION_LABEL[section], href: `/${section === 'admin' ? 'admin' : section}` }, ...crumbs];
  return (
    <header className="gp-top">
      <HomeMark height={44} />
      <span className="gp-top-rule" aria-hidden />
      <nav className="gp-trail" aria-label="You are here">
        <span className="gp-trail-icon" style={tint(palettes[section])} aria-hidden>
          <Icon size={20} strokeWidth={1.8} />
        </span>
        {trail.map((c, i) => {
          const last = i === trail.length - 1;
          return (
            <React.Fragment key={`${c.label}-${i}`}>
              {i > 0 && <ChevronRight className="gp-trail-chev" size={16} strokeWidth={2} aria-hidden />}
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
  const guest = useGuestSignIn();
  const online = status === 'online';
  const main = online ? 'Online' : status === 'unknown' ? 'Checking server' : 'Server offline';
  const ver = online && version ? `v${version}` : null;
  const label = ver ? `${main} · ${ver}` : main;
  const mode = isDemoMode ? 'Demo mode' : isPublicMode ? 'Public mode' : isSingleUserMode ? 'Single user mode' : null;
  const ModeIcon = isDemoMode ? Compass : isPublicMode ? Globe : UserRound;
  // Folded to the rail, the dot stands for both lines: they move to its tooltip.
  const tip = mode ? `${label} · ${mode}` : label;
  return (
    <div className="gp-side-foot">
      {/* The status is also the way into the server info popover: version,
          links and, for an admin, the update notice. */}
      <ServerInfoPopover tooltip={open ? null : tip}>
        {({ label: named, updateDot }) => (
          <button
            type="button"
            className="gp-status"
            data-state={status}
            aria-label={named(label)}
            data-testid="gp-status"
          >
            <span className="gp-status-dot" aria-hidden />
            <span className="gp-status-text">
              <span>{main}</span>
              {ver && <span className="gp-status-ver">{ver}</span>}
            </span>
            {updateDot && <UpdateDot />}
          </button>
        )}
      </ServerInfoPopover>
      {mode && open && guest.available ? (
        // A guest on a public instance: the mode line is also the way to sign in.
        <a href={SIGN_IN_PATH} onClick={rememberHere} className="gp-mode gp-mode--link" data-testid="gp-mode-sign-in">
          <ModeIcon size={14} strokeWidth={STROKE} aria-hidden />
          {mode} · Sign in
        </a>
      ) : (
        mode &&
        open && (
          <span className="gp-mode">
            <ModeIcon size={14} strokeWidth={STROKE} aria-hidden />
            {mode}
          </span>
        )
      )}
    </div>
  );
};

const Sidebar: React.FC<{ section: SidebarSection; open: boolean; onToggle: () => void }> = ({
  section,
  open,
  onToggle,
}) => {
  const entries = useAppNavEntries();
  const palettes = useSectionPalettes();
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
              <PanelLeftClose size={20} strokeWidth={STROKE} aria-hidden />
            ) : (
              <PanelLeftOpen size={20} strokeWidth={STROKE} aria-hidden />
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
                style={tint(palettes[key])}
              >
                <span className="gp-row-icon">
                  <Icon size={20} strokeWidth={STROKE} aria-hidden />
                </span>
                <span className="gp-row-label">{entry.label}</span>
              </a>
            </Tooltip>
          );
        })}
      </div>
      <span className="gp-flex-col" />
      <StatusFoot open={open} />
    </nav>
  );
};

/** The phone's bottom bar: the same entries, icon over name. */
const PhoneBar: React.FC<{ section: SidebarSection }> = ({ section }) => {
  const entries = useAppNavEntries();
  const palettes = useSectionPalettes();
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
            style={tint(palettes[key])}
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
  const palettes = useSectionPalettes();
  const pageTheme = useSectionTone(section, palettes[section]);

  return (
    <MantineThemeContext.Provider value={pageTheme}>
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
            <span className="gp-head-icon" style={tint(palettes[section])} aria-hidden>
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
    </MantineThemeContext.Provider>
  );
};

export default GlassPage;
