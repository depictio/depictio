import React, { useState } from 'react';
import {
  AspectRatio,
  Center,
  HoverCard,
  Stack,
  Text,
  ThemeIcon,
  UnstyledButton,
  useMantineColorScheme,
} from '@mantine/core';
import { Carousel } from '@mantine/carousel';
import { Icon } from '@iconify/react';

import type { DashboardListEntry } from 'depictio-react-core';
import { dashboardHref, dashboardLinkClickHandler } from './lib/dashboardLinks';
import { isImagePath, resolveAssetUrl, screenshotUrl } from './lib/format';
import type { ScreenshotVariant } from './lib/format';

interface MultiTabPreviewProps {
  parent: DashboardListEntry;
  childTabs: DashboardListEntry[];
  /** When omitted, falls back to the current Mantine color scheme. */
  theme?: 'light' | 'dark';
  /** Click handler for a slide — receives that tab's ``dashboard_id`` so
   *  the parent can route to the correct child tab (not just the parent
   *  dashboard). Both the in-card carousel and the hover-popover carousel
   *  trigger this. */
  onTabClick?: (dashboardId: string) => void;
}

interface SlideData {
  id: string;
  title: string;
  icon: string;
  color: string;
  /** Cache-bust key — flips whenever the dashboard is saved, so the
   *  thumbnail re-fetches after the auto-screenshot job overwrites it. */
  version?: string;
}

function toSlide(d: DashboardListEntry, isParent: boolean): SlideData {
  const icon =
    (typeof d.tab_icon === 'string' && d.tab_icon) ||
    (typeof d.icon === 'string' && d.icon) ||
    (isParent ? 'mdi:view-dashboard' : 'mdi:tab');
  const color =
    (typeof d.tab_icon_color === 'string' && d.tab_icon_color) ||
    (typeof d.icon_color === 'string' && d.icon_color) ||
    'orange';
  const title =
    (isParent && typeof d.main_tab_name === 'string' && d.main_tab_name) ||
    (typeof d.title === 'string' && d.title) ||
    d.dashboard_id;
  return { id: d.dashboard_id, title, icon, color, version: d.last_saved_ts };
}

const SlideImage: React.FC<{
  slide: SlideData;
  theme: 'light' | 'dark';
  iconSize: number;
  /** `hidpi` in the hover preview, where the image is shown large enough to
   *  be worth the extra bytes; the carousel inside the card keeps `base`. */
  variant?: ScreenshotVariant;
}> = ({ slide, theme, iconSize, variant = 'base' }) => {
  // The `@2x` capture is missing for tabs shot before it existed, so a failed
  // load steps down to the base one; without any screenshot at all we fall
  // straight back to the tab's colored icon, no generic placeholder between.
  const [fallback, setFallback] = useState<ScreenshotVariant | 'icon'>(variant);
  if (fallback === 'icon') {
    // An image-logo `icon` can't be rendered as an Iconify glyph — show the
    // logo image itself instead of an empty/broken ThemeIcon.
    if (isImagePath(slide.icon)) {
      return (
        <Center h="100%" w="100%" bg="var(--mantine-color-default-hover)">
          <img
            src={resolveAssetUrl(slide.icon)}
            alt={slide.title}
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
        <ThemeIcon size={iconSize} variant="light" color={slide.color} radius="md">
          <Icon icon={slide.icon} width={Math.round(iconSize * 0.6)} />
        </ThemeIcon>
      </Center>
    );
  }
  const src = screenshotUrl(slide.id, theme, slide.version, fallback);
  return (
    <img
      key={src}
      src={src}
      alt={slide.title}
      loading="lazy"
      decoding="async"
      onError={() => setFallback((f) => (f === 'hidpi' ? 'base' : 'icon'))}
      style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
    />
  );
};

const MultiTabPreview: React.FC<MultiTabPreviewProps> = ({
  parent,
  childTabs,
  theme: themeProp,
  onTabClick,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' =
    themeProp ?? (colorScheme === 'dark' ? 'dark' : 'light');
  const captionBg =
    theme === 'dark'
      ? 'var(--mantine-color-dark-6)'
      : 'var(--mantine-color-gray-0)';
  const sortedChildren = [...childTabs].sort(
    (a, b) => (a.tab_order ?? 0) - (b.tab_order ?? 0),
  );
  const slides: SlideData[] = [
    toSlide(parent, true),
    ...sortedChildren.map((c) => toSlide(c, false)),
  ];

  return (
    <HoverCard
      position="right"
      shadow="md"
      withinPortal
      openDelay={150}
      closeDelay={120}
    >
      <HoverCard.Target>
        <div style={{ width: '100%', height: '100%' }}>
          <Carousel
            slideSize="100%"
            slideGap={0}
            withIndicators
            controlSize={20}
            height="100%"
          >
            {slides.map((slide) => (
              <Carousel.Slide key={slide.id}>
                <UnstyledButton
                  component="a"
                  href={dashboardHref(slide.id)}
                  onClick={dashboardLinkClickHandler(
                    onTabClick && (() => onTabClick(slide.id)),
                  )}
                  aria-label={`Open ${slide.title}`}
                  style={{ display: 'block', width: '100%', height: '100%' }}
                >
                  <AspectRatio ratio={16 / 10}>
                    <SlideImage slide={slide} theme={theme} iconSize={48} />
                  </AspectRatio>
                </UnstyledButton>
              </Carousel.Slide>
            ))}
          </Carousel>
        </div>
      </HoverCard.Target>
      {/* Window-relative like the single-dashboard preview, so the enlarged
          slide is actually readable on a wide screen. */}
      <HoverCard.Dropdown p="xs" w="min(1100px, 70vw)">
        <Stack gap="xs">
          <Carousel slideSize="100%" slideGap={0} withIndicators controlSize={28}>
            {slides.map((slide) => (
              <Carousel.Slide key={slide.id}>
                <UnstyledButton
                  component="a"
                  href={dashboardHref(slide.id)}
                  onClick={dashboardLinkClickHandler(
                    onTabClick && (() => onTabClick(slide.id)),
                  )}
                  aria-label={`Open ${slide.title}`}
                  style={{ display: 'block', width: '100%', color: 'inherit' }}
                >
                  <Stack gap={4}>
                    <AspectRatio ratio={16 / 10}>
                      <SlideImage
                        slide={slide}
                        theme={theme}
                        iconSize={72}
                        variant="hidpi"
                      />
                    </AspectRatio>
                    <Text
                      size="sm"
                      fw={500}
                      ta="center"
                      p="xs"
                      bg={captionBg}
                      style={{ borderRadius: 'var(--mantine-radius-sm)' }}
                    >
                      {slide.title}
                    </Text>
                  </Stack>
                </UnstyledButton>
              </Carousel.Slide>
            ))}
          </Carousel>
        </Stack>
      </HoverCard.Dropdown>
    </HoverCard>
  );
};

export default MultiTabPreview;
