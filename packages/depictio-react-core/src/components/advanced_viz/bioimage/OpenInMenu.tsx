import React, { useState } from 'react';
import { ActionIcon, Menu, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  absoluteApiUrl,
  createBioimageHandoffLink,
  fetchBioimageHandoffStatus,
  type BioimageHandoffStatus,
  type BioimageStoreInfo,
} from '../../../api';
import { useFullscreenPortalTarget } from '../../chrome/useFullscreenPortalTarget';
import {
  copyCommands,
  handoffUrl,
  HANDOFF_TARGETS,
  unsupportedReason,
  type HandoffStore,
  type HandoffTargetId,
} from './handoff';
import type { NgffContainerLayout } from './layout';

/** How the store reaches another viewer, once the server has said (see handoff.ts). */
type Tier =
  | { kind: 'remote'; url: string }
  | { kind: 'public'; url: string }
  | { kind: 'link'; ttlMinutes: number }
  | { kind: 'none'; reason: string };

function tierOf(status: BioimageHandoffStatus, dcId: string, store: BioimageStoreInfo): Tier {
  const remote = status.remote_urls[store.name];
  if (remote) return { kind: 'remote', url: remote };
  if (status.public) {
    const path = `/advanced_viz/bioimage/${encodeURIComponent(dcId)}/${encodeURIComponent(store.name)}`;
    return { kind: 'public', url: absoluteApiUrl(path) };
  }
  if (status.links_enabled) return { kind: 'link', ttlMinutes: status.ttl_minutes };
  return {
    kind: 'none',
    reason:
      'This store is private, and this server does not make share links ' +
      '(an admin can turn on DEPICTIO_BIOIMAGE_HANDOFF_ENABLED).',
  };
}

function onThisComputer(): boolean {
  if (typeof window === 'undefined') return false;
  return ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname);
}

interface Props {
  dcId: string;
  store: BioimageStoreInfo;
  layout?: NgffContainerLayout | null;
  imagePath?: string | null;
}

/**
 * "Open in ...": the store in vizarr, Neuroglancer, Vitessce or the NGFF
 * validator, and commands to paste into napari. Targets that cannot take the
 * store are listed greyed out with the reason, never hidden.
 */
const OpenInMenu: React.FC<Props> = ({ dcId, store, layout, imagePath }) => {
  const portalTarget = useFullscreenPortalTarget();
  const [status, setStatus] = useState<BioimageHandoffStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const handoffStore: HandoffStore = { name: store.name, format: store.format, layout, imagePath };
  const tier = status ? tierOf(status, dcId, store) : null;

  const load = () => {
    setError(null);
    setCopied(null);
    if (status) return;
    fetchBioimageHandoffStatus(dcId)
      .then(setStatus)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  };

  /** The store URL for this tier: a fresh signed link for a private store. */
  const storeUrl = async (): Promise<string> => {
    if (!tier || tier.kind === 'none') throw new Error('No URL for this store');
    if (tier.kind !== 'link') return tier.url;
    const link = await createBioimageHandoffLink(dcId, store.name);
    return absoluteApiUrl(link.path);
  };

  const open = (target: HandoffTargetId) => {
    // Opened now, filled once the link exists: a window opened after an await
    // is a popup the browser blocks.
    const win = window.open('', '_blank');
    storeUrl()
      .then((url) => {
        const address = handoffUrl(target, url, handoffStore);
        if (win) {
          win.opener = null;
          win.location.href = address;
        } else {
          window.open(address, '_blank', 'noopener');
        }
      })
      .catch((err: unknown) => {
        win?.close();
        setError(err instanceof Error ? err.message : String(err));
      });
  };

  const copy = (label: string, pick: (url: string) => string) => {
    storeUrl()
      .then((url) => navigator.clipboard.writeText(pick(url)))
      .then(() => setCopied(label))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  };

  const blocked = tier?.kind === 'none' ? tier.reason : null;
  const pending = !tier && !error;
  const commands = copyCommands('URL', handoffStore);

  return (
    <Menu
      position="bottom-end"
      withinPortal
      portalProps={{ target: portalTarget }}
      closeOnItemClick={false}
      onOpen={load}
      width={300}
    >
      <Menu.Target>
        <Tooltip label="Open in another viewer" withArrow openDelay={300}>
          <ActionIcon
            size="sm"
            variant="default"
            aria-label="Open in another viewer"
            data-testid="bioimage-open-in"
          >
            <Icon icon="tabler:external-link" width={14} height={14} />
          </ActionIcon>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown data-testid="bioimage-open-in-menu">
        <Menu.Label>Open {store.sample} in</Menu.Label>
        {HANDOFF_TARGETS.map((target) => {
          const reason = unsupportedReason(target.id, handoffStore) ?? blocked;
          return (
            <Tooltip
              key={target.id}
              label={reason ?? target.description}
              multiline
              w={240}
              position="left"
              withArrow
              openDelay={250}
            >
              <div>
                <Menu.Item
                  leftSection={<Icon icon={target.icon} width={14} />}
                  disabled={Boolean(reason) || pending}
                  onClick={() => open(target.id)}
                  data-testid={`bioimage-open-in-${target.id}`}
                >
                  {target.label}
                </Menu.Item>
              </div>
            </Tooltip>
          );
        })}
        <Menu.Divider />
        <Menu.Label>Copy</Menu.Label>
        {commands.map((cmd) => (
          <Menu.Item
            key={cmd.label}
            leftSection={<Icon icon={copied === cmd.label ? 'tabler:check' : 'tabler:copy'} width={14} />}
            disabled={Boolean(blocked) || pending}
            onClick={() =>
              copy(cmd.label, (url) => copyCommands(url, handoffStore).find((c) => c.label === cmd.label)?.text ?? url)
            }
          >
            {cmd.label === 'Store URL' ? 'Store URL' : `${cmd.label} command`}
          </Menu.Item>
        ))}
        <Menu.Divider />
        <Text size="xs" c={error ? 'red' : 'dimmed'} px="xs" pb={4} data-testid="bioimage-open-in-note">
          {error
            ? error
            : !tier
              ? 'Checking how this store can be shared…'
              : tier.kind === 'remote'
                ? 'Opens the store at its own address.'
                : tier.kind === 'public'
                  ? 'Public project: the link opens for anyone.'
                  : tier.kind === 'link'
                    ? `Anyone with the link can read this image for ${tier.ttlMinutes} min.`
                    : tier.reason}
          {tier && tier.kind !== 'remote' && onThisComputer()
            ? ' The viewer runs on another site: your browser may ask to let it reach this computer.'
            : ''}
        </Text>
      </Menu.Dropdown>
    </Menu>
  );
};

export default OpenInMenu;
