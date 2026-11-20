/**
 * The catalog site's front page: what the catalog is, before the list.
 *
 * The site used to open straight on the list of every output, 471 rows with no
 * word on what a tool, an output or a render is. This page answers that first,
 * as Tool Studio's start screen does for its wizard (and in the same Paper
 * hero and tiles, `bgl-choice` / `bgl-tile` of builder/glass/builder-glass.css):
 * a title and lead with the release's counts, the ways in (browse, search,
 * add a tool), the path every render follows as three tiles, and the tools
 * with the most renders.
 *
 * Shown on the site only (not the single-file gallery, not the editor's picker),
 * and only when the URL names nothing: `#output=`, `#tool=` and `#browse` deep
 * links still open the catalog directly. The rose in the bar comes back here.
 */
import React, { useMemo } from 'react';
import { Button, Group, Select } from '@mantine/core';
import { Icon } from '@iconify/react';
import { ArrowRight, BarChart3, BookOpen, Search, SquarePen } from 'lucide-react';
import LazyOutputView from './OutputView';

import '../builder/glass/builder-glass.css';
import './catalog-landing.css';
import './catalog-kpi.css';
import CatalogHeader, { DOCS_URL, TOOL_STUDIO_URL } from './CatalogHeader';
import ReleaseBar from './ReleaseBar';
import { CATALOG_ACCENT, CATEGORIES, categoryOf, metaFor } from './shared';
import type { ToolEntry } from './shared';
import { isPipeline, isWordmark, TOOL_LOGOS } from './toolMarks';
import catalogIcon from './logos/tools_catalog_icon.webp';


/* "Depictio in numbers", as the docs landing draws it (depictio-docs
 * docs/index.md, .kpi-*): an accent-topped tile, the figure in its accent, an
 * example under it, a link at its foot. Colours are the docs' too. */
const KPI_SEG: Record<string, string> = {
  card: 'var(--cl-teal)',
  advanced_viz: '#d6336c',
  table: 'var(--cl-blue)',
  figure: 'var(--cl-purple)',
  interactive: 'var(--cl-green)',
  multiqc: 'var(--cl-mqc-ink)',
};
/* A thumbnail per advanced visualization, from depictio-docs
 * (docs/images/guides/advanced-visualizations/thumbs), one per theme. */
const VIZ_THUMBS = import.meta.glob('./logos/viz/*.webp', { eager: true, import: 'default' }) as Record<string, string>;
const vizThumb = (kind: string, theme: 'light' | 'dark') => VIZ_THUMBS[`./logos/viz/${kind}_${theme}.webp`];


/** Rows scrolling in turn the opposite way; each prints its list twice so the
 *  loop has no seam (the copy is inert). Same as the docs' `_marquee`. */
function Marquee({ items, rows }: { items: React.ReactNode[]; rows: number }) {
  const size = Math.ceil(items.length / rows);
  return (
    <div className="kpi-marquee">
      {Array.from({ length: rows }, (_, i) => items.slice(i * size, (i + 1) * size))
        .filter((r) => r.length)
        .map((row, i) => (
          <div key={i} className={`kpi-marquee-row${i % 2 ? ' kpi-marquee-reverse' : ''}`}>
            <div className="kpi-marquee-track">
              <ul className="kpi-logos">{row}</ul>
              <ul className="kpi-logos" aria-hidden="true" {...{ inert: "" }}>
                {row}
              </ul>
            </div>
          </div>
        ))}
    </div>
  );
}

const PICKER_URL = 'https://depictio.github.io/depictio-docs/stable/usage/guides/catalog-picker/';

const renderCount = (t: ToolEntry) => t.outputs.reduce((n, o) => n + o.renders.length, 0);





