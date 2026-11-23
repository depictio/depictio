import React, { useState } from 'react';
import { Box, Collapse } from '@mantine/core';
import { ChevronDown } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { STROKE } from '../chrome/variants/glass/icons';

interface CollapsiblePanelProps {
  icon: LucideIcon;
  title: string;
  /** One line shown beside the title while the panel is closed. */
  summary: string;
  defaultOpen?: boolean;
  testId?: string;
  children: React.ReactNode;
}

/** A paper card whose body opens and closes; its summary shows when it is closed. */
const CollapsiblePanel: React.FC<CollapsiblePanelProps> = ({
  icon: Glyph,
  title,
  summary,
  defaultOpen = false,
  testId,
  children,
}) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="re-card" data-open={open || undefined} data-testid={testId}>
      <button
        type="button"
        className="re-card-head"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        data-testid={testId ? `${testId}-toggle` : undefined}
      >
        <span className="re-chip" aria-hidden>
          <Glyph size={17} strokeWidth={STROKE} />
        </span>
        <span className="re-card-title">{title}</span>
        {open ? (
          <span className="re-card-grow" />
        ) : (
          <span className="re-card-summary">{summary}</span>
        )}
        <span className="re-chevron" aria-hidden>
          <ChevronDown size={18} strokeWidth={STROKE} />
        </span>
      </button>
      <Collapse in={open} transitionDuration={220}>
        <Box className="re-card-body">{children}</Box>
      </Collapse>
    </div>
  );
};

export default CollapsiblePanel;
