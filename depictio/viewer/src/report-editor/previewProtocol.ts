/**
 * The messages between this page and the live preview frame (PREVIEW_CONTRACT.md,
 * section 3), and the patch the page builds from the report layer.
 *
 * The frame is the real Quarto report. It cannot be reached except by
 * postMessage (it has an opaque origin), so every text and structure edit goes
 * over as a patch the frame applies to its own document.
 */
import type {
  ReportLayer,
  ReportOrientation,
  ReportOutline,
  ReportTabPlacement,
} from 'depictio-react-core';

import { docToHtml } from './docHtml';
import { buildTabViews } from './model';

export const MSG = {
  ready: 'depictio-preview:ready',
  select: 'depictio-preview:select',
  thumbnail: 'depictio-preview:thumbnail',
  apply: 'depictio-preview:apply',
  thumbnails: 'depictio-preview:thumbnails',
  snapshot: 'depictio-preview:snapshot',
  styles: 'depictio-preview:styles',
  scheme: 'depictio-preview:scheme',
} as const;

/** The colour scheme the frame is asked to show: the app's own. */
export type PreviewScheme = 'light' | 'dark';

/** Thumbnail size asked of the frame. */
export const THUMB_WIDTH = 480;
export const THUMB_HEIGHT = 300;

/** What the frame sends once so the editor can rebuild the report's look
 *  around a snapshot. */
export interface PreviewStyles {
  links: string[];
  css: string;
  htmlClass: string;
  bodyClass: string;
  colorScheme: string;
}

export interface TileFocus {
  tab_id: string;
  component_id: string;
}

export interface PreviewPatch {
  cover: { title: string | null; subtitle: string | null; authors: string[] | null };
  intro_html: string;
  conclusion_html: string;
  tabs: { tab_id: string; order: number | null; placement: ReportTabPlacement }[];
  tiles: {
    tab_id: string;
    component_id: string;
    in_report: boolean;
    in_pdf: boolean;
    orientation: ReportOrientation;
    caption: string | null;
    order: number | null;
    section: string | null;
    page_break_before: boolean;
  }[];
  focus: TileFocus | null;
}

/** The key a tile goes by: the contract's `tile_ref`. */
export function tileKey(tabId: string, componentId: string): string {
  return `${tabId}:${componentId}`;
}

/** What the frame should look like for this layer. `null` in the cover means
 *  "keep the rendered value". */
export function buildPatch(
  layer: ReportLayer,
  outline: ReportOutline,
  focus: TileFocus | null,
): PreviewPatch {
  const cover = layer.cover;
  const tabs = buildTabViews(outline.tabs, layer);
  return {
    cover: {
      title: cover?.title || null,
      subtitle: cover?.subtitle || null,
      authors: cover && cover.authors.length ? cover.authors : null,
    },
    intro_html: docToHtml(layer.intro),
    conclusion_html: docToHtml(layer.conclusion),
    tabs: tabs.map((tab, i) => ({ tab_id: tab.tabId, order: i, placement: tab.placement })),
    tiles: tabs.flatMap((tab) =>
      tab.tiles.map((view, i) => ({
        tab_id: view.tabId,
        component_id: view.componentId,
        in_report: view.inReport,
        in_pdf: view.inPdf,
        orientation: view.orientation,
        caption: view.caption || null,
        order: i,
        section: view.sectionOverride || null,
        page_break_before: view.pageBreakBefore,
      })),
    ),
    focus,
  };
}

/** A frame message, once it has the shape of one of ours. */
export type FrameMessage =
  | { type: typeof MSG.ready; tiles: TileFocus[]; tabs: string[] }
  | { type: typeof MSG.select; tab_id: string; component_id: string }
  | { type: typeof MSG.thumbnail; tab_id: string; component_id: string; data_url: string }
  | { type: typeof MSG.snapshot; tab_id: string; component_id: string; html: string }
  | { type: typeof MSG.styles; styles: PreviewStyles };

const str = (v: unknown): string => (typeof v === 'string' ? v : '');

export function parseFrameMessage(data: unknown): FrameMessage | null {
  if (!data || typeof data !== 'object') return null;
  const m = data as Record<string, unknown>;
  switch (m.type) {
    case MSG.ready:
      return {
        type: MSG.ready,
        tiles: Array.isArray(m.tiles) ? (m.tiles as TileFocus[]) : [],
        tabs: Array.isArray(m.tabs) ? (m.tabs as string[]) : [],
      };
    case MSG.select:
      return typeof m.tab_id === 'string' && typeof m.component_id === 'string'
        ? { type: MSG.select, tab_id: m.tab_id, component_id: m.component_id }
        : null;
    case MSG.thumbnail:
      return typeof m.tab_id === 'string' &&
        typeof m.component_id === 'string' &&
        typeof m.data_url === 'string' &&
        m.data_url.startsWith('data:image/')
        ? {
            type: MSG.thumbnail,
            tab_id: m.tab_id,
            component_id: m.component_id,
            data_url: m.data_url,
          }
        : null;
    case MSG.snapshot:
      return typeof m.tab_id === 'string' &&
        typeof m.component_id === 'string' &&
        typeof m.html === 'string' &&
        m.html
        ? { type: MSG.snapshot, tab_id: m.tab_id, component_id: m.component_id, html: m.html }
        : null;
    case MSG.styles:
      return {
        type: MSG.styles,
        styles: {
          links: Array.isArray(m.links)
            ? m.links.filter((l): l is string => typeof l === 'string')
            : [],
          css: str(m.css),
          htmlClass: str(m.html_class),
          bodyClass: str(m.body_class),
          colorScheme: str(m.color_scheme),
        },
      };
    default:
      return null;
  }
}
