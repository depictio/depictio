import React from 'react';
import { Box, Divider, Group, Loader, Menu, Title, useMantineColorScheme } from '@mantine/core';
import {
  BRAND_PALETTES,
  ChromeButton,
  ChromeButtonGroup,
  useBranding,
  useChromeStyle,
} from 'depictio-react-core';
import { Icon } from '@iconify/react';

import type { BrandTheme, DashboardData, DashboardSummary } from 'depictio-react-core';
import PoweredBy from './PoweredBy';
import { useFeedbackLink } from '../feedback';
import { searchShortcutLabel } from '../spotlight/shortcut';

/** True for path-like icon values (PNG/SVG file URLs) — these came from the
 *  Dash YAML and aren't valid Iconify names. */
function isImagePath(s: string | null | undefined): boolean {
  if (!s) return false;
  return /^(\/|https?:\/\/|data:)/.test(s) || /\.(png|svg|jpe?g|webp)$/i.test(s);
}

function isMultiqcIcon(path: string | null | undefined): boolean {
  if (!path) return false;
  return /\/assets\/images\/logos\/multiqc(\.png|_icon_(dark|white|color)\.svg)$/i.test(path);
}

/** Map any MultiQC logo path (legacy PNG or new SVGs) to the SPA-served
 *  themed SVG. Mirrors the same helper in Sidebar.tsx. */
function rewriteMultiqcIcon(path: string, theme: 'light' | 'dark'): string {
  if (!isMultiqcIcon(path)) return path;
  return theme === 'dark'
    ? '/dashboard/logos/multiqc_icon_white.svg'
    : '/dashboard/logos/multiqc_icon_dark.svg';
}

/** Dash precedence: `tab.tab_icon || tab.icon`, `tab.tab_icon_color || tab.icon_color`. */
function resolveTabIcon(tab: DashboardSummary | null | undefined): string | null {
  return (tab?.tab_icon || tab?.icon) ?? null;
}
function resolveTabColor(
  tab: DashboardSummary | null | undefined,
  brand: BrandTheme | null,
): string | null {
  // Match the Sidebar rule: MultiQC tabs render in neutral dark, regardless
  // of whatever colour the YAML/seed stamped.
  if (isMultiqcIcon(tab?.tab_icon) || isMultiqcIcon(tab?.icon)) return 'dark';
  // Same precedence as the sidebar pill this title names: the author's colour
  // wins, and a tab that states none takes the brand. Still `null` when there
  // is no brand — an unbranded deployment kept a colourless tab's title as
  // plain body text, and this is not the place to change that.
  return (
    tab?.tab_icon_color || tab?.icon_color || (brand?.tertiary ? BRAND_PALETTES.tertiary : null)
  );
}

/** Where an action sits among its neighbours. A layout keeps each group
 *  together (and may join it into one segmented control), in this order. */
export type HeaderActionGroup =
  | 'filters'
  | 'find'
  | 'author'
  | 'read'
  | 'mode'
  | 'settings'
  | 'aside';

export const HEADER_ACTION_GROUPS: HeaderActionGroup[] = [
  'filters',
  'find',
  'author',
  'read',
  'mode',
  'settings',
  'aside',
];

/** One header action, already rendered (a ChromeButton, or a control that
 *  owns a menu or popover around one). */
export interface HeaderAction {
  id: string;
  group: HeaderActionGroup;
  node: React.ReactNode;
}

