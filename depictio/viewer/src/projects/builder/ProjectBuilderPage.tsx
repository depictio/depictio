/**
 * The Project Builder: turn a folder of results into a project, by grouping
 * its files into data collections under one or several workflows.
 *
 * One page, two modes (see `mode.ts`):
 *
 * - server (`/projects/build`): the SPA's chrome; the root is a folder of the
 *   server or an `s3://` location; creating goes through `POST
 *   /projects/from_run` with the inline template, a dry run first.
 * - standalone (`depictio project-builder <dir>`): no auth, no sidebar; the
 *   root is the folder the server was started on; the template is written
 *   next to the data for `depictio ingest`.
 *
 * The run-folder wizard hands over a folder it found no template for
 * through sessionStorage (`takeBuilderHandoff`), read once here.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  AppShell,
  Box,
  Button,
  Center,
  Divider,
  Group,
  Loader,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { listProjects, takeBuilderHandoff, useBrandAccents } from 'depictio-react-core';
import type { BuilderHandoff, FromRunReport } from 'depictio-react-core';

import { useAuthMode } from '../../auth/hooks/useAuthMode';
import { usePageTitle } from '../../branding';
import { AppSidebar, ThemeToggle } from '../../chrome';
import BrandLogo from '../../chrome/BrandLogo';
import { useCurrentUser } from '../../hooks/useCurrentUser';
import { RunCreatedModal } from '../fromRun';
import { rememberRunFolder } from '../fromRun/recentFolders';
import { BuilderModeProvider } from './BuilderModeContext';
import { BuilderSteps } from './BuilderSteps';
import type { BuilderMode } from './mode';
import { ServerCreatePanel, StandaloneCreatePanel } from './review/CreatePanel';
import { SourceStep } from './source/SourceStep';
import { useServerRoot } from './source/useServerRoot';
import { useStandaloneRoot } from './source/useStandaloneRoot';
import { useBuilderDraft } from './useBuilderDraft';

const SIDEBAR_KEY = 'project-builder-sidebar-collapsed';
const CREATE_DISABLED_REASON = 'Project creation is disabled in public/demo mode for non-admin users';
const PAGE_HEIGHT = 'calc(100dvh - var(--app-shell-header-offset, 0rem))';

/** The hand-off, read once per page load: StrictMode renders twice, and the
 *  hand-off is removed as it is read. */
let handoffRead = false;
let handoffValue: BuilderHandoff | null = null;
function consumeHandoff(): BuilderHandoff | null {
  if (!handoffRead) {
    handoffRead = true;
    handoffValue = takeBuilderHandoff();
  }
  return handoffValue;
}

/** The app sidebar starts folded here: the builder needs the width. */
function useBuilderSidebar(): [boolean, () => void] {
  const [opened, setOpened] = useState<boolean>(() => {
    try {
      return localStorage.getItem(SIDEBAR_KEY) === 'false';
    } catch {
      return false;
    }
  });
  const toggle = useCallback(() => {
    setOpened((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_KEY, JSON.stringify(!next));
      } catch {
        /* storage off: the choice lasts the page */
      }
      return next;
    });
  }, []);
  return [opened, toggle];
}

const PageLoader: React.FC = () => (
  <Center h={PAGE_HEIGHT}>
    <Loader />
  </Center>
);

// ── Server mode ─────────────────────────────────────────────────────────────

