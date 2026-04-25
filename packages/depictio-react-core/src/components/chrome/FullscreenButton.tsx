import React, { useCallback, useEffect, useState } from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

interface FullscreenButtonProps {
  /** Element that should enter fullscreen — typically the chrome wrapper's body div. */
  fullscreenRef: React.RefObject<HTMLDivElement | null>;
}

/**
 * Toggles native browser fullscreen on the wrapped div. Mirrors the pattern
 * used by `depictio/dash/modules/fullscreen.py:21-107`:
 *   - requestFullscreen / exitFullscreen
 *   - listen for `fullscreenchange` to keep icon state in sync
 *   - dispatch a `resize` event on the next frame so Plotly re-lays out
 */
const FullscreenButton: React.FC<FullscreenButtonProps> = ({ fullscreenRef }) => {
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);

  useEffect(() => {
    const onChange = () => {
      const active = document.fullscreenElement === fullscreenRef.current;
      setIsFullscreen(active);
      // Plotly listens for window resize — give the layout one frame to settle
      // before nudging it, otherwise the figure picks up the pre-fullscreen size.
      requestAnimationFrame(() => {
        window.dispatchEvent(new Event('resize'));
      });
    };
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, [fullscreenRef]);

  const onClick = useCallback(() => {
    const el = fullscreenRef.current;
    if (!el) return;
    if (document.fullscreenElement === el) {
      void document.exitFullscreen();
    } else {
      void el.requestFullscreen?.();
    }
  }, [fullscreenRef]);

  return (
    <Tooltip label="Toggle fullscreen" withArrow>
      <ActionIcon
        variant="light"
        color="indigo"
        size="sm"
        onClick={onClick}
        aria-label="Toggle fullscreen"
      >
        <Icon
          icon={isFullscreen ? 'mdi:fullscreen-exit' : 'mdi:fullscreen'}
          width={16}
          height={16}
        />
      </ActionIcon>
    </Tooltip>
  );
};

export default FullscreenButton;
