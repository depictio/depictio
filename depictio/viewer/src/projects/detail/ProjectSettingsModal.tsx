import React, { useEffect, useRef } from 'react';
import { Group, Loader, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';

import {
  SECTION_ICON_STYLE,
  SettingsNavModal,
  SettingsRailNote,
  type SettingsNavSection,
} from '../../components/settings/SettingsNavModal';
import StoragePanel from './StoragePanel';
import ManifestRefreshPanel, {
  isRefreshEnded,
  summarizeRefresh,
  useManifestRefresh,
  type ManifestRefreshDc,
} from './ManifestRefreshPanel';
import ExportTemplatePanel from './ExportTemplatePanel';

export type ProjectSettingsSectionKey = 'storage' | 'refresh' | 'export';

interface ProjectSettingsModalProps {
  opened: boolean;
  onClose: () => void;
  projectId: string;
  /** Shown beside the dialog title. */
  projectName?: string | null;
  /** Owners and admins: the storage credentials are theirs alone. */
  canManageStorage: boolean;
  /** Owners, editors and admins: refresh and export. */
  canMutate: boolean;
  /** Why refresh and export are unavailable to this reader on this
   *  deployment (public/demo mode for non-admins, or not known yet while the
   *  auth status loads); null when they are not gated by it. */
  publicModeReason: string | null;
  dataCollections: ReadonlyArray<ManifestRefreshDc>;
  /** Reload the project page once a refresh has rebuilt its tables. */
  onReloadProject?: () => void;
  /** Open on this section rather than the one last visited. */
  initialSection?: ProjectSettingsSectionKey;
}

/**
 * The project's own settings, in the same rail-and-page dialog as the
 * dashboard settings:
 *
 * 1. Storage: the S3-compatible endpoint and keys this project's remote data
 *    collections read private buckets with (owners only).
 * 2. Data refresh: re-read the collections whose source the server can reach
 *    again, and follow the run.
 * 3. Export template: package the project as a reusable template bundle.
 *
 * Unlike the dashboard settings, nothing saves as you go: each section acts
 * on its own button. Unsaved edits survive a switch to another section and
 * back, and are dropped when the dialog closes. A refresh keeps being
 * followed while the dialog is closed (its state lives here, and this
 * component stays mounted on the project page), and says so with a
 * notification when it ends out of sight.
 */
const ProjectSettingsModal: React.FC<ProjectSettingsModalProps> = ({
  opened,
  onClose,
  projectId,
  projectName,
  canManageStorage,
  canMutate,
  publicModeReason,
  dataCollections,
  onReloadProject,
  initialSection,
}) => {
  const refresh = useManifestRefresh(projectId, dataCollections);
  const refreshing = refresh.state === 'starting' || refresh.state === 'running';

  // A refresh that ends while the dialog is closed would otherwise end
  // unnoticed: say how it went.
  const openedRef = useRef(opened);
  openedRef.current = opened;
  const previousState = useRef(refresh.state);
  useEffect(() => {
    const was = previousState.current;
    previousState.current = refresh.state;
    const ended = (was === 'starting' || was === 'running') && isRefreshEnded(refresh.state);
    if (!ended || openedRef.current) return;
    if (refresh.state === 'stopped') {
      // Not an outcome: the page stopped polling, the run may still go on.
      notifications.show({
        color: 'yellow',
        title: 'Stopped following the data refresh',
        message:
          'It may still be running. The Ingestion tab shows how it ends; ' +
          'project settings show what was seen so far.',
        autoClose: 8000,
      });
      return;
    }
    const ok = refresh.state === 'success';
    notifications.show({
      color: ok ? 'teal' : 'red',
      title: ok ? 'Data refresh completed' : 'Data refresh finished with errors',
      message: refresh.report
        ? `${summarizeRefresh(refresh.report)}. Project settings show the details.`
        : 'Project settings show the details.',
      autoClose: 8000,
    });
  }, [refresh.state, refresh.report]);

  const sections: SettingsNavSection[] = [
    {
      key: 'storage',
      icon: 'mdi:cloud-key-outline',
      title: 'Storage',
      subtitle: "The private bucket this project's data collections read from, for owners",
      body: <StoragePanel projectId={projectId} canManage={canManageStorage} />,
    },
    {
      key: 'refresh',
      icon: 'mdi:file-sync-outline',
      title: 'Data refresh',
      subtitle: 'Re-read the collections that come from a manifest, a URL or a bucket',
      navHint: refreshing ? <Loader size={12} /> : undefined,
      body: (
        <ManifestRefreshPanel
          refresh={refresh}
          canMutate={canMutate}
          publicModeReason={publicModeReason}
          onReloadProject={onReloadProject}
        />
      ),
    },
    {
      key: 'export',
      icon: 'mdi:package-variant-closed',
      title: 'Export template',
      navLabel: 'Export',
      subtitle: 'Package this project and its dashboards to build them again on other data',
      body: (
        <ExportTemplatePanel
          projectId={projectId}
          canMutate={canMutate}
          publicModeReason={publicModeReason}
        />
      ),
    },
  ];

  const title = (
    <Group gap="xs" wrap="nowrap">
      <Icon icon="ic:baseline-settings" width={20} height={20} style={SECTION_ICON_STYLE} />
      <Text fw={600}>Project settings</Text>
      {projectName && (
        <Text c="dimmed" size="sm" truncate>
          {projectName}
        </Text>
      )}
    </Group>
  );

  return (
    <SettingsNavModal
      opened={opened}
      onClose={onClose}
      title={title}
      sections={sections}
      storageKey="depictio-project-settings-active"
      defaultSection="storage"
      initialSection={initialSection}
      keepVisitedMounted
      ariaLabel="Project settings"
      testIdPrefix="project-settings"
      footer={
        <SettingsRailNote icon="mdi:information-outline">
          Nothing saves on close: each section acts on its own button.
        </SettingsRailNote>
      }
    />
  );
};

export default ProjectSettingsModal;
