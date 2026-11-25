import React from 'react';
import { ActionIcon, Alert, Badge, Button, Code, Group, Skeleton, Stack, Text, Tooltip } from '@mantine/core';
import { CircleAlert, Eye, Info, Link2, Link2Off, Moon, RefreshCw, Sun } from 'lucide-react';

import DepictioRose from '../components/rose/DepictioRose';
import { STROKE } from '../chrome/variants/glass/icons';
import type { PreviewScheme } from './previewProtocol';
import type { FrameBridge } from './useFrameBridge';
import type { PreviewJobApi } from './usePreviewJob';

function elapsedLabel(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
}

interface PreviewPaneProps {
  job: PreviewJobApi;
  bridge: FrameBridge;
  /** The app's scheme, which the frame follows. */
  scheme: PreviewScheme;
  /** The column and the frame scroll together. */
  syncScroll: boolean;
  onToggleSync: () => void;
  /** Why this server cannot render the report (no Quarto, renders off), or
   *  null when it can. The pane then explains instead of starting a job. */
  unavailable?: string | null;
}

/** The part of a reason that is a command or a setting, shown as code. */
function UnavailableNotice({ reason }: { reason: string }) {
  const flag = /DEPICTIO_[A-Z_]+/.exec(reason)?.[0];
  const pip = /pip install '[^']+'/.exec(reason)?.[0];
  const text = reason.replace(/:?\s*pip install '[^']+'/, '').replace(/\s*\(DEPICTIO_[A-Z_]+\)/, '');
  return (
    <Alert
      color="gray"
      variant="light"
      icon={<Info size={18} strokeWidth={STROKE} />}
      title="No preview on this server"
      w="100%"
      h="fit-content"
      data-testid="report-preview-unavailable"
    >
      <Stack gap="xs">
        <Text size="sm">{text}</Text>
        {pip && <Code block>{pip}</Code>}
        {flag && <Code block>{`${flag}=true`}</Code>}
        <Text size="sm" c="dimmed">
          The structure on the left still works: captions, order and what goes in the report are
          saved, and every download uses them.
        </Text>
      </Stack>
    </Alert>
  );
}

type ChipProps = Pick<PreviewPaneProps, 'job' | 'bridge'>;

/** The status chip above the frame. */
const StatusChip: React.FC<ChipProps & { unavailable?: string | null }> = ({ job, bridge, unavailable }) => {
  if (unavailable) {
    return (
      <Badge color="gray" variant="light">
        Unavailable
      </Badge>
    );
  }
  if (job.error) {
    return (
      <Badge color="red" variant="light" leftSection={<CircleAlert size={12} strokeWidth={STROKE} />}>
        Preview failed
      </Badge>
    );
  }
  if (job.rerendering) {
    return (
      <Badge color="yellow" variant="light" leftSection={<DepictioRose mode="loading" size={12} label="" />}>
        Re-rendering (filters changed)…
      </Badge>
    );
  }
  if (!job.previewUrl) return null;
  if (bridge.unresponsive) {
    return (
      <Badge color="gray" variant="light">
        Static preview: edits are not applied live
      </Badge>
    );
  }
  if (!bridge.frameReady) {
    return (
      <Badge color="gray" variant="light" leftSection={<DepictioRose mode="loading" size={12} label="" />}>
        Connecting…
      </Badge>
    );
  }
  return (
    <Badge color="green" variant="light" leftSection={<span className="re-live-dot" aria-hidden />}>
      Live
    </Badge>
  );
};

/** The right half of the page: the real report, as a page on a stage, kept in
 *  step with the edits on the left and in the app's own colour scheme. */
const PreviewPane: React.FC<PreviewPaneProps> = ({ job, bridge, scheme, syncScroll, onToggleSync, unavailable }) => (
  <Stack gap={0} h="100%" style={{ minHeight: 0 }} data-testid="report-preview-pane">
    <div className="re-pv-bar">
      <span className="re-pv-name">
        <Eye size={17} strokeWidth={STROKE} aria-hidden />
        Preview
      </span>
      <span data-testid="report-preview-status">
        <StatusChip job={job} bridge={bridge} unavailable={unavailable} />
      </span>
      <span className="re-top-grow" />
      <Tooltip
        label={syncScroll ? 'Scrolling together: click to scroll each side on its own' : 'Scroll the structure and the preview together'}
        withArrow
        openDelay={250}
      >
        <ActionIcon
          variant={syncScroll ? 'light' : 'subtle'}
          color={syncScroll ? undefined : 'gray'}
          size="md"
          radius="xl"
          onClick={onToggleSync}
          aria-pressed={syncScroll}
          aria-label="Scroll sync"
          data-testid="report-scroll-sync"
        >
          {syncScroll ? <Link2 size={16} strokeWidth={STROKE} /> : <Link2Off size={16} strokeWidth={STROKE} />}
        </ActionIcon>
      </Tooltip>
      <Tooltip label={`The preview follows the app theme (${scheme})`} withArrow openDelay={250}>
        <span className="re-pv-scheme" data-testid="report-preview-scheme" data-scheme={scheme}>
          {scheme === 'dark' ? (
            <Moon size={16} strokeWidth={STROKE} aria-hidden />
          ) : (
            <Sun size={16} strokeWidth={STROKE} aria-hidden />
          )}
        </span>
      </Tooltip>
      <Button
        size="compact-sm"
        variant="subtle"
        color="gray"
        leftSection={<RefreshCw size={14} strokeWidth={STROKE} />}
        onClick={job.rerun}
        disabled={job.running || Boolean(unavailable)}
        data-testid="report-preview-rerun"
      >
        Refresh data
      </Button>
    </div>

    <div className="re-pv-stage">
      {unavailable && <UnavailableNotice reason={unavailable} />}

      {!unavailable && job.error && (
        <Alert color="red" title="The preview failed" w="100%" h="fit-content">
          {job.error}
        </Alert>
      )}

      {!unavailable && !job.previewUrl && !job.error && (
        <div className="re-pv-page re-pv-wait">
          <Stack gap="sm" data-testid="report-preview-running">
            <Group gap="xs">
              <DepictioRose mode="loading" size={20} label="" />
              <Text size="sm">
                {job.phase} · {elapsedLabel(job.elapsed)}
              </Text>
            </Group>
            <Skeleton h={36} w="60%" />
            <Skeleton h={14} />
            <Skeleton h={14} w="90%" />
            <Skeleton h={220} />
            <Skeleton h={14} w="80%" />
            <Skeleton h={220} />
          </Stack>
        </div>
      )}

      {job.previewUrl && (
        <div className="re-pv-page" style={{ opacity: job.rerendering ? 0.6 : 1 }}>
          <iframe
            ref={bridge.iframeRef}
            key={job.previewUrl}
            title="Report preview"
            src={job.previewUrl}
            sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
            onLoad={bridge.onFrameLoad}
            data-testid="report-preview-frame"
          />
        </div>
      )}
    </div>
  </Stack>
);

export default PreviewPane;