const ServerFlow: React.FC<{
  localDataRootsEnabled: boolean;
  remoteBrowseEnabled: boolean;
  createDisabledReason: string | null;
}> = ({ localDataRootsEnabled, remoteBrowseEnabled, createDisabledReason }) => {
  const accent = useBrandAccents();
  const [handoff] = useState(consumeHandoff);
  const root = useServerRoot({
    localDataRootsEnabled,
    remoteBrowseEnabled,
    // Mirrored server-side: a private bucket's details are refused to
    // non-admins in public mode.
    privateBucketDisabledReason: createDisabledReason
      ? 'Private buckets are disabled in public/demo mode for non-admin users.'
      : null,
    handoff,
  });
  const draft = useBuilderDraft(root.rootSpec?.data_root ?? null);
  const [existingNames, setExistingNames] = useState<string[]>([]);
  const [created, setCreated] = useState<FromRunReport | null>(null);

  useEffect(() => {
    let cancelled = false;
    listProjects()
      .then((projects) => {
        if (!cancelled) setExistingNames(projects.map((p) => p.name).filter(Boolean) as string[]);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const onCreated = (report: FromRunReport) => {
    draft.forget();
    notifications.show({
      color: accent.secondary,
      title: 'Project created',
      message: `“${report.project_name}” is ingesting in the background.`,
      autoClose: 3000,
    });
    setCreated(report);
  };

  return (
    <>
      <BuilderSteps
        rootSpec={root.rootSpec}
        notReadyReason={root.notReadyReason}
        state={draft.state}
        dispatch={draft.dispatch}
        onReset={draft.reset}
        onRootError={root.onRefused}
        onLeaveSource={() => rememberRunFolder(root.trimmed)}
        source={(remote) => (
          <SourceStep
            server={root}
            standalone={null}
            localDataRootsEnabled={localDataRootsEnabled}
            project={draft.state.project}
            dispatch={draft.dispatch}
            remote={remote}
            existingNames={existingNames}
          />
        )}
        create={({ template, templateBlocker, engine }) =>
          root.rootSpec ? (
            <ServerCreatePanel
              root={root.rootSpec}
              template={template}
              templateBlocker={templateBlocker}
              projectName={draft.state.project.name}
              existingNames={existingNames}
              createDisabledReason={createDisabledReason}
              engine={engine}
              onCreated={onCreated}
            />
          ) : null
        }
      />
      {root.browser}
      <RunCreatedModal
        report={created}
        context={{ templateTitle: null, detection: null }}
        onClose={() => {
          const id = created?.project_id;
          window.location.assign(id ? `/projects/${id}` : '/projects');
        }}
      />
    </>
  );
};

const ServerBuilder: React.FC = () => {
  const accent = useBrandAccents();
  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, toggleDesktop] = useBuilderSidebar();
  const { user, localDataRootsEnabled, remoteBrowseEnabled, loading } = useCurrentUser();
  const { status: authStatus, loading: authLoading } = useAuthMode();
  const isPublic = Boolean(authStatus?.is_public_mode);
  const createDisabled = isPublic && !user?.is_admin;

  return (
    <AppShell
      layout="alt"
      header={{ height: 64 }}
      navbar={{
        width: 260,
        breakpoint: 'sm',
        collapsed: { mobile: !mobileOpened, desktop: !desktopOpened },
      }}
      padding={0}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              onClick={toggleMobile}
              hiddenFrom="sm"
              aria-label="Toggle navigation (mobile)"
            >
              <Icon icon="mdi:menu" width={22} />
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              onClick={toggleDesktop}
              visibleFrom="sm"
              aria-label="Toggle navigation"
            >
              <Icon icon="mdi:menu" width={22} />
            </ActionIcon>
            <Icon icon="mdi:folder-cog-outline" width={22} color={`var(--mantine-color-${accent.secondary}-6)`} />
            <Title order={3} c={accent.secondary} data-testid="builder-title">
              Project Builder
            </Title>
          </Group>
          <Button
            component="a"
            href="/projects"
            variant="subtle"
            color="gray"
            leftSection={<Icon icon="mdi:arrow-left" width={16} />}
          >
            Back to Projects
          </Button>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="projects" />
      </AppShell.Navbar>

      <AppShell.Main>
        {loading || authLoading ? (
          <PageLoader />
        ) : (
          <Box h={PAGE_HEIGHT}>
            <ServerFlow
              localDataRootsEnabled={localDataRootsEnabled}
              remoteBrowseEnabled={remoteBrowseEnabled}
              createDisabledReason={createDisabled ? CREATE_DISABLED_REASON : null}
            />
          </Box>
        )}
      </AppShell.Main>
    </AppShell>
  );
};

// ── Standalone ──────────────────────────────────────────────────────────────

const StandaloneFlow: React.FC = () => {
  const root = useStandaloneRoot(true);
  const draft = useBuilderDraft(root.rootSpec?.data_root ?? null);
  let notReadyReason: string | null = null;
  if (root.status === 'loading') notReadyReason = 'Reading the builder context.';
  if (root.status === 'error') notReadyReason = 'The builder server did not answer.';
  return (
    <BuilderSteps
      rootSpec={root.rootSpec}
      notReadyReason={notReadyReason}
      state={draft.state}
      dispatch={draft.dispatch}
      onReset={draft.reset}
      source={(remote) => (
        <SourceStep
          server={null}
          standalone={root}
          localDataRootsEnabled
          project={draft.state.project}
          dispatch={draft.dispatch}
          remote={remote}
          existingNames={[]}
        />
      )}
      create={({ template, templateBlocker, engine }) =>
        root.status === 'ready' ? (
          <StandaloneCreatePanel
            context={root.context}
            template={template}
            templateBlocker={templateBlocker}
            engine={engine}
          />
        ) : null
      }
    />
  );
};

const StandaloneBuilder: React.FC = () => {
  const accent = useBrandAccents();
  return (
    <AppShell header={{ height: 56 }} padding={0}>
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <BrandLogo height={24} />
            <Divider orientation="vertical" my={14} />
            <Title order={3} c={accent.secondary} data-testid="builder-title">
              Project Builder
            </Title>
          </Group>
          <ThemeToggle />
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Box h={PAGE_HEIGHT}>
          <StandaloneFlow />
        </Box>
      </AppShell.Main>
    </AppShell>
  );
};

const ProjectBuilderPage: React.FC<{ mode: BuilderMode }> = ({ mode }) => {
  usePageTitle('Project Builder');
  return (
    <BuilderModeProvider mode={mode}>
      {mode === 'standalone' ? <StandaloneBuilder /> : <ServerBuilder />}
    </BuilderModeProvider>
  );
};

export default ProjectBuilderPage;
