import { useState } from 'react';
import { Modal, Stack, TextInput, PasswordInput, Button, Text, Anchor, Alert, Code, Group } from '@mantine/core';
import { Icon } from '@iconify/react';
import { openCatalogPr } from '../catalog/github';
import type { GeneratedEntry } from '../catalog/yamlGen';

const UPSTREAM = { owner: 'depictio', repo: 'depictio' };

export default function PrModal({
  opened,
  onClose,
  entry,
}: {
  opened: boolean;
  onClose: () => void;
  entry: GeneratedEntry;
}) {
  const [token, setToken] = useState('');
  const [branch, setBranch] = useState(`catalog/${entry.toolId}`);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ html_url: string; number: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    const base = `depictio/catalog/${entry.toolId}`;
    try {
      const pr = await openCatalogPr({
        token: token.trim(),
        target: UPSTREAM,
        branch: branch.trim(),
        title: `catalog: add ${entry.toolId}`,
        body:
          `Adds the \`${entry.toolId}\` catalog entry (generated with Catalog Studio).\n\n` +
          `- \`${base}/module.yaml\`\n` +
          `- \`${base}/${entry.outputYamlName}\`\n` +
          `- \`${base}/${entry.fixtureName}\` (fixture)\n\n` +
          `Validated client-side; CI \`dev catalog validate\` is authoritative.`,
        files: [
          { path: `${base}/module.yaml`, content: entry.moduleYaml },
          { path: `${base}/${entry.outputYamlName}`, content: entry.outputYaml },
          { path: `${base}/${entry.fixtureName}`, content: entry.fixtureContent },
        ],
      });
      setResult(pr);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Open a pull request" size="lg">
      <Stack>
        <Text size="sm" c="dimmed">
          Catalog Studio forks <Code>depictio/depictio</Code>, commits the three files, and opens a
          PR — all from your browser with a token you provide. The token is used only for these API
          calls and is never stored.
        </Text>
        <PasswordInput
          label="GitHub token (PAT)"
          description="Needs repo/contents + pull-request write. Create a fine-grained token scoped to your fork."
          placeholder="ghp_… / github_pat_…"
          value={token}
          onChange={(e) => setToken(e.currentTarget.value)}
          required
        />
        <TextInput
          label="Branch name"
          value={branch}
          onChange={(e) => setBranch(e.currentTarget.value)}
        />

        {error && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
            {error}
          </Alert>
        )}
        {result && (
          <Alert color="teal" variant="light" icon={<Icon icon="mdi:check-circle" />}>
            <Group gap={6}>
              Opened PR #{result.number} —
              <Anchor href={result.html_url} target="_blank" rel="noreferrer">
                view on GitHub
              </Anchor>
            </Group>
          </Alert>
        )}

        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Close
          </Button>
          <Button
            color="green"
            loading={busy}
            disabled={!token.trim() || !branch.trim() || !!result}
            leftSection={<Icon icon="mdi:source-pull" />}
            onClick={submit}
          >
            Create pull request
          </Button>
        </Group>

        <Anchor
          href="https://github.com/settings/tokens?type=beta"
          target="_blank"
          rel="noreferrer"
          size="xs"
        >
          Create a fine-grained token →
        </Anchor>
      </Stack>
    </Modal>
  );
}
