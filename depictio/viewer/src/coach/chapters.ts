import type { CoachChapter, CoachContext, CoachPersona } from './types';

const DASHBOARDS = /^\/dashboards\/?$/;
const DASHBOARD_VIEW = /^\/dashboard\/[^/]+\/?$/;
const PROJECTS = /^\/projects\/?$/;
const EDITOR = /^\/dashboard-edit\/[^/]+\/?$/;
const COMPONENT = /\/component\/(add|edit)\//;

const dashboardsGuest: CoachChapter = {
  id: 'dashboards-guest',
  version: 1,
  label: 'Dashboards',
  icon: 'mdi:view-dashboard-outline',
  route: DASHBOARDS,
  persona: 'guest',
  offer: {
    title: 'New here?',
    body: 'A three-step look at what you can do with these dashboards.',
  },
  steps: [
    {
      id: 'open',
      target: 'dashboard-card',
      title: 'Open a dashboard',
      body: 'Click one to explore it: filter it, hover its figures, export what you need. Nothing you do changes it for anyone else.',
    },
    {
      id: 'copy',
      target: 'dashboard-actions',
      title: 'Make your own copy',
      body: (ctx: CoachContext) =>
        `This menu holds **Duplicate**: an editable copy of the dashboard, yours for the session (${ctx.sessionTtl}). Move things around, add components, save your view.`,
    },
    {
      id: 'sign-in',
      target: null,
      title: 'Sign in to keep a trace',
      body: 'Comments and annotations need an account: sign in from the avatar at the top right.',
      when: (ctx: CoachContext) => ctx.canSignIn,
    },
  ],
};

const dashboardsBuilder: CoachChapter = {
  id: 'dashboards-builder',
  version: 1,
  label: 'Dashboards',
  icon: 'mdi:view-dashboard-outline',
  route: DASHBOARDS,
  persona: 'builder',
  offer: {
    title: 'New to Dashboards?',
    body: 'A three-step look at this page, about a minute.',
  },
  steps: [
    {
      id: 'find',
      target: 'dashboards-toolbar',
      title: 'Find a dashboard',
      body: 'Search, group and sort everything you can open. The star pins the ones you use most to the top.',
    },
    {
      id: 'open',
      target: 'dashboard-card',
      title: 'Open, rename, duplicate',
      body: 'Click a dashboard to open it. Its ⋮ menu renames it, duplicates it or exports it as JSON.',
    },
    {
      id: 'create',
      target: 'dashboards-create',
      title: 'Start a new one',
      body: "**New dashboard** builds one on a project's data, from an empty canvas or from an exported dashboard.",
    },
  ],
};

/** The welcome card's "Build a dashboard": the ways to start one, then where
 *  the building happens. */
const dashboardsBuild: CoachChapter = {
  id: 'dashboards-build',
  version: 1,
  label: 'Build a dashboard',
  icon: 'mdi:view-grid-plus-outline',
  route: DASHBOARDS,
  persona: 'builder',
  journeyOnly: true,
  offer: {
    title: 'Build a dashboard',
    body: 'Two ways to start one, then the editor.',
  },
  steps: [
    {
      id: 'new',
      target: 'dashboards-create',
      title: 'Start from a project',
      body: "**New dashboard** asks for a project and a title, then opens an empty canvas on that project's data. Its **Import** tab starts from a dashboard exported as JSON instead.",
    },
    {
      id: 'copy',
      target: 'dashboard-actions',
      title: 'Or start from a copy',
      body: "**Duplicate**, in a dashboard's ⋮ menu, makes a copy that is yours to change. The original stays as it is.",
    },
    {
      id: 'editor',
      target: null,
      title: 'Then, the editor',
      body: 'Open a dashboard and click its **Edit** pencil: add components, arrange them, save versions. The editor shows you around the first time.',
    },
  ],
};

/** The welcome card's "Explore a dashboard", run on the dashboard it opens:
 *  how to move around it, then the Guide for the rest. Never offered on its
 *  own: a dashboard opened from a link has the landing card. */
const dashboardExplore: CoachChapter = {
  id: 'dashboard-explore',
  version: 1,
  label: 'Explore a dashboard',
  icon: 'mdi:view-dashboard-outline',
  route: DASHBOARD_VIEW,
  persona: 'builder',
  journeyOnly: true,
  offer: {
    title: 'Explore a dashboard',
    body: 'Tabs, filters, components, then the Guide.',
  },
  steps: [
    {
      id: 'tabs',
      target: 'sidebar',
      title: 'Move between tabs',
      body: 'Each tab answers one question about the data. The sidebar lists them, grouped under headings.',
    },
    {
      id: 'filters',
      target: ['[data-testid="glass-filters"]', 'filter-panel'],
      title: 'Narrow the samples',
      body: '**Filters** holds the controls: pick values and the figures follow. Sample filters apply to every tab.',
    },
    {
      id: 'actions',
      // The first tile with data and actions: a text block reads no data.
      target:
        '.depictio-component-chrome:not([data-component-type="text"]):has(> .depictio-component-actions > *)',
      title: 'Ask a component',
      body: "Hover a component: the icons in its corner show where its data comes from, open it full screen or export what it shows.",
    },
    {
      id: 'guide',
      target: 'guide',
      title: 'The Guide goes further',
      body: '**Guide** walks through this dashboard part by part, with live examples drawn from it: sections, analysis, labels, comments, versions.',
    },
  ],
};