export interface HeaderProps {
  dashboardId: string | null;
  dashboard: DashboardData | null;
  /** The active tab in the sibling family (parent or current child). */
  activeTab: DashboardSummary | null;
  /** The parent dashboard (used for "Parent / Child" breadcrumb). */
  parentTab?: DashboardSummary | null;
  mobileOpened: boolean;
  desktopOpened: boolean;
  onToggleMobile: () => void;
  onToggleDesktop: () => void;
  onOpenSettings: () => void;
  cardsLoading?: boolean;
  /** 'view' (default) shows Edit; 'edit' shows View + Add + Save. */
  mode?: 'view' | 'edit';
  /** Edit-mode only: opens the component builder. */
  onAddComponent?: () => void;
  /** Edit-mode only: opens the add-section dialog. The "Add" menu is add-only —
   *  editing sections happens from the "…" on each section header. */
  onAddSection?: () => void;
  /** Edit-mode only: invoked when the user clicks "Save". Should force-flush any pending debounced save. */
  onSave?: () => void;
  /** True when the current user owns this dashboard. When false, the
   *  Edit / Add / Save buttons render disabled with a tooltip
   *  explaining why — the backend enforces the same rule with 403s. The
   *  default is `true` so callers that haven't been migrated keep working,
   *  matching prior behavior. */
  isOwner?: boolean;
  /** Actions the page adds beside the header's own (Comments, Analysis, live
   *  updates), each placed in its group. */
  extraActions?: HeaderAction[];
  /** Optional element rendered right after the title (e.g. the dashboard load
   *  indicator). Replaces the bare `cardsLoading` spinner when provided, since
   *  an indicator of its own already accounts for the card group. */
  titleExtras?: React.ReactNode;
  /** Below `sm` the filter panel moves into a drawer; this opens it. Omitted
   *  (with the button hidden) when there are no filters to show. */
  onOpenFilters?: () => void;
  /** Active filter count, badged on the filters button so a filtered dashboard
   *  never looks unfiltered on a phone. */
  filterCount?: number;
  /** Opens the dashboard search. The button is omitted without it. */
  onOpenSearch?: () => void;
}

/** Everything the header shows, as data: a layout may draw the title and the
 *  actions wherever it likes (a dock, a rail, a toolbar of groups). */
export interface HeaderModel {
  mode: 'view' | 'edit';
  /** The dashboard's name, when the title is "dashboard / tab". */
  dashboardName: string | null;
  /** The tab the reader is on. */
  activeLabel: string;
  /** The full title as one string. */
  titleText: string;
  /** The active tab's icon, sized 20px, or null. */
  tabIcon: React.ReactNode | null;
  /** The tab's colour as a CSS value, when it has one. */
  titleColor: string | undefined;
  /** Beside the title: the dashboard load indicator. */
  titleExtras: React.ReactNode;
  /** The burger buttons (`mobile` below `sm`, `desktop` above). */
  burgers: { mobile: React.ReactNode; desktop: React.ReactNode };
  /** The "Powered by" attribution. */
  poweredBy: React.ReactNode;
  /** Every action, in display order. */
  actions: HeaderAction[];
}

const OWNER_ONLY_EDIT =
  'You can only edit dashboards you own. Duplicate this one to get your own copy.';

