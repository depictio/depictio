import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { ArrowRight, Pencil, ScanSearch, X } from 'lucide-react';

import type { DCLink } from 'depictio-react-core';

import { DcTypeIcon } from '../dcTypeIcon';

import { STROKE } from '../../chrome/variants/glass/pages';
import '../../chrome/variants/glass/pages/connections.css';

/** The slice of a data collection the map needs. */
export interface ConnectionDC {
  id: string;
  tag: string;
  type: string;
}

/** One entry of the project's top-level `joins`. The model is tag-keyed
 *  (`left_dc` / `right_dc`, possibly `workflow.tag` scoped); the `dc1` / `dc2`
 *  and `dc_tag1` / `dc_tag2` aliases are tolerated like in the old graph. */
export interface ProjectJoin {
  left_dc?: string;
  right_dc?: string;
  dc1?: string;
  dc2?: string;
  dc_tag1?: string;
  dc_tag2?: string;
  on_columns?: string[];
  how?: string;
  name?: string;
}

interface Edge {
  id: string;
  kind: 'link' | 'join';
  from: string;
  to: string;
  /** Source column of a link, or the joined columns of a join. */
  column: string;
  /** Resolver of a link, join type of a join. */
  how: string;
  enabled: boolean;
  link?: DCLink;
}

interface Node {
  key: string;
  tag: string;
  type: string;
}

type Focus = { kind: 'dc'; key: string } | { kind: 'edge'; id: string } | null;

interface ConnectionsMapProps {
  dataCollections: ConnectionDC[];
  links: DCLink[];
  joins?: ProjectJoin[];
  canMutate: boolean;
  onInspect: (link: DCLink) => void;
  onEdit: (link: DCLink) => void;
}

const sameFocus = (a: Exclude<Focus, null>, b: Exclude<Focus, null>) =>
  a.kind === 'dc' ? b.kind === 'dc' && a.key === b.key : b.kind === 'edge' && a.id === b.id;

const NODE_H = 30;
const NODE_GAP = 8;
const NODE_MAX_W = 232;
/** Narrowest column gap that still leaves the edges room to curve. */
const MIN_COL_GAP = 96;
/** Below this node width the map gives way to the grouped list. */
const MIN_NODE_W = 128;


/** Ranks the connected nodes left to right (a node sits one column after its
 *  furthest source), orders each column by its neighbours, then places them:
 *  the tallest column evenly, the others level with what they connect to. */
