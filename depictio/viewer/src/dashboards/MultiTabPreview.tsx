import React, { useState } from 'react';
import {
  AspectRatio,
  Center,
  HoverCard,
  Stack,
  Text,
  ThemeIcon,
  useMantineColorScheme,
} from '@mantine/core';
import { Carousel } from '@mantine/carousel';
import { Icon } from '@iconify/react';

import type { DashboardListEntry } from 'depictio-react-core';

interface MultiTabPreviewProps {
  parent: DashboardListEntry;
  childTabs: DashboardListEntry[];
  /** When omitted, falls back to the current Mantine color scheme. */
  theme?: 'light' | 'dark';
}

interface SlideData {
  id: string;
  title: string;
  icon: string;
  color: string;
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
  return { id: d.dashboard_id, title, icon, color };
}

const SlideImage: React.FC<{
  slide: SlideData;
  theme: 'light' | 'dark';
  iconSize: number;
}> = ({ slide, theme, iconSize }) => {
  const [errored, setErrored] = useState(false);
  if (errored) {
    return (
      <Center h="100%" w="100%" bg="var(--mantine-color-default-hover)">
        <ThemeIcon size={iconSize} variant="light" color={slide.color} radius="md">
          <Icon icon={slide.icon} width={Math.round(iconSize * 0.6)} />
        </ThemeIcon>
      </Center>
    );
  }
  return (
    <img
      key={theme}
      src={`/static/screenshots/${slide.id}_${theme}.png`}
      alt={slide.title}
      loading="lazy"
      decoding="async"
      onError={() => setErrored(true)}
      style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
    />
  );
};

const MultiTabPreview: React.FC<MultiTabPreviewProps> = ({
  parent,
  childTabs,
  theme: themeProp,
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
                <AspectRatio ratio={16 / 10}>
                  <SlideImage slide={slide} theme={theme} iconSize={48} />
                </AspectRatio>
              </Carousel.Slide>
            ))}
          </Carousel>
        </div>
      </HoverCard.Target>
      <HoverCard.Dropdown p="xs" w={520}>
        <Stack gap="xs">
          <Carousel slideSize="100%" slideGap={0} withIndicators controlSize={24}>
            {slides.map((slide) => (
              <Carousel.Slide key={slide.id}>
                <Stack gap={4}>
                  <AspectRatio ratio={16 / 10}>
                    <SlideImage slide={slide} theme={theme} iconSize={64} />
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
              </Carousel.Slide>
            ))}
          </Carousel>
        </Stack>
      </HoverCard.Dropdown>
    </HoverCard>
  );
};

export default MultiTabPreview;
