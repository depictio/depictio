import React from 'react';
import { Icon as Iconify } from '@iconify/react';
import {
  ArrowLeft,
  ChartScatter,
  ChevronDown,
  ChevronUp,
  Ellipsis,
  Eraser,
  Eye,
  Funnel,
  ListFilterPlus,
  MessageSquareQuote,
  MessagesSquare,
  PanelLeftClose,
  PenLine,
  Plus,
  Rows3,
  Save,
  Search,
  Settings,
  SlidersHorizontal,
  Waypoints,
  type LucideIcon,
} from 'lucide-react';
import type { ChromeIconName } from 'depictio-react-core';

/**
 * Glass's glyphs: one Lucide family with a hairline stroke and the softer
 * shapes (sliders, a scatter).
 */
const GLASS: Record<ChromeIconName, LucideIcon> = {
  menu: Rows3,
  search: Search,
  add: Plus,
  save: Save,
  edit: PenLine,
  view: Eye,
  settings: Settings,
  feedback: MessageSquareQuote,
  comments: MessagesSquare,
  analysis: ChartScatter,
  filters: SlidersHorizontal,
  reset: Eraser,
  more: Ellipsis,
  moreFilters: ListFilterPlus,
  lessFilters: ChevronUp,
  hide: PanelLeftClose,
  chevronDown: ChevronDown,
  funnel: Funnel,
  funnelView: Waypoints,
  back: ArrowLeft,
};

export const STROKE = 1.6;

export function Glyph({
  slot,
  id,
  size,
  className,
}: {
  slot: ChromeIconName | null | undefined;
  id: string | undefined;
  size: number;
  className?: string;
}) {
  const Lucide = slot ? GLASS[slot] : undefined;
  if (Lucide) {
    return <Lucide size={size} strokeWidth={STROKE} aria-hidden className={className} />;
  }
  if (!id) return null;
  return <Iconify icon={id} width={size} height={size} aria-hidden className={className} />;
}