const projects: CoachChapter = {
  id: 'projects',
  version: 1,
  label: 'Projects',
  icon: 'mdi:folder-table-outline',
  route: PROJECTS,
  persona: 'builder',
  offer: {
    title: 'New to Projects?',
    body: 'Where your data comes in: three steps, about a minute.',
  },
  steps: [
    {
      id: 'what',
      target: 'projects-header',
      title: 'Projects hold the data',
      body: "A project gathers a pipeline's results as data collections, says who may use them, and carries the dashboards built on them.",
    },
    {
      id: 'create',
      target: 'projects-create',
      title: 'Bring your results in',
      body: 'Point **New project** at a run folder: Depictio works out what each file is. From a terminal, `depictio ingest` does the same.',
    },
    {
      id: 'inside',
      target: null,
      title: 'Inside a project',
      body: 'Open one to see its data collections, its runs and the ingestion report, which says what was read and what was not.',
    },
  ],
};

const editor: CoachChapter = {
  id: 'editor',
  version: 1,
  label: 'Editor',
  icon: 'mdi:pencil-ruler',
  route: EDITOR,
  persona: 'builder',
  offer: {
    title: 'First time in the editor?',
    body: 'How to add, arrange and keep your work: three steps.',
  },
  steps: [
    {
      id: 'add',
      target: 'editor-add-component',
      title: 'Add components and sections',
      body: '**Add → Component** opens the builder. **Add → Section** groups components under a heading readers can fold.',
    },
    {
      id: 'arrange',
      target: 'editor-grid',
      title: 'Arrange the canvas',
      body: 'Drag a component by its header to move it, by its corner to resize it. The layout saves as you go.',
    },
    {
      id: 'save',
      target: 'editor-save',
      title: 'Save a version',
      body: '**Save** marks a version you can find again: **Settings → History** previews or restores any of them.',
    },
  ],
};

const component: CoachChapter = {
  id: 'component',
  version: 1,
  label: 'Component builder',
  icon: 'mdi:view-grid-plus-outline',
  route: COMPONENT,
  persona: 'builder',
  offer: {
    title: 'Building a component?',
    body: 'Build or pick, then kind, data and design: three steps.',
  },
  steps: [
    {
      id: 'source',
      target: ['component-source-choice', 'component-type-grid'],
      title: 'Build one, or pick one',
      body: "**New component** builds one step by step. **Pick from catalog** offers ready visualisations for the tools Depictio recognised in your project's data.",
    },
    {
      id: 'wizard',
      target: 'component-wizard-stepper',
      title: 'Kind, data, then design',
      body: 'Pick a figure, a table, a card, a filter or an advanced visualisation, choose its data collection and columns, then shape the look with a live preview.',
    },
    {
      id: 'save',
      target: 'component-save',
      title: 'Put it on the canvas',
      body: 'Saving places the component on the dashboard, where you can move and resize it.',
    },
  ],
};

export const CHAPTERS: readonly CoachChapter[] = [
  dashboardsGuest,
  dashboardsBuilder,
  dashboardsBuild,
  dashboardExplore,
  projects,
  editor,
  component,
];

/** The chapter of this page for this visitor, if it has one. A dashboard
 *  opened for reading never has one: the landing card speaks there. */
export function chapterFor(pathname: string, persona: CoachPersona): CoachChapter | null {
  return (
    CHAPTERS.find((c) => !c.journeyOnly && c.persona === persona && c.route.test(pathname)) ?? null
  );
}

export function chapterById(id: string): CoachChapter | null {
  return CHAPTERS.find((c) => c.id === id) ?? null;
}

/** The pages a first visit is welcomed on: where a visitor starts. */
export const WELCOME_ROUTE = /^\/(dashboards|projects)\/?$/;

/** `24h`, `90m`, `1h 30m` from the temporary-user expiry settings. */
export function formatSessionTtl(hours: number, minutes: number): string {
  if (minutes <= 0) return `${hours}h`;
  if (hours <= 0) return `${minutes}m`;
  return `${hours}h ${minutes}m`;
}
