/**
 * Per-type design surface: depictio's own builder, unmodified.
 *
 * Every panel here is imported straight from `depictio/viewer/src/builder` via
 * the `depictio-builder` alias — the same components the dashboard editor
 * mounts, with the same controls, the same layout and the same live previews.
 * They work with no backend because the offline api shim (`src/api/studioApi.ts`)
 * answers their data calls from the fixture, and `seedStore.ts` fills the store
 * they read their columns from.
 *
 * The Studio used to reimplement four of these five panels. That is what made
 * its sliders, its advanced-viz menu and its table options diverge from
 * depictio's — an author configured one thing here and got another there.
 */
import React from 'react';
import { Alert, Code, List, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { ComponentType } from 'depictio-builder/store/useBuilderStore';
import AdvancedVizBuilder from 'depictio-builder/advanced_viz/AdvancedVizBuilder';
import CardBuilder from 'depictio-builder/card/CardBuilder';
import FigureBuilder from 'depictio-builder/figure/FigureBuilder';
import InteractiveBuilder from 'depictio-builder/interactive/InteractiveBuilder';
import TableBuilder from 'depictio-builder/table/TableBuilder';
import { CodeModeEnvironmentProvider } from 'depictio-builder/figure/codeModeEnvironment';

/** Every builder is store-driven and takes no props, so the dispatch is a
 *  lookup rather than a chain of comparisons. */
const BUILDERS: Partial<Record<ComponentType, React.FC>> = {
  figure: FigureBuilder,
  card: CardBuilder,
  table: TableBuilder,
  interactive: InteractiveBuilder,
  advanced_viz: AdvancedVizBuilder,
};

/** What Code Mode does *here*, shown above depictio's own description of its
 *  server-side sandbox.
 *
 *  That description — RestrictedPython, a Polars `df` — is true of the render
 *  once it is imported into depictio and true of nothing in this app, where
 *  Execute runs the snippet in the browser under Pyodide against the fixture.
 *  The pandas/Polars split is the part that actually bites: a snippet that
 *  works in this preview can still fail server-side, so the `to_pandas()`
 *  idiom is spelled out here rather than left to be discovered. */
const CODE_MODE_NOTE = (
  <Alert
    color="blue"
    variant="light"
    icon={<Icon icon="mdi:flask-outline" width={18} />}
    title="In Tool Studio, this preview runs in your browser"
  >
    <List size="xs" spacing={4}>
      <List.Item>
        <strong>Execute</strong> runs your code here, under Pyodide (a Python build for the
        browser). Your file never leaves this page, and the first run downloads that runtime,
        which takes a few seconds, once per session.
      </List.Item>
      <List.Item>
        <Code fz="xs">df</Code> is your fixture as a <strong>pandas</strong> DataFrame: Polars has
        no browser build, so <Code fz="xs">pl</Code> is unavailable here and says so if you reach
        for it. <Code fz="xs">df.to_pandas()</Code> still works, so snippets copied from depictio
        run unchanged.
      </List.Item>
      <List.Item>
        Your snippet is exported <strong>verbatim</strong> as the render&apos;s{' '}
        <Code fz="xs">code</Code>, and depictio runs it server-side, where <Code fz="xs">df</Code>{' '}
        <em>is</em> Polars. Call <Code fz="xs">df.to_pandas()</Code> before any pandas-only
        operation and it behaves the same in both places.
      </List.Item>
    </List>
    <Text size="xs" c="dimmed" mt={6}>
      Everything below describes that server-side sandbox: what runs your code once the tool is in
      the catalog.
    </Text>
  </Alert>
);

const CODE_MODE_ENVIRONMENT = { note: CODE_MODE_NOTE, openAbout: true };

export default function DesignArea({ type }: { type: ComponentType }) {
  const Builder = BUILDERS[type];
  if (!Builder) return null;
  return (
    <CodeModeEnvironmentProvider value={CODE_MODE_ENVIRONMENT}>
      <Builder />
    </CodeModeEnvironmentProvider>
  );
}
