/**
 * "Export / embed" for one component: the API URL that serves it to another
 * site, in the mode the user picks, ready to copy.
 *
 * Two modes, the two formats of `GET /export/dashboards/{id}/components/{cid}`:
 *
 * - **Plotly spec** (`format=json`): `{data, layout, config, meta}` for the
 *   host's own plotly.js. Only for components with a server-built figure.
 * - **Embeddable page** (`format=html`): one self-contained offline page that
 *   runs the viewer's real renderer. Every type but JBrowse.
 *
 * What each component supports comes from the export manifest, fetched when
 * the dialog opens, rather than from a copy of the server's matrix: a kind
 * whose builder lands server-side becomes JSON-exportable here with no edit.
 *
 * Nothing here holds a credential. A private project's export needs a bearer
 * token, which the snippets name as `$DEPICTIO_TOKEN` and the dialog points
 * at the CLI agents page to create; the session token is short-lived and is
 * never pasted into a snippet someone will commit.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  SegmentedControl,
  Stack,
  Switch,
  Tabs,
  Text,
  Tooltip,
  useComputedColorScheme,
} from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import {
  activeFiltersFor,
  compactExportFilters,
  componentExportPath,
  fetchExportManifest,
} from 'depictio-react-core';
import type {
  ComponentExportFormat,
  ComponentExportManifestEntry,
  ComponentExportTarget,
} from 'depictio-react-core';

import { copyToClipboard } from '../../lib/listingUrl';

/** Above this a GET URL risks a proxy's or a browser's length limit, so the
 *  curl snippet switches to the POST form, which takes the same body. */
const MAX_GET_URL = 2000;

const MODES: { value: ComponentExportFormat; label: string; hint: string }[] = [
  {
    value: 'json',
    label: 'Plotly spec (JSON)',
    hint: 'Data, layout and config for your own plotly.js: no frame, your page’s styling.',
  },
  {
    value: 'html',
    label: 'Embeddable page (HTML)',
    hint: 'One self-contained page running Depictio’s own renderer, for an <iframe> or a file.',
  },
];

type Snippet = 'url' | 'curl' | 'plotly' | 'iframe';

export interface ComponentExportModalProps {
  target: ComponentExportTarget | null;
  onClose: () => void;
  /** The dashboard's project is public: its exports need no token. */
  isPublic: boolean;
  /** Some site may frame an embed (a non-empty allowlist on the server). */
  framingEnabled: boolean;
}

function absolute(path: string): string {
  return `${window.location.origin}${path}`;
}

function curlSnippet(
  url: string,
  path: string,
  body: Record<string, unknown>,
  needsToken: boolean,
  format: ComponentExportFormat,
): string {
  const auth = needsToken ? ` \\\n  -H "Authorization: Bearer $DEPICTIO_TOKEN"` : '';
  const out = format === 'html' ? ` \\\n  -o component.html` : '';
  if (url.length <= MAX_GET_URL) return `curl -sS "${url}"${auth}${out}`;
  // Too long for a query string: same route, filters in the body.
  const base = absolute(path.split('?')[0]);
  return (
    `curl -sS -X POST "${base}?format=${format}"${auth} \\\n` +
    `  -H "Content-Type: application/json" \\\n` +
    `  -d '${JSON.stringify(body)}'${out}`
  );
}

function plotlySnippet(url: string, needsToken: boolean): string {
  const headers = needsToken
    ? `, {\n  headers: { Authorization: \`Bearer \${DEPICTIO_TOKEN}\` },\n}`
    : '';
  return (
    `<div id="depictio-figure"></div>\n` +
    `<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>\n` +
    `<script>\n` +
    `fetch("${url}"${headers})\n` +
    `  .then((r) => r.json())\n` +
    `  .then((fig) => Plotly.newPlot("depictio-figure", fig.data, fig.layout, fig.config));\n` +
    `</script>`
  );
}