function layout(nodes: Node[], edges: Edge[]) {
  const ids = new Set<string>();
  const real = edges.filter((e) => e.from !== e.to);
  real.forEach((e) => {
    ids.add(e.from);
    ids.add(e.to);
  });
  const connected = nodes.filter((n) => ids.has(n.key));

  const preds = new Map<string, string[]>();
  const succs = new Map<string, string[]>();
  real.forEach((e) => {
    preds.set(e.to, [...(preds.get(e.to) ?? []), e.from]);
    succs.set(e.from, [...(succs.get(e.from) ?? []), e.to]);
  });

  // A cycle (a join written both ways, a link back) is cut where the walk
  // meets itself, so the ranking always ends.
  const rank = new Map<string, number>();
  const visiting = new Set<string>();
  const rankOf = (k: string): number => {
    const known = rank.get(k);
    if (known !== undefined) return known;
    visiting.add(k);
    let r = 0;
    (preds.get(k) ?? []).forEach((p) => {
      if (!visiting.has(p)) r = Math.max(r, rankOf(p) + 1);
    });
    visiting.delete(k);
    rank.set(k, r);
    return r;
  };
  connected.forEach((n) => rankOf(n.key));

  const columns: Node[][] = [];
  [...connected]
    .sort(
      (a, b) =>
        (succs.get(b.key)?.length ?? 0) - (succs.get(a.key)?.length ?? 0) ||
        a.tag.localeCompare(b.tag),
    )
    .forEach((n) => {
      const r = rank.get(n.key) ?? 0;
      (columns[r] ??= []).push(n);
    });
  for (let r = 0; r < columns.length; r += 1) columns[r] ??= [];

  const index = new Map<string, number>();
  const reindex = () =>
    columns.forEach((col) => col.forEach((n, i) => index.set(n.key, i)));
  reindex();
  const sweep = (col: Node[], towards: Map<string, string[]>) => {
    const score = (n: Node) => {
      const near = towards.get(n.key) ?? [];
      return near.length
        ? near.reduce((s, k) => s + (index.get(k) ?? 0), 0) / near.length
        : (index.get(n.key) ?? 0);
    };
    const before = new Map(col.map((n) => [n.key, index.get(n.key) ?? 0]));
    col.sort((a, b) => score(a) - score(b) || before.get(a.key)! - before.get(b.key)!);
    reindex();
  };
  for (let pass = 0; pass < 2; pass += 1) {
    for (let r = 1; r < columns.length; r += 1) sweep(columns[r], preds);
    for (let r = columns.length - 2; r >= 0; r -= 1) sweep(columns[r], succs);
  }

  const step = NODE_H + NODE_GAP;
  const tallest = Math.max(1, ...columns.map((c) => c.length));
  const height = tallest * step - NODE_GAP;
  const y = new Map<string, number>();
  columns.forEach((col) => {
    col.forEach((n, i) => y.set(n.key, ((i + 0.5) * height) / col.length - NODE_H / 2));
  });
  // The shorter columns drift towards the middle of their neighbours, never
  // closer than a row apart and never out of the canvas.
  const evenY = new Map(y);
  columns.forEach((col) => {
    if (col.length === tallest) return;
    const want = col.map((n) => {
      const near = [...(preds.get(n.key) ?? []), ...(succs.get(n.key) ?? [])];
      return near.length
        ? near.reduce((s, k) => s + (evenY.get(k) ?? 0), 0) / near.length
        : (evenY.get(n.key) ?? 0);
    });
    const placed = want.map((w) => Math.max(w, 0));
    for (let i = 1; i < placed.length; i += 1) {
      placed[i] = Math.max(placed[i], placed[i - 1] + step);
    }
    const room = height - NODE_H;
    for (let i = placed.length - 1; i >= 0; i -= 1) {
      const cap = i === placed.length - 1 ? room : placed[i + 1] - step;
      placed[i] = Math.max(0, Math.min(placed[i], cap));
    }
    col.forEach((n, i) => y.set(n.key, placed[i]));
  });

  return { columns, rank, y, height };
}

