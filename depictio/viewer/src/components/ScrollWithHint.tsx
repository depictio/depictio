import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActionIcon, Box } from '@mantine/core';
import { Icon } from '@iconify/react';

/** A scrolling area with an arrow that says there is more below, and goes there. */
export const ScrollWithHint: React.FC<{ mah: string | number; children: React.ReactNode }> = ({
  mah,
  children,
}) => {
  const viewport = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);
  const measure = useCallback(() => {
    const v = viewport.current;
    if (v) setMore(v.scrollHeight - v.scrollTop - v.clientHeight > 8);
  }, []);

  useEffect(() => {
    const v = viewport.current;
    if (!v) return undefined;
    measure();
    // The content grows as sections open and rows arrive.
    const observer = new ResizeObserver(measure);
    observer.observe(v);
    if (v.firstElementChild) observer.observe(v.firstElementChild);
    return () => observer.disconnect();
  }, [measure]);

  return (
    <Box pos="relative">
      <Box ref={viewport} onScroll={measure} mah={mah} style={{ overflowY: 'auto' }}>
        <div>{children}</div>
      </Box>
      {more && (
        <ActionIcon
          variant="default"
          radius="xl"
          size="lg"
          aria-label="Scroll down"
          data-testid="scroll-more"
          style={{ position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)' }}
          onClick={() =>
            viewport.current?.scrollBy({ top: viewport.current.clientHeight * 0.8, behavior: 'smooth' })
          }
        >
          <Icon icon="mdi:chevron-down" width={20} />
        </ActionIcon>
      )}
    </Box>
  );
};

export default ScrollWithHint;
