/**
 * A tool's mark, shared by the front page and the gallery's tool grid: its
 * logo (copied from depictio-docs, docs/images/landing/logos) when there is
 * one, else a monogram on the tool's own hue; nf-core's mark for a pipeline.
 */
import React from 'react';
import { Icon } from '@iconify/react';

import type { ToolEntry } from './shared';
import './catalog-landing.css';
import toolLogoSources from './logos/tools-sources.json';

/* Logos copied from depictio-docs (docs/images/landing/logos): tools by id,
 * nf-core pipelines by name and theme. A tool without one keeps a monogram. */
export const TOOL_LOGOS = Object.fromEntries(
  Object.entries(
    import.meta.glob('./logos/tools/*.{svg,webp,png}', { eager: true, import: 'default' }) as Record<string, string>,
  ).map(([k, v]) => [k.replace(/^.*\/|\.[a-z]+$/g, ''), v]),
);
const PIPELINE_LOGOS = import.meta.glob('./logos/pipelines/*.webp', {
  eager: true,
  import: 'default',
}) as Record<string, string>;
const isDark = () => document.documentElement.getAttribute('data-mantine-color-scheme') === 'dark';
export function logoFor(tool: ToolEntry): string | undefined {
  if (TOOL_LOGOS[tool.id]) return TOOL_LOGOS[tool.id];
  const m = tool.name.match(/^nf-core\/([a-z0-9]+)/i);
  if (!m) return undefined;
  return PIPELINE_LOGOS[`./logos/pipelines/${m[1].toLowerCase()}_${isDark() ? 'dark' : 'light'}.webp`];
}

/** A pipeline entry (nf-core/…) as opposed to a tool. The index carries no
 *  kind yet, so it is read from the id/name until module.yaml declares one. */
export const isPipeline = (t: ToolEntry) => /^nf-core\//i.test(t.name) || /^nf-core[/_-]/i.test(t.id);

/** A logo that already spells the tool's name (MultiQC, QIIME 2): the name is not repeated. */
export const isWordmark = (t: ToolEntry) =>
  Boolean((toolLogoSources as Record<string, { wordmark?: boolean }>)[t.id]?.wordmark) ||
  (isPipeline(t) && Boolean(logoFor(t)));

const HUES = ['violet', 'blue', 'teal', 'grape', 'indigo', 'cyan', 'pink', 'orange', 'green'];
const hueOf = (id: string) => HUES[[...id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % HUES.length];

/** A tool's mark: its logo when depictio-docs has one, else a monogram on the
 *  tool's own hue (nf-core's mark for a pipeline without one). */
export function ToolMark({ tool, size = 40 }: { tool: ToolEntry; size?: number }) {
  const logo = logoFor(tool);
  if (logo)
    return (
      <span className="cl-mark cl-mark-img" aria-hidden>
        <img src={logo} alt="" style={{ height: size, maxWidth: isPipeline(tool) ? size * 4 : size * 2.4 }} />
      </span>
    );
  const style = {
    width: size,
    height: size,
    fontSize: size * 0.4,
    ['--bgl-tint' as string]: `var(--mantine-color-${hueOf(tool.id)}-6)`,
  } as React.CSSProperties;
  if (isPipeline(tool))
    return (
      <span className="cl-mark" style={style} aria-hidden>
        <Icon icon="simple-icons:nfcore" width={size * 0.55} />
      </span>
    );
  const letters = tool.name.replace(/[^A-Za-z0-9]/g, '').slice(0, 2);
  return (
    <span className="cl-mark" style={style} aria-hidden>
      {letters.charAt(0).toUpperCase() + letters.slice(1).toLowerCase()}
    </span>
  );
}
