import React, { useState } from 'react';
import { Collapse, Divider, Group, Text, Title, UnstyledButton } from '@mantine/core';
import { ChevronDown } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { STROKE, useGlassPages } from '../../chrome/variants/glass/pages';

const storageKey = (id: string) => `depictio:project-part:${id}`;

function readOpen(id: string): boolean {
  try {
    return window.localStorage.getItem(storageKey(id)) !== 'closed';
  } catch {
    return true;
  }
}

function writeOpen(id: string, open: boolean): void {
  try {
    window.localStorage.setItem(storageKey(id), open ? 'open' : 'closed');
  } catch {
    // Private window or blocked storage: the part still toggles, it just
    // does not remember.
  }
}

/** One of the project page's major parts (Dashboards, Data): a full-width
 *  head that folds the part away, remembered per viewer. */
export const ProjectPart: React.FC<{
  /** Stable key for the remembered open state, and the test id suffix. */
  id: string;
  icon: LucideIcon;
  title: string;
  /** Short summary beside the title, e.g. "3 dashboards". */
  summary?: React.ReactNode;
  /** Open on mount whatever the viewer last chose (a link to something inside). */
  forceOpen?: boolean;
  children: React.ReactNode;
}> = ({ id, icon: PartIcon, title, summary, forceOpen = false, children }) => {
  const glass = useGlassPages();
  const [open, setOpen] = useState(() => forceOpen || readOpen(id));
  const toggle = () => {
    setOpen((o) => {
      writeOpen(id, !o);
      return !o;
    });
  };
  const bodyId = `project-part-${id}-body`;

  if (glass) {
    return (
      <section className="pd-part" data-open={open || undefined} data-testid={`project-part-${id}`}>
        <button
          type="button"
          className="pd-part-head"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={toggle}
          data-testid={`project-part-${id}-toggle`}
        >
          <span className="pd-part-icon">
            <PartIcon size={20} strokeWidth={STROKE} aria-hidden />
          </span>
          <span className="pd-part-title">{title}</span>
          {summary != null && <span className="pd-part-summary">{summary}</span>}
          <ChevronDown className="pd-part-chevron" size={18} strokeWidth={STROKE} aria-hidden />
        </button>
        <Collapse in={open} id={bodyId}>
          <div className="pd-part-body">{children}</div>
        </Collapse>
      </section>
    );
  }

  return (
    <section data-testid={`project-part-${id}`}>
      <UnstyledButton
        onClick={toggle}
        aria-expanded={open}
        aria-controls={bodyId}
        w="100%"
        py="xs"
        data-testid={`project-part-${id}-toggle`}
      >
        <Group gap="sm" wrap="nowrap">
          <PartIcon size={20} strokeWidth={STROKE} aria-hidden />
          <Title order={3}>{title}</Title>
          {summary != null && (
            <Text size="sm" c="dimmed">
              {summary}
            </Text>
          )}
          <ChevronDown
            size={18}
            strokeWidth={STROKE}
            aria-hidden
            style={{
              marginLeft: 'auto',
              transform: open ? undefined : 'rotate(-90deg)',
              transition: 'transform 150ms ease',
            }}
          />
        </Group>
      </UnstyledButton>
      <Divider mb={open ? 'md' : 0} />
      <Collapse in={open} id={bodyId}>
        {children}
      </Collapse>
    </section>
  );
};
