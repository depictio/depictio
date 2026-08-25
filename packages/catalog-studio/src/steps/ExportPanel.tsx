import { useMemo, useState } from 'react';
import { Stack, Title, Text, Button, Group, Paper, Alert, Tabs, Code, Badge, List, Anchor } from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import JSZip from 'jszip';
import { useStudioStore } from '../state/useStudioStore';
import { generateEntry, appendRenders } from '../catalog/yamlGen';
import AppendedYamlPreview from './AppendedYamlPreview';
import { validateAll } from '../catalog/grounding';
import { oauthConfigured, signIn, getStoredToken, clearStoredToken, devToken } from '../catalog/githubOAuth';
import { openCatalogPr, openAddRendersPr, openNewOutputPr, resolveTarget } from '../catalog/github';
import type { PrTarget } from '../catalog/github';
import { useUpstreamFile } from '../catalog/upstreamFile';
import type { KindsMap } from '../types';

// Fallback when OAuth isn't configured for the deployment: point GitHub's web
// uploader at the existing parent dir (a non-existent <tool>/ dir 404s) and have
// the user drag the unzipped <tool>/ folder in — GitHub keeps the subpath, forks,
// and opens the PR. No token. Derived from the resolved target so VITE_GH_TARGET
// redirects this path too — it used to send testers at the production repo.
const uploadUrl = (t: PrTarget) =>
  `https://github.com/${t.owner}/${t.repo}/upload/${t.base}/depictio/catalog`;
const editUrl = (t: PrTarget, path: string) =>
  `https://github.com/${t.owner}/${t.repo}/edit/${t.base}/${path}`;

type PrPhase = { status: 'idle' | 'working' | 'done' | 'error'; message?: string; url?: string };