/** The header's content as a model; `Header` is one rendering of it. */
export function useHeaderModel({
  dashboardId,
  dashboard,
  activeTab,
  parentTab,
  onToggleMobile,
  onToggleDesktop,
  onOpenSettings,
  cardsLoading = false,
  mode = 'view',
  onAddComponent,
  onAddSection,
  onSave,
  isOwner = true,
  extraActions,
  titleExtras,
  onOpenFilters,
  filterCount = 0,
  onOpenSearch,
}: HeaderProps): HeaderModel {
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';

  const tabIconRaw = resolveTabIcon(activeTab);
  const tabIconIsImage = isImagePath(tabIconRaw);
  // Image path → swap MultiQC PNG/SVG variants to the SPA-served themed SVG.
  // Iconify names (mdi:..., bx:...) pass through unchanged.
  const tabIconImageSrc =
    tabIconIsImage && tabIconRaw ? rewriteMultiqcIcon(tabIconRaw, theme) : null;
  const brand = useBranding();
  const resolvedColor = resolveTabColor(activeTab, brand);
  const tabIconColor = resolvedColor || 'gray';
  // Title text color:
  //   - 'dark' (the MultiQC neutral scheme) → page text color (`#1a1b1e`
  //     light / `#e9ecef` dark) so it stays readable in both schemes.
  //     `dark.6` is near-black and would be invisible on the dark page.
  //   - any other named color → shade 6 in light, shade 4 in dark.
  const titleColor = !resolvedColor
    ? undefined
    : resolvedColor === 'dark'
      ? 'var(--mantine-color-text)'
      : theme === 'dark'
        ? `var(--mantine-color-${resolvedColor}-4)`
        : `var(--mantine-color-${resolvedColor}-6)`;

  // Breadcrumb format: `<dashboard name> / <active tab label>` for every tab.
  // - prefix is the parent dashboard's `title` (e.g. "nf-core/ampliseq")
  // - active label is the tab's pill label: `main_tab_name` for the parent
  //   pill (e.g. "MultiQC"), `title` for child pills (e.g. "Variants").
  // Falls back gracefully if any field is missing.
  const isChild = Boolean(activeTab?.parent_dashboard_id);
  const dashboardName = parentTab?.title || dashboard?.title || null;
  const activeLabel = isChild
    ? activeTab?.title || dashboardId || 'Dashboard'
    : activeTab?.main_tab_name ||
      activeTab?.title ||
      dashboard?.title ||
      dashboardId ||
      'Dashboard';
  const titleText = dashboardName ? `${dashboardName} / ${activeLabel}` : activeLabel;
  // The pill label the reader is actually looking at, or nothing when this tab
  // has none of its own. `activeTab.title` is the dashboard's own title on a
  // parent tab, so reading it here sent "nf-core/ampliseq" as both the
  // dashboard and the tab; an empty field says less but says it truthfully.
  const tabLabel = (isChild ? activeTab?.title : activeTab?.main_tab_name) || null;

  // The reader's context travels with the link: which dashboard, which tab,
  // which page. Without it a remark arrives as "that plot is wrong" with
  // nothing saying where. Both names are the ones on screen, taken from the
  // breadcrumb rather than the raw fields, so the link and the header agree.
  const feedback = useFeedbackLink({
    dashboard: dashboardName ?? null,
    dashboardId,
    tab: tabLabel,
  });

  const handleEdit = () => {
    if (dashboardId) window.location.assign(`/dashboard-edit/${dashboardId}`);
  };
  const handleViewMode = () => {
    if (dashboardId) window.location.assign(`/dashboard/${dashboardId}`);
  };

  const tabIcon = tabIconImageSrc ? (
    <img
      src={tabIconImageSrc}
      alt=""
      className="dc-header-tab-icon"
      style={{ width: 20, height: 20, objectFit: 'contain' }}
    />
  ) : tabIconRaw ? (
    <Icon
      icon={tabIconRaw}
      width={20}
      className="dc-header-tab-icon"
      style={{
        flexShrink: 0,
        color:
          tabIconColor === 'dark'
            ? 'var(--mantine-color-text)'
            : theme === 'dark'
              ? `var(--mantine-color-${tabIconColor}-4)`
              : `var(--mantine-color-${tabIconColor}-6)`,
      }}
    />
  ) : null;

  const actions: HeaderAction[] = [];
  // Only below `sm`, where the filter panel has moved into a drawer.
  if (onOpenFilters) {
    actions.push({
      id: 'filters',
      group: 'filters',
      node: (
        <ChromeButton
          role="secondary"
          collapse
          icon="filters"
          label="Filters"
          badge={filterCount}
          onClick={onOpenFilters}
          className="dc-only-mobile"
        />
      ),
    });
  }
  if (onOpenSearch) {
    actions.push({
      id: 'search',
      group: 'find',
      node: (
        <ChromeButton
          role="quiet"
          iconOnly
          icon="search"
          label="Search this dashboard"
          tooltip={`Search this dashboard (${searchShortcutLabel()})`}
          onClick={onOpenSearch}
          aria-keyshortcuts="Meta+K Control+K"
          data-testid="dashboard-search"
        />
      ),
    });
  }
  // One Add menu rather than a button per thing that can be added.
  if (mode === 'edit' && onAddComponent) {
    actions.push({
      id: 'add',
      group: 'author',
      node: (
        <Menu shadow="md" width={200} position="bottom-end">
          <Menu.Target>
            <ChromeButton
              role="secondary"
              collapse
              icon="add"
              rightIcon="chevronDown"
              label="Add"
              tooltip={isOwner ? undefined : OWNER_ONLY_EDIT}
              disabled={!dashboardId || !isOwner}
              data-tour-id="editor-add-component"
            />
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item
              leftSection={<Icon icon="mdi:view-grid-plus-outline" width={14} />}
              onClick={onAddComponent}
              data-testid="add-component"
            >
              Component
            </Menu.Item>
            {onAddSection && (
              <Menu.Item
                leftSection={<Icon icon="mdi:format-list-group" width={14} />}
                onClick={onAddSection}
                data-testid="add-section"
              >
                Section
              </Menu.Item>
            )}
          </Menu.Dropdown>
        </Menu>
      ),
    });
  }
  // Comments, Analysis, live updates: ways of *reading* the dashboard.
  if (extraActions) actions.push(...extraActions);
  actions.push(
    mode === 'view'
      ? {
          id: 'edit',
          group: 'mode',
          node: (
            <ChromeButton
              role="primary"
              collapse
              icon="edit"
              label="Edit"
              tooltip={isOwner ? undefined : OWNER_ONLY_EDIT}
              onClick={handleEdit}
              disabled={!dashboardId || !isOwner}
              data-tour-id="enter-edit-mode"
            />
          ),
        }
      : {
          id: 'exit-edit',
          group: 'mode',
          node: (
            <ChromeButton
              role="secondary"
              collapse
              icon="view"
              label="Exit Edit"
              onClick={handleViewMode}
              disabled={!dashboardId}
            />
          ),
        },
  );
  // The primary sits last before Settings in both modes: Edit in view, Save
  // in edit.
  if (mode === 'edit' && onSave) {
    actions.push({
      id: 'save',
      group: 'mode',
      node: (
        <ChromeButton
          role="primary"
          collapse
          icon="save"
          label="Save"
          tooltip={
            isOwner
              ? undefined
              : 'You can only save dashboards you own. Duplicate this one to get your own copy.'
          }
          onClick={onSave}
          disabled={!dashboardId || !isOwner}
          data-tour-id="editor-save"
        />
      ),
    });
  }
  actions.push({
    id: 'settings',
    group: 'settings',
    node: (
      <ChromeButton
        role="secondary"
        collapse
        icon="settings"
        label="Settings"
        onClick={onOpenSettings}
      />
    ),
  });
  // An aside about the dashboard rather than an action on it. Also a
  // labelled row in the Settings drawer.
  if (feedback) {
    actions.push({
      id: 'feedback',
      group: 'aside',
      node: (
        <ChromeButton
          role="quiet"
          iconOnly
          icon="feedback"
          label={feedback.label}
          href={feedback.href}
          target="_blank"
          rel="noopener noreferrer"
          className="dc-only-desktop"
          data-testid="dashboard-feedback"
        />
      ),
    });
  }
  // Stable by group, so a page's extra actions land beside their kin.
  const order = (a: HeaderAction) => HEADER_ACTION_GROUPS.indexOf(a.group);
  actions.sort((a, b) => order(a) - order(b));

  return {
    mode,
    dashboardName,
    activeLabel,
    titleText,
    tabIcon,
    titleColor,
    titleExtras: titleExtras ?? (cardsLoading ? <Loader size="xs" /> : null),
    burgers: {
      mobile: (
        <ChromeButton
          role="quiet"
          iconOnly
          icon="menu"
          label="Toggle navigation (mobile)"
          tooltip={null}
          onClick={onToggleMobile}
          className="dc-burger dc-only-mobile"
        />
      ),
      desktop: (
        <ChromeButton
          role="quiet"
          iconOnly
          icon="menu"
          label="Toggle tab sidebar"
          tooltip={null}
          onClick={onToggleDesktop}
          className="dc-burger dc-only-desktop"
        />
      ),
    },
    poweredBy: <PoweredBy withRightBorder />,
    actions,
  };
}

