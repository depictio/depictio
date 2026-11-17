/**
 * The project page of a static bundle: Depictio's own project page, offline.
 *
 * A bundle has no `/projects/<id>` route. Every link the live app has to the
 * project (the Settings drawer's project link, the sidebar's project row, a
 * `/projects/...` link in a tile) opens this page instead, drawn over the
 * canvas like the Guide: the sidebar and the tab stay where they are, and
 * "Back to <tab>" (or Esc) returns.
 *
 * The page itself is the live one, `ProjectDetailApp`, mounted with an
 * `embed` frame instead of its own shell: the same head, Dashboards and Data
 * parts, workflows, collections table, collection viewer (facts, rows, columns,
 * links, details) and links map. Its reads answer from the manifest through
 * the api shim (`fetchProject`, `listProjectLinks`, `listDashboards`,
 * `fetchDataCollectionPreview` over the bundled Parquet); what needs a server
 * is hidden by `useIsStaticBundle()` and compiled out (projectServerStubs.tsx).
 */
import React, { useEffect } from 'react';
import { ActionIcon, Anchor, Badge, Button, Group, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useCanvasBox } from '../guide';
import ProjectDetailApp from '../projects/detail/ProjectDetailApp';
import { formatExportedAt } from '../chrome/StaticProvenance';
import { rawBundle } from './bundle';

const HEADING_ID = 'bundle-project-heading';

const ProjectPage: React.FC<{ tabName: string; onClose: () => void }> = ({ tabName, onClose }) => {
  const manifest = rawBundle();
  const project = manifest.project;
  const canvasBox = useCanvasBox();

  // Arriving on the page moves focus to its title, as the Guide does. The
  // title is the frame's (known before the project resolves), so it is there
  // on the first frame.
  useEffect(() => {
    document.getElementById(HEADING_ID)?.focus({ preventScroll: true });
  }, []);

  // Esc returns to the tab, unless a menu, dialog or list is what Esc is for.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // Visible ones only: the Settings dialog stays mounted once opened.
      const above = document.querySelectorAll('[role="dialog"], [role="menu"], [role="listbox"]');
      if (Array.from(above).some((el) => el.getClientRects().length > 0)) return;
      // Inside the links map, Esc closes the map's own details.
      if ((e.target as Element | null)?.closest?.('[data-testid="connections-map"]')) return;
      onClose();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  if (!project) return null;

  const exportedAt = formatExportedAt(manifest.provenance?.exported_at ?? manifest.built_at);
  const description = (
    <Group gap="xs" wrap="wrap" component="span">
      {project.description && (
        <Text span inherit>
          {project.description}
        </Text>
      )}
      <Tooltip
        label="A copy taken from a Depictio instance: nothing here is fetched, the figures are those of the export, and editing, ingestion and comments need the live project."
        multiline
        w={300}
        withArrow
      >
        <Badge
          variant="light"
          color="gray"
          radius="sm"
          tt="none"
          leftSection={<Icon icon="mdi:package-variant-closed" width={12} />}
          data-testid="bundle-project-snapshot"
        >
          Static snapshot{exportedAt ? ` · ${exportedAt}` : ''}
        </Badge>
      </Tooltip>
      {project.project_url && (
        <Anchor
          href={project.project_url}
          target="_blank"
          rel="noreferrer"
          size="sm"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          Live project
          <Icon icon="mdi:open-in-new" width={12} />
        </Anchor>
      )}
    </Group>
  );
  const actions = (
    <>
      <Button
        variant="default"
        leftSection={<Icon icon="mdi:arrow-left" width={16} />}
        onClick={onClose}
        visibleFrom="sm"
        data-testid="bundle-project-close"
      >
        Back to {tabName}
      </Button>
      <ActionIcon
        variant="default"
        size="lg"
        onClick={onClose}
        hiddenFrom="sm"
        aria-label={`Back to ${tabName}`}
      >
        <Icon icon="mdi:close" width={18} />
      </ActionIcon>
    </>
  );

  return (
    <div
      className="depictio-guide-layer dc-bundle-project"
      role="region"
      aria-labelledby={HEADING_ID}
      data-testid="bundle-project-page"
      style={
        canvasBox
          ? {
              top: canvasBox.top,
              left: canvasBox.left,
              width: canvasBox.width,
              height: canvasBox.height,
              right: 'auto',
              bottom: 'auto',
              transition: 'none',
            }
          : undefined
      }
    >
      <ProjectDetailApp
        embed={{
          projectId: project.id,
          title: project.name,
          description,
          actions,
          titleProps: { id: HEADING_ID, tabIndex: '-1' },
        }}
      />
    </div>
  );
};

export default ProjectPage;