function iframeSnippet(url: string, title: string): string {
  const safeTitle = title.replace(/"/g, '&quot;') || 'Depictio component';
  return (
    `<iframe src="${url}"\n` +
    `        title="${safeTitle}"\n` +
    `        width="100%" height="420" style="border: 0" loading="lazy"></iframe>`
  );
}

const ComponentExportModal: React.FC<ComponentExportModalProps> = ({
  target,
  onClose,
  isPublic,
  framingEnabled,
}) => {
  const scheme = useComputedColorScheme('light');
  const [manifest, setManifest] = useState<ComponentExportManifestEntry | null>(null);
  const [manifestError, setManifestError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [format, setFormat] = useState<ComponentExportFormat>('json');
  const [theme, setTheme] = useState<'light' | 'dark'>(scheme === 'dark' ? 'dark' : 'light');
  const [withFilters, setWithFilters] = useState(true);
  const [snippet, setSnippet] = useState<Snippet>('url');

  const activeFilters = useMemo(() => activeFiltersFor(target?.filters ?? []), [target]);

  // One manifest read per opening: it is the whole dashboard's, and it says
  // which formats this component has and why it lacks the others.
  useEffect(() => {
    if (!target) return;
    let cancelled = false;
    setLoading(true);
    setManifest(null);
    setManifestError(null);
    setTheme(scheme === 'dark' ? 'dark' : 'light');
    setWithFilters(true);
    fetchExportManifest(target.dashboardId)
      .then((entries) => {
        if (cancelled) return;
        const entry = entries.find((e) => e.component_id === target.componentId) ?? null;
        setManifest(entry);
        if (!entry) setManifestError('This component is not in the export manifest.');
        // Open on the richer format the component has.
        const formats = entry?.formats ?? [];
        setFormat(formats.includes('json') ? 'json' : 'html');
        setSnippet('url');
      })
      .catch((err: unknown) => {
        if (!cancelled) setManifestError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // `scheme` seeds the theme once per opening; it is not a reason to refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  const formats = manifest?.formats ?? [];
  const available = formats.includes(format);
  const filters = withFilters ? activeFilters : [];
  const path = target
    ? componentExportPath(target.dashboardId, target.componentId, { format, theme, filters })
    : '';
  const url = path ? absolute(path) : '';
  const needsToken = !isPublic;

  const snippets: { value: Snippet; label: string; code: string; language: string }[] = [];
  if (target && available) {
    snippets.push({ value: 'url', label: 'URL', code: url, language: 'bash' });
    snippets.push({
      value: 'curl',
      label: 'curl',
      code: curlSnippet(
        url,
        path,
        { filters: compactExportFilters(filters), theme },
        needsToken,
        format,
      ),
      language: 'bash',
    });
    if (format === 'json') {
      snippets.push({
        value: 'plotly',
        label: 'plotly.js',
        code: plotlySnippet(url, needsToken),
        language: 'html',
      });
    } else {
      snippets.push({
        value: 'iframe',
        label: '<iframe>',
        code: iframeSnippet(url, target.title ?? ''),
        language: 'html',
      });
    }
  }
  const shown = snippets.find((s) => s.value === snippet) ?? snippets[0];

  const copy = async (text: string, what: string) => {
    const ok = await copyToClipboard(text);
    notifications.show({
      color: ok ? 'teal' : 'red',
      title: ok ? `${what} copied` : 'Copy failed',
      message: ok ? undefined : 'Select the text and copy it by hand.',
      autoClose: 2500,
    });
  };

  const unavailableReason =
    format === 'json' ? manifest?.json_unavailable_reason : manifest?.html_unavailable_reason;

  return (
    <Modal
      opened={target !== null}
      onClose={onClose}
      size="xl"
      centered
      title={
        <Group gap="xs">
          <Icon icon="mdi:code-json" width={20} />
          <Text fw={600}>Export / embed</Text>
          {target?.title ? (
            <Text c="dimmed" size="sm" lineClamp={1} maw={360}>
              {target.title}
            </Text>
          ) : null}
        </Group>
      }
      data-testid="component-export-modal"
    >
      {loading ? (
        <Group justify="center" py="xl">
          <Loader size="sm" />
        </Group>
      ) : manifestError ? (
        <Alert color="red" icon={<Icon icon="mdi:alert-circle-outline" width={18} />}>
          {manifestError}
        </Alert>
      ) : target && manifest ? (
        <Stack gap="md">
          <Group gap="xs">
            <Badge variant="light">{manifest.component_type}</Badge>
            {manifest.viz_kind ? (
              <Badge variant="light" color="grape">
                {manifest.viz_kind}
              </Badge>
            ) : null}
            <Text size="xs" c="dimmed">
              Served by the export API, live: the link always returns the component as the
              dashboard has it now.
            </Text>
          </Group>

          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Mode
            </Text>
            <SegmentedControl
              fullWidth
              value={format}
              onChange={(value) => setFormat(value as ComponentExportFormat)}
              data={MODES.map((m) => ({
                value: m.value,
                label: (
                  <Tooltip
                    label={
                      formats.includes(m.value)
                        ? m.hint
                        : ((m.value === 'json'
                            ? manifest.json_unavailable_reason
                            : manifest.html_unavailable_reason) ?? 'Not available')
                    }
                    multiline
                    w={300}
                    withArrow
                  >
                    <span data-testid={`export-mode-${m.value}`}>{m.label}</span>
                  </Tooltip>
                ),
                disabled: !formats.includes(m.value),
              }))}
            />
            <Text size="xs" c="dimmed">
              {MODES.find((m) => m.value === format)?.hint}
            </Text>
          </Stack>

          {!available ? (
            <Alert
              color="gray"
              icon={<Icon icon="mdi:information-outline" width={18} />}
              data-testid="export-unavailable"
            >
              {unavailableReason ?? 'This component cannot be exported in this mode.'}
            </Alert>
          ) : (
            <>
              <Group gap="xl" align="flex-end">
                <Stack gap={4}>
                  <Text size="sm" fw={500}>
                    Theme
                  </Text>
                  <SegmentedControl
                    size="xs"
                    value={theme}
                    onChange={(value) => setTheme(value as 'light' | 'dark')}
                    data={[
                      { value: 'light', label: 'Light' },
                      { value: 'dark', label: 'Dark' },
                    ]}
                  />
                </Stack>
                <Switch
                  checked={withFilters && activeFilters.length > 0}
                  disabled={activeFilters.length === 0}
                  onChange={(e) => setWithFilters(e.currentTarget.checked)}
                  label={
                    activeFilters.length > 0
                      ? `Include the current filters (${activeFilters.length})`
                      : 'No filter is active'
                  }
                  data-testid="export-with-filters"
                />
              </Group>

              {needsToken ? (
                <Alert
                  color="yellow"
                  icon={<Icon icon="mdi:lock-outline" width={18} />}
                  title="Private project"
                >
                  This link answers <code>403</code> without a token. Send{' '}
                  <code>Authorization: Bearer $DEPICTIO_TOKEN</code>, with a long-lived token from{' '}
                  <Anchor href="/cli-agents" size="sm">
                    CLI agents
                  </Anchor>
                  .{format === 'html' ? ' An <iframe> cannot send one, so embed it from a public project.' : ''}
                </Alert>
              ) : null}
              {format === 'html' && !framingEnabled ? (
                <Alert
                  color="yellow"
                  icon={<Icon icon="mdi:window-close" width={18} />}
                  title="No site may frame this page yet"
                >
                  The page opens on its own, but an <code>&lt;iframe&gt;</code> of it is refused until
                  an administrator lists the site in{' '}
                  <code>DEPICTIO_FASTAPI_EMBED_ALLOWED_ORIGINS</code>.
                </Alert>
              ) : null}

              <Tabs value={shown?.value ?? 'url'} onChange={(v) => v && setSnippet(v as Snippet)}>
                <Tabs.List>
                  {snippets.map((s) => (
                    <Tabs.Tab key={s.value} value={s.value} data-testid={`export-snippet-${s.value}`}>
                      {s.label}
                    </Tabs.Tab>
                  ))}
                </Tabs.List>
              </Tabs>
              {shown ? (
                <div data-testid="export-snippet">
                  {/* Mantine's copy button needs navigator.clipboard, which an
                      http:// deployment lacks; the button below falls back. */}
                  <CodeHighlight
                    code={shown.code}
                    language={shown.language}
                    withCopyButton={false}
                    // A URL is one long token: wrap it rather than scroll it
                    // out of sight, so what is copied is what is read.
                    styles={{ code: { whiteSpace: 'pre-wrap', wordBreak: 'break-all' } }}
                  />
                </div>
              ) : null}

              <Text size="xs" c="dimmed">
                Every response carries an ETag and <code>X-Depictio-Revision</code>: poll with{' '}
                <code>If-None-Match</code>, pin with <code>?expect_revision=</code>.
              </Text>
              <Group justify="flex-end">
                <Group gap="xs">
                  <Button
                    size="xs"
                    variant="default"
                    component="a"
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    leftSection={<Icon icon="mdi:open-in-new" width={14} />}
                    data-testid="export-open"
                  >
                    Open
                  </Button>
                  <Button
                    size="xs"
                    leftSection={<Icon icon="mdi:content-copy" width={14} />}
                    onClick={() => shown && copy(shown.code, shown.label)}
                    data-testid="export-copy"
                  >
                    Copy {shown?.label}
                  </Button>
                </Group>
              </Group>
            </>
          )}
        </Stack>
      ) : null}
    </Modal>
  );
};

export default ComponentExportModal;