/** Consecutive actions of one group, each run in a `ChromeButtonGroup`. */
export function groupHeaderActions(
  actions: HeaderAction[],
): { group: HeaderActionGroup; actions: HeaderAction[] }[] {
  const runs: { group: HeaderActionGroup; actions: HeaderAction[] }[] = [];
  for (const a of actions) {
    const last = runs[runs.length - 1];
    if (last && last.group === a.group) last.actions.push(a);
    else runs.push({ group: a.group, actions: [a] });
  }
  return runs;
}

/** The actions, one `ChromeButtonGroup` per group. */
export const HeaderActions: React.FC<{ actions: HeaderAction[] }> = ({ actions }) => (
  <>
    {groupHeaderActions(actions).map((run) => (
      <React.Fragment key={run.group}>
        {/* The aside sits past a rule: about the dashboard, not on it. */}
        {run.group === 'aside' && (
          <Divider orientation="vertical" my={6} className="dc-header-divider dc-only-desktop" />
        )}
        <ChromeButtonGroup group={run.group}>
          {run.actions.map((a) => (
            <React.Fragment key={a.id}>{a.node}</React.Fragment>
          ))}
        </ChromeButtonGroup>
      </React.Fragment>
    ))}
  </>
);

/** The header title: tab icon, "dashboard / tab", and its extras. */
export const HeaderTitle: React.FC<{ model: HeaderModel }> = ({ model }) => (
  <>
    {model.tabIcon}
    <Title
      order={3}
      className="dc-header-title"
      style={{
        color: model.titleColor,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        minWidth: 0,
      }}
    >
      {model.dashboardName ? (
        <>
          <span className="dc-header-title-parent">{model.dashboardName}</span>
          <span className="dc-header-title-sep"> / </span>
          <span className="dc-header-title-tab">{model.activeLabel}</span>
        </>
      ) : (
        <span className="dc-header-title-tab">{model.titleText}</span>
      )}
    </Title>
    <span className="dc-header-title-extras">{model.titleExtras}</span>
  </>
);

