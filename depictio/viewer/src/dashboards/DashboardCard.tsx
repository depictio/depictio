import React, { useState } from 'react';
import {
  ActionIcon,
  AspectRatio,
  Badge,
  Box,
  Card,
  Center,
  Group,
  HoverCard,
  Stack,
  Space,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
  UnstyledButton,
  useMantineColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardListEntry } from 'depictio-react-core';
import MultiTabPreview from './MultiTabPreview';
import DashboardActionsMenu from './DashboardActionsMenu';
import {
  coerceString,
  formatLastSaved,
  isImagePath,
  resolveAssetUrl,
  screenshotUrl,
  screenshotVersion,
} from './lib/format';
import type { ScreenshotVariant } from './lib/format';
import { dashboardHrefFor, dashboardLinkClickHandler } from './lib/dashboardLinks';
import { CARD_BADGES } from './hooks/useDashboardViewPrefs';
import type { CardBadge } from './hooks/useDashboardViewPrefs';
import { formatRelative } from '../lib/datetime';
import { parseTemplateOrigin, TemplateChip } from '../projects/template';
import { useBrandAccents } from 'depictio-react-core';

interface DashboardCardProps {
  dashboard: DashboardListEntry;
  childTabs?: DashboardListEntry[];
  isOwner: boolean;
  projectName?: string;
  /** Raw `template_origin` from the dashboard's owning project (when the
   *  project was instantiated from a template). Renders a TemplateChip
   *  alongside the project badge so users can spot template-derived
   *  dashboards at a glance and follow the chip to the template's docs. */
  projectTemplateOrigin?: unknown;
  /** Badges to render under the title, picked in the toolbar's "Card
   *  display" menu. Every badge when omitted. */
  visibleBadges?: ReadonlySet<CardBadge>;
  pinned?: boolean;
  pinDisabled?: boolean;
  onTogglePin?: () => void;
  onView: (d: DashboardListEntry) => void;
  onEdit: (d: DashboardListEntry) => void;
  onDelete: (d: DashboardListEntry) => void;
  onDuplicate: (d: DashboardListEntry) => void;
  onExport: (d: DashboardListEntry) => void;
}

const ALL_BADGES: ReadonlySet<CardBadge> = new Set(CARD_BADGES);

const SingleThumbnail: React.FC<{
  dashboard: DashboardListEntry;
  theme: 'light' | 'dark';
}> = ({ dashboard, theme }) => {
  const accent = useBrandAccents();
  // No real screenshot yet (freshly created dashboard, or capture failed) →
  // fall straight back to the dashboard's own colored icon. No generic
  // placeholder image in between.
  const [fallback, setFallback] = useState<'none' | 'icon'>('none');
  const icon = coerceString(dashboard.icon, 'mdi:view-dashboard');
  const color = coerceString(dashboard.icon_color, accent.tertiary);

  if (fallback === 'icon') {
    // When the dashboard's "icon" is actually an image logo, show that logo as
    // the thumbnail rather than the generic dashboard glyph. Previously this
    // branch swapped any image path for `mdi:view-dashboard`, so a logo'd
    // dashboard with no screenshot fell back to the default placeholder even
    // though a perfectly good logo was available — render the logo instead.
    if (isImagePath(icon)) {
      return (
        <Center h="100%" w="100%" bg="var(--mantine-color-default-hover)">
          <img
            src={resolveAssetUrl(icon)}
            alt={dashboard.title || dashboard.dashboard_id}
            loading="lazy"
            decoding="async"
            style={{
              maxWidth: '60%',
              maxHeight: '60%',
              objectFit: 'contain',
              display: 'block',
            }}
          />
        </Center>
      );
    }
    return (
      <Center h="100%" w="100%" bg="var(--mantine-color-default-hover)">
        <ThemeIcon size={64} variant="light" color={color} radius="md">
          <Icon icon={icon} width={36} />
        </ThemeIcon>
      </Center>
    );
  }
  return (
    <img
      key={`${theme}-${screenshotVersion(dashboard) ?? ''}-${fallback}`}
      src={screenshotUrl(dashboard.dashboard_id, theme, screenshotVersion(dashboard))}
      alt={dashboard.title || dashboard.dashboard_id}
      loading="lazy"
      decoding="async"
      onError={() => setFallback('icon')}
      style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
    />
  );
};

/** Header icon: workflow-logo image when `dashboard.icon` is a path,
 *  otherwise a filled circular ActionIcon with the Iconify icon. Mirrors
 *  `dashboards_management.py:696-713`. */
const HeaderIcon: React.FC<{ icon: string; color: string }> = ({ icon, color }) => {
  if (isImagePath(icon)) {
    return (
      <img
        src={resolveAssetUrl(icon)}
        alt=""
        style={{
          width: 48,
          height: 48,
          objectFit: 'contain',
          borderRadius: '50%',
          padding: 4,
        }}
      />
    );
  }
  return (
    <ActionIcon color={color} radius="xl" size="lg" variant="filled" aria-hidden>
      <Icon icon={icon} width={24} height={24} />
    </ActionIcon>
  );
};

