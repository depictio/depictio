import { useMemo, useState } from 'react';
import { Stack, Title, Text, Button, Group, Paper, Alert, Tabs, Code, Badge, List, Anchor } from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import JSZip from 'jszip';
import { useStudioStore } from '../state/useStudioStore';
import { generateEntry, appendRendersToYaml } from '../catalog/yamlGen';
import { validateAll } from '../catalog/grounding';
import { oauthConfigured, signIn, getStoredToken, clearStoredToken, devToken } from '../catalog/githubOAuth';
import { openCatalogPr, openAddRendersPr, resolveTarget } from '../catalog/github';
import type { KindsMap } from '../types';

// Fallback when OAuth isn't configured for the deployment: point GitHub's web
// uploader at the existing parent dir (a non-existent <tool>/ dir 404s) and have
// the user drag the unzipped <tool>/ folder in — GitHub keeps the subpath, forks,
// and opens the PR. No token.
const CATALOG_UPLOAD_URL = 'https://github.com/depictio/depictio/upload/main/depictio/catalog';

type PrPhase = { status: 'idle' | 'working' | 'done' | 'error'; message?: string; url?: string };

export default function ExportPanel({ kinds }: { kinds: KindsMap }) {
  const tool = useStudioStore((s) => s.tool);
  const output = useStudioStore((s) => s.output);
  const fixture = useStudioStore((s) => s.fixture);
  const renders = useStudioStore((s) => s.renders);
  const existing = useStudioStore((s) => s.existing);
  const dev = devToken();
  const [signedIn, setSignedIn] = useState<boolean>(() => Boolean(getStoredToken() || dev));
  const [pr, setPr] = useState<PrPhase>({ status: 'idle' });

  // New-tool mode generates a fresh entry; existing-tool mode appends the new
  // renders to the tool's current output YAML (nothing else changes).
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

  const updatedYaml = useMemo(
    () => (existing ? appendRendersToYaml(existing.rawYaml, renders) : null),
    [existing, renders],
  );

  const issues = fixture ? validateAll(renders, fixture.columns, kinds) : [];
  const errors = issues.filter((i) => i.severity === 'error');

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
    if (existing && updatedYaml) {
      downloadBlob(`${existing.outputSlug}.yaml`, new Blob([updatedYaml], { type: 'text/yaml' }));
      return;
    }
    if (!entry) return;
    const zip = new JSZip();
    const dir = zip.folder(tool.id)!;
    dir.file('module.yaml', entry.moduleYaml);
    dir.file(entry.outputYamlName, entry.outputYaml);
    dir.file(entry.fixtureName, entry.fixtureContent);
    downloadBlob(`${tool.id}-catalog.zip`, await zip.generateAsync({ type: 'blob' }));
  };

  const contributeViaUpload = async () => {
    await doDownload();
    // Existing tool → GitHub's edit page for that file; new tool → the uploader.
    const url =
      existing && existing.yamlPath
        ? `https://github.com/depictio/depictio/edit/main/${existing.yamlPath}`
        : CATALOG_UPLOAD_URL;
    window.open(url, '_blank', 'noopener,noreferrer');
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
        existing && updatedYaml
          ? await openAddRendersPr(
              token,
              {
                toolId: existing.toolId,
                outputSlug: existing.outputSlug,
                yamlPath: existing.yamlPath,
                updatedYaml,
                count: renders.length,
              },
              resolveTarget(),
              onProgress,
            )
          : await openCatalogPr(token, entry!, resolveTarget(), onProgress);
      setPr({ status: 'done', url: result.prUrl });
      notifications.show({ color: 'teal', message: 'Pull request opened.' });
    } catch (e) {
      // A stale/insufficient token is the usual culprit — drop it so the next
      // attempt re-runs sign-in.
      clearStoredToken();
      setSignedIn(false);
      setPr({ status: 'error', message: (e as Error).message });
    }
  };

  const canPr = oauthConfigured() || Boolean(dev);
  const target = resolveTarget();

  return (
    <Stack gap="lg">
      <div>
        <Title order={3} style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
          Export
        </Title>
        <Text c="dimmed" size="sm">
          {existing ? (
            <>
              Append {renders.length} render(s) to <Code>{existing.yamlPath}</Code>, or open a pull
              request on GitHub. CI (<Code>dev catalog validate</Code>) is the authoritative check.
            </>
          ) : (
            <>
              Download a zip for <Code>depictio/catalog/{tool.id}/</Code>, or open a pull request on
              GitHub. CI (<Code>dev catalog validate</Code>) is the authoritative check.
            </>
          )}
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
              One click: sign in with GitHub, and Tools Studio forks{' '}
              <Code>{target.owner}/{target.repo}</Code>,{' '}
              {existing ? (
                <>
                  commits the updated <Code>{existing.yamlPath}</Code>
                </>
              ) : (
                <>
                  commits the three files under <Code>depictio/catalog/{tool.id}/</Code>
                </>
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
            {existing ? existing.yamlPath : `depictio/catalog/${tool.id}/`}
          </Badge>
        </Group>
        {existing && updatedYaml ? (
          <CodeHighlight code={updatedYaml} language="yaml" />
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