export default function ExportPanel({ kinds }: { kinds: KindsMap }) {
  const tool = useStudioStore((s) => s.tool);
  const output = useStudioStore((s) => s.output);
  const fixture = useStudioStore((s) => s.fixture);
  const renders = useStudioStore((s) => s.renders);
  const existing = useStudioStore((s) => s.existing);
  const newOutputTarget = useStudioStore((s) => s.newOutputTarget);
  const dev = devToken();
  const [signedIn, setSignedIn] = useState<boolean>(() => Boolean(getStoredToken() || dev));
  const [pr, setPr] = useState<PrPhase>({ status: 'idle' });

  // New-tool AND new-output modes generate a fresh entry (a full <slug>.yaml +
  // fixture); the append mode instead edits the tool's current output YAML.
  const entry = useMemo(() => {
    if (!fixture || existing) return null;
    return generateEntry({
      tool,
      output,
      fixtureFileName: fixture.fileName,
      fixtureContent: fixture.raw,
      renders,
    });
  }, [tool, output, fixture, renders, existing]);

  // Preview + download rebase on the file as it is upstream right now; the
  // build-time snapshot is only the fallback when the fetch fails (offline,
  // private fork). The PR path re-reads at its own base commit regardless.
  // Compare against the SHIPPED snapshot, not `rawYaml` — the store refreshes
  // that from upstream on entry, which would make every file look unchanged.
  const upstream = useUpstreamFile(existing?.yamlPath ?? null, existing?.snapshotYaml ?? null);
  const baseYaml =
    upstream.status === 'ok' ? upstream.text : (existing?.rawYaml ?? null);
  const append = useMemo(
    () => (existing && baseYaml != null ? appendRenders(baseYaml, renders) : null),
    [existing, baseYaml, renders],
  );
  const updatedYaml = append?.yaml ?? null;

  const issues = fixture ? validateAll(renders, fixture.columns, kinds) : [];
  const errors = issues.filter((i) => i.severity === 'error');
  // The textual splice refuses a few legal YAML shapes rather than corrupting
  // them; when it does, there is nothing valid to download or commit.
  const appendProblem = append?.problem ?? null;

  if (!fixture || (!entry && !existing)) return <Text c="dimmed">Complete the earlier steps first.</Text>;

  const downloadBlob = (name: string, blob: Blob) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
    notifications.show({ color: 'teal', message: `Downloaded ${name}` });
  };

  const doDownload = async () => {
    try {
      if (existing) {
        if (appendProblem || !updatedYaml) return;
        downloadBlob(`${existing.outputSlug}.yaml`, new Blob([updatedYaml], { type: 'text/yaml' }));
        return;
      }
      if (!entry) return;
      const zip = new JSZip();
      const dir = zip.folder(tool.id)!;
      // New output on an existing tool: only the new files — module.yaml already exists.
      if (!newOutputTarget) dir.file('module.yaml', entry.moduleYaml);
      dir.file(entry.outputYamlName, entry.outputYaml);
      dir.file(entry.fixtureName, entry.fixtureContent);
      const zipName = newOutputTarget ? `${tool.id}-${output.slug}.zip` : `${tool.id}-catalog.zip`;
      downloadBlob(zipName, await zip.generateAsync({ type: 'blob' }));
    } catch (e) {
      // Previously an unhandled rejection with no UI feedback at all.
      notifications.show({ color: 'red', message: `Download failed: ${(e as Error).message}` });
    }
  };

  const contributeViaUpload = async () => {
    // Open the tab FIRST, while the click's user-activation is still live: after
    // an await, Safari and Firefox block the popup and the flow dead-ends.
    const t = resolveTarget();
    const url = existing && existing.yamlPath ? editUrl(t, existing.yamlPath) : uploadUrl(t);
    const tab = window.open(url, '_blank', 'noopener,noreferrer');
    if (!tab) {
      notifications.show({
        color: 'yellow',
        message: 'Your browser blocked the GitHub tab — allow popups for this site, or open it manually.',
      });
    }
    await doDownload();
  };

  const doOpenPr = async () => {
    // Enter the working state up-front so the button is disabled during the
    // OAuth popup too — a second click would open a second popup + listener and
    // trip the state check.
    setPr({ status: 'working', message: signedIn ? 'Starting…' : 'Waiting for GitHub sign-in…' });
    let token = getStoredToken() || dev;
    if (!token) {
      try {
        token = await signIn();
        setSignedIn(true);
      } catch (e) {
        setPr({ status: 'idle' });
        notifications.show({ color: 'red', message: (e as Error).message });
        return;
      }
    }
    setPr({ status: 'working', message: 'Starting…' });
    const onProgress = (m: string) => setPr({ status: 'working', message: m });
    try {
      const result =
        existing
          ? await openAddRendersPr(
              token,
              {
                toolId: existing.toolId,
                outputSlug: existing.outputSlug,
                yamlPath: existing.yamlPath,
                // The renders, not the merged text: the PR re-appends them to
                // the file as it stands upstream. `snapshotYaml` is only used to
                // note in the PR body that the preview was built against an
                // older copy.
                renders,
                snapshotYaml: existing.snapshotYaml,
              },
              resolveTarget(),
              onProgress,
            )
          : newOutputTarget
            ? await openNewOutputPr(token, entry!, newOutputTarget.dir, resolveTarget(), onProgress)
            : await openCatalogPr(token, entry!, resolveTarget(), onProgress);
      setPr({ status: 'done', url: result.prUrl });
      notifications.show({ color: 'teal', message: 'Pull request opened.' });
    } catch (e) {
      const message = (e as Error).message;
      // Only an auth failure justifies dropping the token: doing it on ANY
      // error (a 422, a dropped connection, a refused append) forced a fresh
      // OAuth popup for problems that had nothing to do with credentials.
      if (/\b401\b|Bad credentials|rejected the token/i.test(message)) {
        clearStoredToken();
        setSignedIn(false);
      }
      setPr({ status: 'error', message });
    }
  };

  const canPr = oauthConfigured() || Boolean(dev);
  const target = resolveTarget();
  // Which of the three export shapes this is, and where its files land — derived
  // once so the copy below stays consistent (append edits one file; newOutput
  // adds files to an existing tool dir; newTool creates the tool dir).
  const mode: 'append' | 'newOutput' | 'newTool' = existing
    ? 'append'
    : newOutputTarget
      ? 'newOutput'
      : 'newTool';
  const targetDir = newOutputTarget ? `${newOutputTarget.dir}/` : `depictio/catalog/${tool.id}/`;

  return (
    <Stack gap="lg">
      <div>
        <Title order={3} style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
          Export
        </Title>
        <Text c="dimmed" size="sm">
          {mode === 'append' && existing ? (
            <>Append {renders.length} render(s) to <Code>{existing.yamlPath}</Code>, </>
          ) : mode === 'newOutput' ? (
            <>Add a new output (<Code>{output.slug}.yaml</Code> + fixture) to <Code>{targetDir}</Code>, </>
          ) : (
            <>Download a zip for <Code>{targetDir}</Code>, </>
          )}
          or open a pull request on GitHub. CI (<Code>dev catalog validate</Code>) is the
          authoritative check.
        </Text>
      </div>

      {errors.length > 0 ? (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />} title={`${errors.length} grounding error(s)`}>
          <Stack gap={2}>
            {errors.map((e, i) => (
              <Text key={i} size="sm">
                {e.message}
              </Text>
            ))}
          </Stack>
          <Text size="xs" c="dimmed" mt="xs">
            You can still export, but CI will reject these until fixed.
          </Text>
        </Alert>
      ) : (
        <Alert color="teal" variant="light" icon={<Icon icon="mdi:check-circle-outline" />}>
          Client checks pass — {renders.length} render(s) grounded against{' '}
          <Badge variant="light" size="sm">
            {fixture.fileName}
          </Badge>
          .
        </Alert>
      )}

      <Group>
        <Button
          size="md"
          color="green"
          disabled={Boolean(appendProblem)}
          leftSection={<Icon icon={existing ? 'mdi:file-download-outline' : 'mdi:folder-zip-outline'} />}
          onClick={doDownload}
        >
          {existing ? 'Download updated YAML' : 'Download zip'}
        </Button>

        {canPr ? (
          pr.status === 'done' && pr.url ? (
            <Button
              size="md"
              color="teal"
              component="a"
              href={pr.url}
              target="_blank"
              rel="noopener noreferrer"
              leftSection={<Icon icon="mdi:check-circle" />}
              rightSection={<Icon icon="mdi:open-in-new" width={14} />}
            >
              View pull request
            </Button>
          ) : (
            <Button
              size="md"
              variant="light"
              disabled={Boolean(appendProblem)}
              leftSection={<Icon icon="mdi:github" />}
              loading={pr.status === 'working'}
              onClick={doOpenPr}
            >
              {signedIn ? 'Open pull request' : 'Sign in with GitHub & open PR'}
            </Button>
          )
        ) : (
          <Button
            size="md"
            variant="light"
            leftSection={<Icon icon="mdi:github" />}
            rightSection={<Icon icon="mdi:open-in-new" width={14} />}
            onClick={contributeViaUpload}
          >
            Contribute on GitHub
          </Button>
        )}
      </Group>

      {!canPr && (
        <Text size="xs" c="dimmed">
          One-click PR is off in this deployment: it needs <Code>VITE_GH_CLIENT_ID</Code> and{' '}
          <Code>VITE_GH_OAUTH_WORKER_URL</Code> at build time (Vite inlines them). See{' '}
          <Anchor
            href="https://github.com/depictio/depictio/blob/main/packages/catalog-studio/oauth-worker/README.md"
            target="_blank"
            rel="noreferrer"
          >
            oauth-worker/README
          </Anchor>
          . The steps below work without any token.
        </Text>
      )}
      {canPr ? (
        <>
          {pr.status === 'working' && (
            <Alert color="blue" variant="light" icon={<Icon icon="mdi:loading" />}>
              {pr.message ?? 'Working…'}
            </Alert>
          )}
          {pr.status === 'done' && pr.url && (
            <Alert color="teal" variant="light" icon={<Icon icon="mdi:check-circle" />} title="Pull request opened">
              <Anchor href={pr.url} target="_blank" rel="noopener noreferrer">
                {pr.url}
              </Anchor>
            </Alert>
          )}
          {pr.status === 'error' && (
            <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />} title="Couldn't open the PR">
              <Text size="sm">{pr.message}</Text>
            </Alert>
          )}
          {pr.status === 'idle' && (
            <Text size="xs" c="dimmed">
              One click: sign in with GitHub, and Catalog Studio forks{' '}
              <Code>{target.owner}/{target.repo}</Code>,{' '}
              {mode === 'append' && existing ? (
                <>commits the updated <Code>{existing.yamlPath}</Code></>
              ) : mode === 'newOutput' ? (
                <>commits the two new files under <Code>{targetDir}</Code></>
              ) : (
                <>commits the three files under <Code>{targetDir}</Code></>
              )}
              , and opens the PR. Only the <Code>public_repo</Code> scope is requested.
              {dev ? ' (Local dev token in use.)' : ''}
            </Text>
          )}
        </>
      ) : existing ? (
        <Alert color="blue" variant="light" icon={<Icon icon="mdi:source-pull" />} title="Open a PR without a token">
          <List size="sm" spacing={2} type="ordered">
            <List.Item>
              <strong>Contribute on GitHub</strong> downloads the updated{' '}
              <Code>{existing.outputSlug}.yaml</Code> and opens GitHub's editor for that file.
            </List.Item>
            <List.Item>
              Paste the downloaded contents over the file and click <em>Propose changes</em> — GitHub
              forks the repo and opens the pull request.
            </List.Item>
          </List>
        </Alert>
      ) : (
        <Alert color="blue" variant="light" icon={<Icon icon="mdi:source-pull" />} title="Open a PR without a token">
          <List size="sm" spacing={2} type="ordered">
            <List.Item>
              <strong>Contribute on GitHub</strong> downloads the zip and opens GitHub's file uploader.
            </List.Item>
            <List.Item>
              Unzip it and drag the <Code>{tool.id}/</Code> folder onto the page (it keeps the subpath →{' '}
              <Code>depictio/catalog/{tool.id}/</Code>).
            </List.Item>
            <List.Item>
              Click <em>Propose changes</em> — GitHub forks the repo and opens the pull request.
            </List.Item>
          </List>
        </Alert>
      )}

      <Paper withBorder radius="md" p="md">
        <Group gap="xs" mb="sm" wrap="nowrap">
          <Icon icon="mdi:folder-outline" width={18} />
          <Text fw={600}>
            {existing ? 'Updated file for' : 'Generated files for'}{' '}
            <Code>{tool.name || tool.id}</Code>
          </Text>
          <Badge variant="light" color="gray" radius="sm">
            {existing ? existing.yamlPath : targetDir}
          </Badge>
        </Group>
        {appendProblem && (
          <Alert
            color="red"
            variant="light"
            mb="sm"
            icon={<Icon icon="mdi:file-alert-outline" />}
            title="This file needs a hand edit"
          >
            {appendProblem}
          </Alert>
        )}
        {existing && upstream.status === 'ok' && upstream.drifted && (
          <Alert
            color="blue"
            variant="light"
            mb="sm"
            icon={<Icon icon="mdi:source-branch-sync" />}
            title="Rebased on the current file"
          >
            <Code>{existing.yamlPath}</Code> has changed upstream since this build's catalog
            snapshot. The preview below (and the PR) append to the current version, so nothing
            already merged is reverted.
          </Alert>
        )}
        {existing && upstream.status === 'error' && (
          <Alert
            color="yellow"
            variant="light"
            mb="sm"
            icon={<Icon icon="mdi:cloud-off-outline" />}
            title="Showing the snapshot, not the live file"
          >
            Could not read <Code>{existing.yamlPath}</Code> from GitHub ({upstream.message}), so
            the preview uses this build's snapshot. Opening the PR still re-reads the live file,
            but a downloaded YAML may be based on an outdated copy.
          </Alert>
        )}
        {existing && append ? (
          <AppendedYamlPreview yaml={append.yaml} addedLines={append.addedLines} />
        ) : entry && newOutputTarget ? (
          // New output on an existing tool: module.yaml is untouched, so show only
          // the new <slug>.yaml.
          <CodeHighlight code={entry.outputYaml} language="yaml" />
        ) : entry ? (
          <Tabs defaultValue="module">
            <Tabs.List>
              <Tabs.Tab value="module" leftSection={<Icon icon="mdi:file-cog-outline" />}>
                module.yaml
              </Tabs.Tab>
              <Tabs.Tab value="output" leftSection={<Icon icon="mdi:file-chart-outline" />}>
                {entry.outputYamlName}
              </Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="module" pt="sm">
              <CodeHighlight code={entry.moduleYaml} language="yaml" />
            </Tabs.Panel>
            <Tabs.Panel value="output" pt="sm">
              <CodeHighlight code={entry.outputYaml} language="yaml" />
            </Tabs.Panel>
          </Tabs>
        ) : null}
      </Paper>
    </Stack>
  );
}