const DashboardCard: React.FC<DashboardCardProps> = ({
  dashboard,
  childTabs = [],
  isOwner,
  projectName,
  projectTemplateOrigin,
  visibleBadges = ALL_BADGES,
  pinned = false,
  pinDisabled = false,
  onTogglePin,
  onView,
  onEdit,
  onDelete,
  onDuplicate,
  onExport,
}) => {
  const accent = useBrandAccents();
  const parsedTemplate = parseTemplateOrigin(projectTemplateOrigin);
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';

  const dashboardIcon = coerceString(dashboard.icon, 'mdi:view-dashboard');
  const dashboardIconColor = coerceString(dashboard.icon_color, accent.tertiary);
  const subtitle = coerceString(dashboard.subtitle, '');
  const ownerEmail = dashboard.permissions?.owners?.[0]?.email ?? '';
  // Badges carry the short form and their tooltips the full one, so a row of
  // them stays on one or two lines instead of one line per badge.
  const ownerShort = ownerEmail.split('@')[0] || ownerEmail;
  const isPublic = Boolean(dashboard.is_public);
  const lastSavedRaw = coerceString(dashboard.last_saved_ts, '');
  const lastSaved = lastSavedRaw ? formatLastSaved(lastSavedRaw) : 'Never';
  // An empty timestamp doesn't parse, so this falls back to `lastSaved` ('Never').
  const lastSavedRelative = formatRelative(lastSavedRaw, lastSaved);
  const projectId = (dashboard.project_id as string | undefined) || null;
  const titleText = dashboard.title || dashboard.dashboard_id;
  const totalTabs = childTabs.length + 1;
  const hasMultipleTabs = childTabs.length > 0;
  const dashboardHrefStr = dashboardHrefFor(dashboard);
  const handleOpen = dashboardLinkClickHandler(() => onView(dashboard));
  // The preview asks for the `@2x` capture first. Dashboards shot before that
  // file existed only have the base one, hence the step down rather than
  // straight to hiding; and when there is no screenshot at all the card itself
  // is showing its icon fallback, so there is nothing to enlarge and the
  // popover image is suppressed rather than blown up from a placeholder.
  const [previewVariant, setPreviewVariant] = useState<
    ScreenshotVariant | 'hidden'
  >('hidpi');
  const previewSrc =
    previewVariant === 'hidden'
      ? ''
      : screenshotUrl(
          dashboard.dashboard_id,
          theme,
          screenshotVersion(dashboard),
          previewVariant,
        );

  const showProject = Boolean(projectName) && visibleBadges.has('project');
  const showTemplate = parsedTemplate !== null && visibleBadges.has('template');
  const showOwner = Boolean(ownerEmail) && visibleBadges.has('owner');
  const showVisibility = visibleBadges.has('visibility');
  const showModified = visibleBadges.has('modified');
  const showTabs = hasMultipleTabs && visibleBadges.has('tabs');
  const hasBadges =
    showProject ||
    showTemplate ||
    showOwner ||
    showVisibility ||
    showModified ||
    showTabs;

  return (
    <Card
      shadow="sm"
      padding="md"
      radius="md"
      withBorder
      style={{ position: 'relative' }}
      data-tour-id="dashboard-card"
      data-testid="dashboard-card"
      data-dashboard-title={dashboard.title}
    >
      {onTogglePin && (
        <Tooltip
          label={
            pinDisabled
              ? 'Pinning is disabled in public mode'
              : pinned
                ? 'Unpin'
                : 'Pin to top'
          }
          withinPortal
        >
          <ActionIcon
            variant="transparent"
            size="md"
            onClick={onTogglePin}
            disabled={pinDisabled}
            aria-label={pinned ? 'Unpin dashboard' : 'Pin dashboard'}
            style={{
              position: 'absolute',
              top: 8,
              right: 8,
              zIndex: 2,
              // Drop shadow keeps the icon legible against any screenshot.
              filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.4))',
            }}
          >
            <Icon
              icon={pinned ? 'mdi:star' : 'mdi:star-outline'}
              width={20}
              color={
                pinned
                  ? 'var(--mantine-color-yellow-5)'
                  : 'var(--mantine-color-white)'
              }
            />
          </ActionIcon>
        </Tooltip>
      )}

      <Card.Section>
        <AspectRatio ratio={16 / 10}>
          {hasMultipleTabs ? (
            <MultiTabPreview
              parent={dashboard}
              childTabs={childTabs}
              theme={theme}
              onTabClick={(tabDashboardId) => {
                const target =
                  tabDashboardId === dashboard.dashboard_id
                    ? dashboard
                    : (childTabs.find(
                        (t) => t.dashboard_id === tabDashboardId,
                      ) ?? dashboard);
                onView(target);
              }}
            />
          ) : (
            <HoverCard
              position="right"
              openDelay={250}
              closeDelay={100}
              shadow="lg"
              withinPortal
              offset={12}
            >
              <HoverCard.Target>
                <UnstyledButton
                  component="a"
                  href={dashboardHrefStr}
                  onClick={handleOpen}
                  style={{ width: '100%', height: '100%', display: 'block' }}
                  aria-label={`Open ${titleText}`}
                >
                  <SingleThumbnail dashboard={dashboard} theme={theme} />
                </UnstyledButton>
              </HoverCard.Target>
              {previewVariant !== 'hidden' && (
                <HoverCard.Dropdown p={0} style={{ overflow: 'hidden' }}>
                  {/* Sized against the window rather than fixed at 720px: the
                      preview is the only place the full capture is legible, so
                      it takes what the screen can spare, capped where the
                      capture would start being upscaled. */}
                  <Box w="min(1100px, 70vw)">
                    <AspectRatio ratio={16 / 10}>
                      <img
                        key={previewSrc}
                        src={previewSrc}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        onError={() =>
                          setPreviewVariant((v) => (v === 'hidpi' ? 'base' : 'hidden'))
                        }
                        style={{
                          width: '100%',
                          height: '100%',
                          objectFit: 'cover',
                          display: 'block',
                        }}
                      />
                    </AspectRatio>
                  </Box>
                </HoverCard.Dropdown>
              )}
            </HoverCard>
          )}
        </AspectRatio>
      </Card.Section>

      <Space h={10} />

      <Group align="flex-start" wrap="nowrap" gap="sm">
        <HeaderIcon icon={dashboardIcon} color={dashboardIconColor} />
        <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
          <UnstyledButton
            component="a"
            href={dashboardHrefStr}
            onClick={handleOpen}
            style={{ textAlign: 'left', color: 'inherit' }}
          >
            <Title
              order={4}
              style={{
                wordWrap: 'break-word',
                whiteSpace: 'normal',
                marginBottom: 0,
              }}
            >
              {titleText}
            </Title>
          </UnstyledButton>
          {subtitle && (
            <Text size="sm" c="gray">
              {subtitle}
            </Text>
          )}
        </Stack>
        <DashboardActionsMenu
          dashboard={dashboard}
          isOwner={isOwner}
          onView={onView}
          onEdit={onEdit}
          onDelete={onDelete}
          onDuplicate={onDuplicate}
          onExport={onExport}
        />
      </Group>

      {hasBadges && (
        <>
          <Space h={10} />

          <Group gap={4} wrap="wrap">
            {showProject && (
              <Tooltip
                label={projectId ? `Open project: ${projectName}` : `Project: ${projectName}`}
                withinPortal
              >
                <Badge
                  color={accent.secondary}
                  size="sm"
                  component={projectId ? 'a' : 'div'}
                  href={projectId ? `/projects/${projectId}` : undefined}
                  onClick={(e: React.MouseEvent) => e.stopPropagation()}
                  leftSection={<Icon icon="mdi:jira" width={12} color="white" />}
                  rightSection={
                    projectId ? (
                      <Icon icon="mdi:open-in-new" width={10} color="white" />
                    ) : undefined
                  }
                  style={{ maxWidth: '100%', cursor: projectId ? 'pointer' : undefined }}
                >
                  {projectName}
                </Badge>
              </Tooltip>
            )}
            {showTemplate && parsedTemplate && <TemplateChip parsed={parsedTemplate} />}
            {showOwner && (
              <Tooltip label={`Owner: ${ownerEmail}`} withinPortal>
                <Badge
                  color={isOwner ? 'blue' : 'gray'}
                  size="sm"
                  leftSection={<Icon icon="mdi:account" width={12} color="white" />}
                  style={{ maxWidth: '100%' }}
                >
                  {ownerShort}
                </Badge>
              </Tooltip>
            )}
            {showVisibility && (
              <Tooltip label={`Visibility: ${isPublic ? 'Public' : 'Private'}`} withinPortal>
                <Badge
                  color={isPublic ? 'green' : 'grape'}
                  size="sm"
                  leftSection={
                    <Icon
                      icon={isPublic ? 'material-symbols:public' : 'material-symbols:lock'}
                      width={12}
                      color="white"
                    />
                  }
                >
                  {isPublic ? 'Public' : 'Private'}
                </Badge>
              </Tooltip>
            )}
            {showModified && (
              <Tooltip label={`Last modified: ${lastSaved}`} withinPortal>
                <Badge
                  color="gray"
                  variant="light"
                  size="sm"
                  leftSection={<Icon icon="mdi:clock-outline" width={12} />}
                >
                  {lastSavedRelative}
                </Badge>
              </Tooltip>
            )}
            {showTabs && (
              <Badge
                color={accent.tertiary}
                variant="light"
                size="sm"
                leftSection={<Icon icon="mdi:tab" width={12} />}
              >
                {totalTabs} tabs
              </Badge>
            )}
          </Group>
        </>
      )}
    </Card>
  );
};

export default DashboardCard;