/**
 * The default header, drawn from a `HeaderModel`. Two regions:
 *   Left:  burgers + active-tab icon + dashboard title (with parent breadcrumb)
 *   Right: PoweredBy, then the actions, one group after another.
 */
export const HeaderView: React.FC<{ model: HeaderModel }> = ({ model }) => {
  return (
    <>
      <Group h="100%" px="md" justify="space-between" wrap="nowrap" className="dc-header-inner">
        <Group gap="sm" wrap="nowrap" className="dc-header-left" style={{ minWidth: 0 }}>
          {model.burgers.mobile}
          {model.burgers.desktop}
          <HeaderTitle model={model} />
        </Group>

        <Box style={{ flex: 1, minWidth: 0 }} />

        {/* Every control is a ChromeButton, so its look comes from its role in
            the active chrome style; each group may draw as one control. */}
        <Group gap={8} wrap="nowrap" className="dc-header-actions" style={{ flexShrink: 0 }}>
          <span className="dc-only-desktop dc-header-powered">{model.poweredBy}</span>
          <HeaderActions actions={model.actions} />
        </Group>
      </Group>
    </>
  );
};

/** Replaces the contents of `<AppShell.Header>`. */
const Header: React.FC<HeaderProps> = (props) => <HeaderView model={useHeaderModel(props)} />;

export default Header;