const ConnectionsMap: React.FC<ConnectionsMapProps> = ({
  dataCollections,
  links,
  joins = [],
  canMutate,
  onInspect,
  onEdit,
}) => {
  const hostRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [sel, setSel] = useState<Focus>(null);
  const [hover, setHover] = useState<Focus>(null);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return undefined;
    const read = () => setWidth(Math.floor(el.getBoundingClientRect().width));
    read();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { nodes, edges } = useMemo(() => {
    const byId = new Map(dataCollections.map((d) => [d.id, d]));
    const byTag = new Map<string, ConnectionDC>();
    dataCollections.forEach((d) => {
      if (!byTag.has(d.tag)) byTag.set(d.tag, d);
    });
    const known = new Map<string, Node>(
      dataCollections.map((d) => [d.id, { key: d.id, tag: d.tag, type: d.type }]),
    );
    // A reference is an id, a `tag:<tag>` placeholder (template imports), a
    // bare tag, or a `workflow.tag` scoped tag; unknown ones still get a node.
    const resolve = (idRef?: string, tagRef?: string): string => {
      const direct = idRef ? byId.get(idRef) : undefined;
      if (direct) return direct.id;
      const tag = tagRef || (idRef || '').replace(/^tag:/, '') || '?';
      const hit = byTag.get(tag) ?? byTag.get(tag.split('.').pop() ?? tag);
      if (hit) return hit.id;
      const key = `tag:${tag}`;
      if (!known.has(key)) known.set(key, { key, tag: tag.split('.').pop() ?? tag, type: 'unknown' });
      return key;
    };

    const list: Edge[] = [];
    links.forEach((l) => {
      const src = (l as { source_dc_tag?: string }).source_dc_tag;
      const tgt = (l as { target_dc_tag?: string }).target_dc_tag;
      list.push({
        id: `link:${l.id}`,
        kind: 'link',
        from: resolve(l.source_dc_id, src),
        to: resolve(l.target_dc_id, tgt),
        column: l.source_column,
        how: l.link_config?.resolver || 'direct',
        enabled: l.enabled !== false,
        link: l,
      });
    });
    joins.forEach((j, i) => {
      const left = j.left_dc ?? j.dc_tag1 ?? j.dc1;
      const right = j.right_dc ?? j.dc_tag2 ?? j.dc2;
      if (!left || !right) return;
      list.push({
        id: `join:${j.name ?? i}:${i}`,
        kind: 'join',
        from: resolve(left, left),
        to: resolve(right, right),
        column: (j.on_columns ?? []).join(', '),
        how: j.how || 'inner',
        enabled: true,
      });
    });
    return { nodes: [...known.values()], edges: list };
  }, [dataCollections, links, joins]);

  const plan = useMemo(() => layout(nodes, edges), [nodes, edges]);
  const nodeByKey = useMemo(() => new Map(nodes.map((n) => [n.key, n])), [nodes]);
  const tagOf = (k: string) => nodeByKey.get(k)?.tag ?? k;

  const degree = useMemo(() => {
    const d = new Map<string, number>();
    edges.forEach((e) => {
      if (e.from === e.to) return;
      d.set(e.from, (d.get(e.from) ?? 0) + 1);
      d.set(e.to, (d.get(e.to) ?? 0) + 1);
    });
    return d;
  }, [edges]);

  // Drop a pick whose edge or collection is gone after a refresh.
  useEffect(() => {
    if (sel?.kind === 'edge' && !edges.some((e) => e.id === sel.id)) setSel(null);
  }, [edges, sel]);

  const cols = plan.columns.length;
  const nodeW = cols
    ? Math.min(NODE_MAX_W, Math.floor((width - (cols - 1) * MIN_COL_GAP) / cols))
    : 0;
  const asList = width > 0 && (cols < 2 || nodeW < MIN_NODE_W);
  const colX = (r: number) => (cols > 1 ? (r * (width - nodeW)) / (cols - 1) : 0);

  const act = sel ?? hover;
  const lit = useMemo(() => {
    if (!act) return null;
    const live = new Set<string>();
    const nodesLit = new Set<string>();
    edges.forEach((e) => {
      if (e.from === e.to) return;
      const hit = act.kind === 'edge' ? e.id === act.id : e.from === act.key || e.to === act.key;
      if (!hit) return;
      live.add(e.id);
      nodesLit.add(e.from);
      nodesLit.add(e.to);
    });
    return { edges: live, nodes: nodesLit };
  }, [act, edges]);

  const drawn = edges.filter((e) => e.from !== e.to);
  const alone = dataCollections.filter((d) => !degree.has(d.id));

  // Parallel edges between one pair fan out a few pixels so both stay visible.
  const spread = useMemo(() => {
    const groups = new Map<string, string[]>();
    drawn.forEach((e) => {
      const k = `${e.from}>${e.to}`;
      groups.set(k, [...(groups.get(k) ?? []), e.id]);
    });
    const off = new Map<string, number>();
    groups.forEach((ids) => ids.forEach((id, i) => off.set(id, (i - (ids.length - 1) / 2) * 6)));
    return off;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edges]);

  const geometry = (e: Edge) => {
    const x1 = colX(plan.rank.get(e.from) ?? 0) + nodeW;
    const x2 = colX(plan.rank.get(e.to) ?? 0);
    const o = spread.get(e.id) ?? 0;
    const y1 = (plan.y.get(e.from) ?? 0) + NODE_H / 2 + o;
    const y2 = (plan.y.get(e.to) ?? 0) + NODE_H / 2 + o;
    const dx = Math.max(36, (x2 - x1) / 2);
    return { x1, y1, x2, y2, d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}` };
  };

  const edgeState = (e: Edge) => (!lit ? 'idle' : lit.edges.has(e.id) ? 'on' : 'dim');
  const nodeState = (k: string) => (!lit ? 'idle' : lit.nodes.has(k) ? 'on' : 'dim');
  const isPrimary = (k: string) => act?.kind === 'dc' && act.key === k;

  const edgeLabel = (e: Edge) =>
    e.kind === 'join'
      ? `${tagOf(e.from)} joined with ${tagOf(e.to)} on ${e.column || 'its keys'}`
      : `${tagOf(e.from)} to ${tagOf(e.to)} on ${e.column}, ${e.how}${e.enabled ? '' : ', off'}`;

  const togglePick = (p: Exclude<Focus, null>) =>
    setSel((cur) => (cur && sameFocus(cur, p) ? null : p));

  if (!edges.length) {
    return (
      <p className="cm-empty" data-testid="connections-map">
        Nothing is connected yet. A link lets a filter on one data collection narrow another.
      </p>
    );
  }

  const detailEdges = sel
    ? edges.filter((e) =>
        sel.kind === 'edge' ? e.id === sel.id : e.from === sel.key || e.to === sel.key,
      )
    : [];
  const detailOrder = (e: Edge) =>
    sel?.kind === 'dc' && e.to === sel.key && e.from !== sel.key ? 1 : 0;

  const pills = lit && lit.edges.size > 0 && lit.edges.size <= 3
    ? drawn.filter((e) => lit.edges.has(e.id))
    : [];

  return (
    <div
      className="cm"
      data-testid="connections-map"
      role="group"
      aria-label="Connections between data collections"
      onKeyDown={(e) => {
        if (e.key === 'Escape') setSel(null);
      }}
    >
      <div ref={hostRef} className="cm-host">
        {width > 0 && !asList && (
          <div
            className="cm-canvas"
            style={{ height: plan.height }}
            onClick={() => setSel(null)}
          >
            <svg
              className="cm-svg"
              width={width}
              height={plan.height}
              viewBox={`0 0 ${width} ${plan.height}`}
              aria-hidden
            >
              {[...drawn]
                .sort((a, b) => Number(edgeState(a) === 'on') - Number(edgeState(b) === 'on'))
                .map((e) => {
                  const g = geometry(e);
                  return (
                    <g
                      key={e.id}
                      className="cm-edge"
                      data-kind={e.kind}
                      data-state={edgeState(e)}
                      data-off={!e.enabled || undefined}
                      onMouseEnter={() => setHover({ kind: 'edge', id: e.id })}
                      onMouseLeave={() => setHover(null)}
                      onClick={(ev) => {
                        ev.stopPropagation();
                        togglePick({ kind: 'edge', id: e.id });
                      }}
                    >
                      <path className="cm-hit" d={g.d} />
                      <path className="cm-line" d={g.d} />
                      <circle className="cm-end" cx={g.x2} cy={g.y2} r={3} />
                    </g>
                  );
                })}
            </svg>

            {plan.columns.map((col) =>
              col.map((n) => {
                const picked = sel?.kind === 'dc' && sel.key === n.key;
                return (
                  <button
                    key={n.key}
                    type="button"
                    className="cm-node"
                    data-state={nodeState(n.key)}
                    data-primary={isPrimary(n.key) || undefined}
                    aria-pressed={picked}
                    aria-label={`${n.tag}, ${degree.get(n.key) ?? 0} connections`}
                    title={`${n.tag} (${n.type})`}
                    style={{
                      left: colX(plan.rank.get(n.key) ?? 0),
                      top: plan.y.get(n.key) ?? 0,
                      width: nodeW,
                      height: NODE_H,
                    }}
                    onMouseEnter={() => setHover({ kind: 'dc', key: n.key })}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover({ kind: 'dc', key: n.key })}
                    onBlur={() => setHover(null)}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      togglePick({ kind: 'dc', key: n.key });
                    }}
                  >
                    <DcTypeIcon type={n.type} size={14} withTooltip={false} />
                    <span className="cm-node-tag">{n.tag}</span>
                    <span className="cm-node-count">{degree.get(n.key) ?? 0}</span>
                  </button>
                );
              }),
            )}

            {pills.map((e) => {
              const g = geometry(e);
              return (
                <span
                  key={e.id}
                  className="cm-pill"
                  style={{ left: (g.x1 + g.x2) / 2, top: (g.y1 + g.y2) / 2 }}
                >
                  {e.column || e.how}
                  {e.column && <i>{e.how}</i>}
                </span>
              );
            })}
          </div>
        )}

        {width > 0 && asList && (
          <div className="cm-list">
            {plan.columns
              .flat()
              .filter((n) => drawn.some((e) => e.from === n.key))
              .map((n) => {
                return (
                  <section key={n.key} className="cm-group">
                    <button
                      type="button"
                      className="cm-group-name"
                      aria-pressed={sel?.kind === 'dc' && sel.key === n.key}
                      onClick={() => togglePick({ kind: 'dc', key: n.key })}
                    >
                      <DcTypeIcon type={n.type} size={14} withTooltip={false} />
                      {n.tag}
                    </button>
                    <div className="cm-chips">
                      {drawn
                        .filter((e) => e.from === n.key)
                        .map((e) => (
                          <button
                            key={e.id}
                            type="button"
                            className="cm-chip"
                            data-kind={e.kind}
                            data-off={!e.enabled || undefined}
                            aria-pressed={sel?.kind === 'edge' && sel.id === e.id}
                            aria-label={edgeLabel(e)}
                            onClick={() => togglePick({ kind: 'edge', id: e.id })}
                          >
                            <ArrowRight size={12} strokeWidth={STROKE} aria-hidden />
                            {tagOf(e.to)}
                            {e.column && <small>{e.column}</small>}
                          </button>
                        ))}
                    </div>
                  </section>
                );
              })}
          </div>
        )}
      </div>

      {!asList && (
        <div className="cm-legend" aria-hidden>
          <span className="cm-key" data-kind="link">
            <svg width="28" height="8">
              <line x1="0" y1="4" x2="28" y2="4" />
            </svg>
            Link
          </span>
          <span className="cm-key" data-kind="join">
            <svg width="28" height="8">
              <line x1="0" y1="4" x2="28" y2="4" />
            </svg>
            Join
          </span>
          <span className="cm-key" data-kind="link" data-off>
            <svg width="28" height="8">
              <line x1="0" y1="4" x2="28" y2="4" />
            </svg>
            Off
          </span>
          <span className="cm-legend-hint">Hover a collection to trace its connections</span>
        </div>
      )}

      {alone.length > 0 && (
        <p className="cm-alone">
          Not connected:{' '}
          {alone
            .slice(0, 8)
            .map((d) => d.tag)
            .join(', ')}
          {alone.length > 8 ? ` and ${alone.length - 8} more` : ''}
        </p>
      )}

      {sel && detailEdges.length > 0 && (
        <div className="cm-detail" data-testid="connections-detail">
          <div className="cm-detail-head">
            <b>{sel.kind === 'dc' ? tagOf(sel.key) : 'Connection'}</b>
            <span>
              {detailEdges.length} {detailEdges.length === 1 ? 'connection' : 'connections'}
            </span>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              ml="auto"
              aria-label="Close details"
              onClick={() => setSel(null)}
            >
              <X size={14} strokeWidth={STROKE} aria-hidden />
            </ActionIcon>
          </div>
          <ul className="cm-rows">
            {[...detailEdges]
              .sort((a, b) => detailOrder(a) - detailOrder(b))
              .map((e) => (
                <li
                  key={e.id}
                  className="cm-row"
                  data-off={!e.enabled || undefined}
                  onMouseEnter={() => setHover({ kind: 'edge', id: e.id })}
                  onMouseLeave={() => setHover(null)}
                >
                  <span className="cm-row-path">
                    <b>{tagOf(e.from)}</b>
                    <ArrowRight size={12} strokeWidth={STROKE} aria-hidden />
                    <b>{tagOf(e.to)}</b>
                  </span>
                  {e.column && <code>{e.column}</code>}
                  <span className="cm-row-kind" data-kind={e.kind}>
                    {e.kind === 'join' ? `Join, ${e.how}` : e.how}
                  </span>
                  {!e.enabled && <span className="cm-row-off">Off</span>}
                  {e.link && (
                    <span className="cm-row-actions">
                      <Tooltip label="Inspect mapping" withArrow>
                        <ActionIcon
                          variant="subtle"
                          color="gray"
                          size="sm"
                          aria-label="Inspect mapping"
                          onClick={() => e.link && onInspect(e.link)}
                        >
                          <ScanSearch size={14} strokeWidth={STROKE} aria-hidden />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip label={canMutate ? 'Edit link' : 'Disabled in public/demo mode'} withArrow>
                        <ActionIcon
                          variant="subtle"
                          color="gray"
                          size="sm"
                          aria-label="Edit link"
                          disabled={!canMutate}
                          onClick={() => e.link && onEdit(e.link)}
                        >
                          <Pencil size={14} strokeWidth={STROKE} aria-hidden />
                        </ActionIcon>
                      </Tooltip>
                    </span>
                  )}
                </li>
              ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default ConnectionsMap;
