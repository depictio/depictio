import React from 'react';
import { Box } from '@mantine/core';
import { STROKE } from '../chrome/variants/glass/icons';
import type { LucideIcon } from 'lucide-react';

interface EditorSectionProps {
  icon: LucideIcon;
  title: string;
  /** One or two short sentences: what this part of the report is. */
  description: string;
  /** Controls on the title row, right of its rule. */
  actions?: React.ReactNode;
  testId?: string;
  children: React.ReactNode;
}

/** A titled group of the edit column: a small-caps title with its glyph, a
 *  hairline, a line of helper text, then its panels. */
const EditorSection: React.FC<EditorSectionProps> = ({
  icon: Glyph,
  title,
  description,
  actions,
  testId,
  children,
}) => (
  <Box component="section" data-testid={testId} aria-label={title}>
    <div className="re-section-head">
      <Glyph size={16} strokeWidth={STROKE} aria-hidden />
      <span className="re-eyebrow">{title}</span>
      <span className="re-rule" aria-hidden />
      {actions}
    </div>
    <p className="re-help">{description}</p>
    <div className="re-section-body">{children}</div>
  </Box>
);

export default EditorSection;
