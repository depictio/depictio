import React, { useEffect, useState } from 'react';
import { Collapse } from '@mantine/core';

const DURATION_MS = 200;

interface InspectorSlotProps {
  open: boolean;
  children: React.ReactNode;
}

/** Opens its content under a card with a smooth Collapse, and unmounts it
 *  once closed, so only the open inspector costs anything. */
const InspectorSlot: React.FC<InspectorSlotProps> = ({ open, children }) => {
  const [mounted, setMounted] = useState(open);
  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    const timer = window.setTimeout(() => setMounted(false), DURATION_MS + 50);
    return () => window.clearTimeout(timer);
  }, [open]);
  if (!mounted && !open) return null;
  return (
    <Collapse in={open} transitionDuration={DURATION_MS}>
      {children}
    </Collapse>
  );
};

export default InspectorSlot;
