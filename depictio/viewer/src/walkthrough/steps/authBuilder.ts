import type { WalkthroughDefinition } from '../types';

/** Authenticated / builder walkthrough — runs once for any logged-in user
 *  (single- or multi-user mode). Goal: walk them through the full pipeline
 *  *projects → dashboards → editor → component → save*, so they understand
 *  data has to live somewhere before a dashboard can render it. */
export const authBuilderWalkthrough: WalkthroughDefinition = {
  id: 'builder',
  // v2 — bumped after restructuring to put projects before dashboards. Anyone
  // who saw the v1 builder tour gets v2 once on next visit.
  version: 'v2',
  label: 'Take the builder tour',
  steps: [
    {
      id: 'welcome',
      target: null,
      title: 'Welcome to Depictio',
      body: "👋 Your reads are processed, your dataframes are clean — now let's make them clickable. We start with a project — that's where the data lives.",
      position: 'bottom',
      image: {
        src: '/dashboard-beta/favicon.svg',
        alt: 'Depictio',
        height: 64,
      },
      navigateTo: '/projects-beta',
    },
    {
      id: 'projects-page',
      target: 'projects-header',
      route: /^\/projects-beta\/?$/,
      title: 'Projects bundle your data',
      body: 'A project groups the data collections, workflows, and permissions your dashboards will pull from. You can have one per study, pipeline, or team.',
      position: 'bottom',
    },
    {
      id: 'projects-create',
      target: 'projects-create',
      route: /^\/projects-beta\/?$/,
      title: 'Create your first project',
      body: "Click here to spin up a new project. You'll pick a name and (optionally) attach data collections — the tour resumes once you land on the project page.",
      position: 'left',
      awaitClick: true,
    },
    {
      id: 'project-detail',
      target: null,
      route: /^\/projects-beta\/[^/]+\/?$/,
      title: 'Inside a project',
      body: "Here you can browse this project's data collections, set permissions, and check workflow runs. When you're ready, we'll head over to Dashboards to build a view on top.",
      position: 'bottom',
      navigateTo: '/dashboards-beta',
    },
    {
      id: 'dashboards-page',
      target: null,
      route: /^\/dashboards-beta\/?$/,
      title: 'Dashboards live here',
      body: 'Dashboards visualize a project. Each one can have multiple tabs and any number of components — figures, cards, tables, and interactive filters.',
      position: 'bottom',
    },
    {
      id: 'dashboards-create',
      target: 'dashboards-create',
      route: /^\/dashboards-beta\/?$/,
      title: 'Create a dashboard',
      body: "Click here to start a new dashboard. Pick the project you just made — the tour will continue in the editor.",
      position: 'left',
      awaitClick: true,
    },
    {
      id: 'editor-add',
      target: 'editor-add-component',
      route: /^\/dashboard-beta-edit\//,
      title: 'Add your first component',
      body: 'A dashboard is built from components. Click "Add component" to open the builder.',
      position: 'bottom',
      awaitClick: true,
    },
    {
      id: 'component-type',
      target: 'component-type-grid',
      route: /\/(create|edit)\//,
      title: 'Pick a component type',
      body: 'Choose what to render: a chart, a KPI card, a data table, or an interactive filter. Each type drives the next configuration steps.',
      position: 'bottom',
    },
    {
      id: 'component-save',
      target: 'component-save',
      route: /\/(create|edit)\//,
      title: 'Save the component',
      body: 'Once data and design are configured, save the component. It will appear on your dashboard grid where you can resize and arrange it.',
      position: 'top',
      awaitClick: true,
    },
    {
      id: 'editor-save',
      target: 'editor-save',
      route: /^\/dashboard-beta-edit\//,
      title: 'Save the dashboard',
      body: 'Components are added to the workspace, but the dashboard layout itself needs an explicit save. Hit Save to persist your work.',
      position: 'bottom',
    },
    {
      id: 'done',
      target: null,
      title: "You're a builder now",
      body: 'You can re-launch this tour any time from the user menu. Add more components, share the dashboard with your team, or duplicate it as a starting point.',
      position: 'bottom',
    },
  ],
};