export default function Landing({
  tools,
  onBrowse,
  onOpenOutput,
  onOpenTool,
  onBrowseType,
  onBrowseCategory,
}: {
  tools: ToolEntry[];
  onBrowse: () => void;
  onBrowseType: (type: string) => void;
  onBrowseCategory: (category: string) => void;
  onOpenOutput: (id: string) => void;
  onOpenTool: (id: string) => void;
}) {
  const toolList = useMemo(
    () => tools.filter((t) => !isPipeline(t)).sort((a, b) => renderCount(b) - renderCount(a)),
    [tools],
  );
  const pipelines = useMemo(
    () => tools.filter(isPipeline).sort((a, b) => a.name.localeCompare(b.name)),
    [tools],
  );
  const counts = useMemo(() => {
    let outputs = 0;
    let renders = 0;
    const byType = new Map<string, number>();
    for (const t of tools) {
      outputs += t.outputs.length;
      for (const o of t.outputs)
        for (const r of o.renders) {
          renders += 1;
          const ty = String(r.component_type || 'other');
          byType.set(ty, (byType.get(ty) ?? 0) + 1);
        }
    }
    const types = [...byType.entries()].sort((a, b) => b[1] - a[1]);
    const kinds = new Set<string>();
    for (const t of tools)
      for (const o of t.outputs)
        for (const r of o.renders) if (r.component_type === 'advanced_viz' && r._variant) kinds.add(String(r._variant));
    return { outputs, renders, types, vizKinds: [...kinds].sort() };
  }, [tools]);

  const searchData = useMemo(
    () => [
      {
        group: 'Categories',
        items: CATEGORIES.filter((c) => tools.some((t) => categoryOf(t).id === c.id)).map((c) => ({
          value: `category:${c.id}`,
          label: c.label,
        })),
      },
      { group: 'Tools', items: toolList.map((t) => ({ value: `tool:${t.id}`, label: `${t.name} · ${categoryOf(t).label}` })) },
      { group: 'Pipelines', items: pipelines.map((t) => ({ value: `tool:${t.id}`, label: t.name })) },
      {
        group: 'Outputs',
        items: tools.flatMap((t) =>
          t.outputs.map((o) => ({
            value: `output:${o.output.id}`,
            label: `${t.name} · ${o.output.name || o.output.id}`,
          })),
        ),
      },
    ],
    [tools, toolList, pipelines],
  );
  const pick = (v: string | null) => {
    if (!v) return;
    const i = v.indexOf(':');
    if (v.slice(0, i) === 'category') onBrowseCategory(v.slice(i + 1));
    else if (v.slice(0, i) === 'tool') onOpenTool(v.slice(i + 1));
    else onOpenOutput(v.slice(i + 1));
  };



  return (
    <div className="gp-shell cp-shell" data-testid="catalog-landing">
      <CatalogHeader extras={<ReleaseBar />} />
      <div className="cl-scroll">
        <div className="cl-page">
          <header className="cl-hero">
            <div className="cl-brand">
              <img className="cl-logo" src={catalogIcon} alt="" />
              <h1 className="cl-title">Depictio Tools Catalog</h1>
            </div>
            <p className="cl-lead">
              Ready-made dashboard components for the outputs of bioinformatics tools. Point depictio
              at a pipeline run and every output it recognises becomes a dashboard, with no wiring.
            </p>
            <Select
              className="cl-search"
              size="lg"
              radius="md"
              searchable
              clearable
              placeholder="Find a tool, a pipeline or an output: mosdepth, mag, coverage…"
              leftSection={<Search size={18} strokeWidth={1.8} aria-hidden />}
              rightSection={<span />}
              rightSectionPointerEvents="none"
              data={searchData}
              limit={40}
              value={null}
              onChange={pick}
              nothingFoundMessage="No tool, pipeline or output by that name"
              comboboxProps={{ withinPortal: true }}
              aria-label="Find a tool, a pipeline or an output"
              data-testid="landing-search"
            />
            <Group gap="xs" justify="center">
              <Button size="sm" color={CATALOG_ACCENT} onClick={onBrowse} data-testid="landing-browse"
                rightSection={<ArrowRight size={16} aria-hidden />}>
                Browse the catalog
              </Button>
              <Button size="sm" variant="default" component="a" href={TOOL_STUDIO_URL} target="_blank" rel="noreferrer"
                leftSection={<SquarePen size={15} aria-hidden />}>
                Add a tool
              </Button>
              <Button size="sm" variant="default" component="a" href={DOCS_URL} target="_blank" rel="noreferrer"
                leftSection={<BookOpen size={15} aria-hidden />}>
                Documentation
              </Button>
            </Group>
          </header>

          <section className="kpi-section">
            <h2 className="cl-heading">
              <BarChart3 size={20} aria-hidden /> The catalog in numbers
            </h2>
            <div className="kpi-grid" data-testid="landing-counts">
              <article className="kpi-tile" style={{ ['--kpi-accent' as string]: 'var(--cl-purple)' }}>
                <p className="kpi-figure">
                  <span className="kpi-num">{toolList.length}</span>
                  <span className="kpi-figure-sub">
                    tools · <span className="kpi-num">{counts.outputs}</span> outputs
                  </span>
                </p>
                <h3 className="kpi-label">with ready-made components</h3>
                <div className="kpi-example kpi-tools">
                  <Marquee
                    rows={4}
                    items={toolList.map((t) => {
                      const logo = TOOL_LOGOS[t.id];
                      return (
                        <li key={t.id}>
                          <button
                            type="button"
                            className={`kpi-tool${logo ? ' kpi-tool-logo' : ''}`}
                            title={t.name}
                            onClick={() => onOpenTool(t.id)}
                          >
                            {logo && <img src={logo} alt="" />}
                            {(!logo || !isWordmark(t)) && <span>{t.name}</span>}
                          </button>
                        </li>
                      );
                    })}
                  />
                </div>
                <button type="button" className="kpi-link" onClick={onBrowse}>
                  Browse the tools →
                </button>
              </article>

              <article className="kpi-tile" style={{ ['--kpi-accent' as string]: 'var(--cl-teal)' }}>
                <p className="kpi-figure">
                  <span className="kpi-num">{counts.renders}</span>
                </p>
                <h3 className="kpi-label">ready-made renders</h3>
                <div className="kpi-example">
                  <div className="kpi-bar" role="img" aria-label="Renders by component type">
                    {counts.types.map(([type, n]) => (
                      <span
                        key={type}
                        className="kpi-seg"
                        style={{ width: `${(100 * n) / counts.renders}%`, background: KPI_SEG[type] ?? 'var(--gl-faint)' }}
                        title={`${metaFor(type).name}: ${n}`}
                      />
                    ))}
                  </div>
                  <ul className="kpi-legend">
                    {counts.types.map(([type, n]) => (
                      <li key={type}>
                        <button type="button" onClick={() => onBrowseType(type)} title={`Browse the ${metaFor(type).name} renders`}>
                          <span className="kpi-dot" style={{ background: KPI_SEG[type] ?? 'var(--gl-faint)' }} />
                          <span className="kpi-legend-name">{metaFor(type).name}</span>
                          <b>{n}</b>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
                <button type="button" className="kpi-link" onClick={onBrowse}>
                  See the renders →
                </button>
              </article>

              <article className="kpi-tile" style={{ ['--kpi-accent' as string]: '#d6336c' }}>
                <p className="kpi-figure">
                  <span className="kpi-num">{counts.vizKinds.length}</span>
                </p>
                <h3 className="kpi-label">kinds of advanced visualization</h3>
                <p className="kpi-sub">Each with its own controls and views</p>
                <div className="kpi-example kpi-viz">
                  <Marquee
                    rows={2}
                    items={counts.vizKinds
                      .filter((k) => vizThumb(k, 'light'))
                      .map((k) => (
                        <li key={k}>
                          <button type="button" title={k.replace(/_/g, ' ')} onClick={() => onBrowseType('advanced_viz')}>
                            <img className="kpi-viz-light" src={vizThumb(k, 'light')} alt="" width={112} height={84} loading="lazy" />
                            <img className="kpi-viz-dark" src={vizThumb(k, 'dark')} alt="" width={112} height={84} loading="lazy" />
                          </button>
                        </li>
                      ))}
                  />
                </div>
                <button type="button" className="kpi-link" onClick={() => onBrowseType('advanced_viz')}>
                  Browse them →
                </button>
              </article>
            </div>
          </section>

          {/* "Tools Catalog" as the docs landing draws it (.catalog-landing-*). */}
          <section className="catalog-landing-section">
            <div className="catalog-landing-grid">
              <button type="button" className="catalog-landing-card" onClick={onBrowse}>
                <div className="catalog-landing-icon" style={{ background: 'var(--cl-purple)' }}>
                  <Icon icon="mdi:toolbox-outline" />
                </div>
                <h4>Browse the catalog</h4>
                <p>Every recognised tool, every output, and what each one renders as. Previewed on real fixture data.</p>
                <span className="catalog-landing-link">Open the catalog →</span>
              </button>
              <a className="catalog-landing-card" href={PICKER_URL} target="_blank" rel="noreferrer">
                <div className="catalog-landing-icon" style={{ background: 'var(--cl-teal)' }}>
                  <Icon icon="mdi:rocket-launch-outline" />
                </div>
                <h4>Pick, don't build</h4>
                <p>Adding a component starts with a choice: build it yourself, or pick a pre-configured one the catalog matched to your data.</p>
                <span className="catalog-landing-link">See the picker →</span>
              </a>
              <a className="catalog-landing-card" href={TOOL_STUDIO_URL} target="_blank" rel="noreferrer">
                <div className="catalog-landing-icon" style={{ background: 'var(--cl-pink)' }}>
                  <Icon icon="mdi:wrench-outline" />
                </div>
                <h4>Contribute a tool</h4>
                <p>Tool Studio authors an entry in the browser: drop an output file, bind its columns, and it opens the pull request for you.</p>
                <span className="catalog-landing-link">Open Tool Studio →</span>
              </a>
            </div>
          </section>

          <footer className="cl-foot">
            <span>One catalog per depictio release: pick another from the menu in the bar.</span>
            <span className="cl-foot-links">
              <a href={DOCS_URL} target="_blank" rel="noreferrer">Documentation</a>
              <a href="https://github.com/depictio/depictio/tree/main/depictio/catalog" target="_blank" rel="noreferrer">Source</a>
              <a href={TOOL_STUDIO_URL} target="_blank" rel="noreferrer">Tool Studio</a>
            </span>
          </footer>
        </div>
      </div>
    </div>
  );
}
