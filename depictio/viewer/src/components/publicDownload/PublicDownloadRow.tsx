import React, { useState } from 'react';
import { Switch } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Download } from 'lucide-react';
import { setPublicOfflineDownload } from 'depictio-react-core';
import PublicDownloadPreviewModal from './PublicDownloadPreviewModal';

/**
 * The owner's switch for the visitors' offline copy of a public project
 * (#1480), beside visibility on the Permissions page. Disabled, with the
 * reason, while the project is private. Turning it on opens the preview of
 * what the file holds and needs it reviewed; turning it off is immediate and
 * deletes the copies.
 *
 * `variant="glass"` renders as a `.pm-visibility` row (Paper chrome), the
 * default as a Mantine `Switch` with label and description.
 */
const PublicDownloadRow: React.FC<{
  projectId: string;
  projectName?: string;
  isPublic: boolean;
  enabled: boolean;
  canManage: boolean;
  /** Editing is locked (a published project) and the reader is not an admin. */
  lockedForMe?: boolean;
  variant?: 'glass' | 'classic';
  iconStroke?: number;
  onChanged: (enabled: boolean) => void;
}> = ({
  projectId,
  projectName,
  isPublic,
  enabled,
  canManage,
  lockedForMe = false,
  variant = 'classic',
  iconStroke,
  onChanged,
}) => {
  const [previewOpen, setPreviewOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const apply = async (next: boolean) => {
    setBusy(true);
    try {
      const res = await setPublicOfflineDownload(projectId, next, next);
      onChanged(res.public_offline_download);
      setPreviewOpen(false);
      notifications.show({
        color: 'teal',
        title: next ? 'Offline copy offered to visitors' : 'Offline copy withdrawn',
        message: next
          ? 'Each dashboard is being built; visitors find it under Settings › Export.'
          : 'Visitors can no longer download it, and the copies were deleted.',
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Offline download not changed',
        message: (err as Error).message,
      });
    } finally {
      setBusy(false);
    }
  };

  const onToggle = (checked: boolean) => {
    if (checked) setPreviewOpen(true);
    else void apply(false);
  };

  const title = 'Offline copy for visitors';
  const text = !isPublic
    ? 'Only a public project can offer it. Make the project public first.'
    : lockedForMe
      ? `${enabled ? 'Visitors can download each dashboard as one HTML file that works offline.' : 'Visitors cannot download an offline copy.'} Editing is locked: only an administrator can change it.`
      : enabled
      ? 'Visitors can download each dashboard as one HTML file that works offline.'
      : 'Let visitors download each dashboard as one HTML file that works offline. You see what it holds before turning it on.';
  const disabled = !canManage || !isPublic || lockedForMe || busy;
  const checked = enabled && isPublic;

  const modal = (
    <PublicDownloadPreviewModal
      opened={previewOpen}
      projectId={projectId}
      projectName={projectName}
      busy={busy}
      onClose={() => setPreviewOpen(false)}
      onConfirm={() => void apply(true)}
    />
  );

  if (variant === 'glass') {
    return (
      <div className="pm-visibility" data-testid="project-public-download-row">
        <span className="pm-chip">
          <Download size={20} strokeWidth={iconStroke} aria-hidden />
        </span>
        <div className="pm-visibility-body">
          <div className="pm-visibility-title">{title}</div>
          <div className="pm-visibility-text">{text}</div>
        </div>
        <Switch
          checked={checked}
          onChange={(e) => onToggle(e.currentTarget.checked)}
          disabled={disabled}
          aria-label={title}
          data-testid="project-public-download-switch"
        />
        {modal}
      </div>
    );
  }
  return (
    <>
      <Switch
        mt="xs"
        label={title}
        description={text}
        checked={checked}
        onChange={(e) => onToggle(e.currentTarget.checked)}
        disabled={disabled}
        data-testid="project-public-download-switch"
      />
      {modal}
    </>
  );
};

export default PublicDownloadRow;
