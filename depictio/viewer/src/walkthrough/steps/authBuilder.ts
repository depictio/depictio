import type { WalkthroughDefinition } from '../types';

/** Authenticated / builder walkthrough — runs once for any logged-in user
 *  (single- or multi-user mode). Goal: orient them around the
 *  projects → dashboards → editor → component pipeline so they can build
 *  their first dashboard end-to-end. */
export const authBuilderWalkthrough: WalkthroughDefinition = {
  id: 'builder',
  version: 'v1',
  label: 'Take the builder tour',
  steps: [
    {
      id: 'welcome',
      target: null,
      route: /^\/dashboards-beta(\/|$)/,
      title: 'Welcome to Depictio',
      body: "Let's build your first dashboard. This tour walks you through creating one from scratch.",
      position: 'bottom',
    },
    {
      id: 'dashboards-create',
      target: 'dashboards-create',
      route: /^\/dashboards-beta(\/|$)/,
      title: 'Create a dashboard',
      body: "Dashboards group views over the same project. Click here when you're ready to make one — the tour will continue in the editor.",
      position: 'left',
      awaitClick: true,
    },
    {
      id: 'editor-add',
      target: 'editor-add-component',
      route: /^\/dashboard-beta-edit\//,
      title: 'Add your first component',
      body: 'A dashboard is built from components: figures, cards, tables, and interactive filters. Click "Add component" to open the builder.',
      position: 'bottom',
      awaitClick: true,
    },
    {
      id: 'component-type',
      target: 'component-type-grid',
      route: /\/(create|edit)\//,
      title: 'Pick a component type',
      body: 'Choose what you want to show: a chart, a KPI card, a data table, or an interactive filter. Each type drives the next steps.',
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
      body: 'Components are added to your workspace, but the dashboard layout itself needs an explicit save. Hit Save to persist your work.',
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
