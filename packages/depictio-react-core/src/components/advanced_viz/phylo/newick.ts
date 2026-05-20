/**
 * Minimal Newick parser. Builds an in-memory tree of `PhyloNode`s.
 *
 * Newick grammar (informal):
 *   tree    := node ';'
 *   node    := '(' children ')' label? (':' length)?
 *           | label? (':' length)?
 *   children := node (',' node)*
 *   label   := unquoted_token | quoted_string
 *
 * Comments in square brackets [...] are skipped. Branch length is optional
 * and defaults to NaN (renderers treat NaN as "no length"). Internal-node
 * labels (after the closing paren) are preserved as `name`.
 */

export interface PhyloNode {
  id: number;
  name: string | null;
  branchLength: number;
  parent: PhyloNode | null;
  children: PhyloNode[];
  // Computed lazily after parsing — number of leaves under this node.
  leafCount?: number;
  // For rendering — assigned by the layout step.
  x?: number;
  y?: number;
  angle?: number;
}

export interface PhyloTree {
  root: PhyloNode;
  leaves: PhyloNode[];
  nodes: PhyloNode[];
}

let _idSeq = 0;

function newNode(name: string | null, len: number, parent: PhyloNode | null): PhyloNode {
  return { id: _idSeq++, name, branchLength: len, parent, children: [] };
}

export function parseNewick(input: string): PhyloTree {
  _idSeq = 0;
  // Strip [comments] and the trailing ';'.
  const src = input.replace(/\[[^\]]*\]/g, '').replace(/\s+/g, '').replace(/;\s*$/, '');
  let i = 0;

  function parseLength(): number {
    if (src[i] !== ':') return NaN;
    i++; // skip ':'
    const start = i;
    while (i < src.length && /[-0-9.eE+]/.test(src[i])) i++;
    const v = parseFloat(src.slice(start, i));
    return Number.isFinite(v) ? v : NaN;
  }

  function parseLabel(): string | null {
    const start = i;
    while (i < src.length && !'(),:;'.includes(src[i])) i++;
    if (i === start) return null;
    let raw = src.slice(start, i);
    if (raw.startsWith("'") && raw.endsWith("'")) raw = raw.slice(1, -1);
    return raw;
  }

  function parseNode(parent: PhyloNode | null): PhyloNode {
    const node = newNode(null, NaN, parent);
    if (src[i] === '(') {
      i++; // skip '('
      while (true) {
        const child = parseNode(node);
        node.children.push(child);
        if (src[i] === ',') {
          i++;
          continue;
        }
        if (src[i] === ')') {
          i++;
          break;
        }
        throw new Error(`Newick parse error at position ${i}: expected ',' or ')'`);
      }
    }
    node.name = parseLabel();
    node.branchLength = parseLength();
    return node;
  }

  const root = parseNode(null);

  // Walk once to collect leaves + assign leaf counts.
  const leaves: PhyloNode[] = [];
  const nodes: PhyloNode[] = [];
  function walk(n: PhyloNode): number {
    nodes.push(n);
    if (n.children.length === 0) {
      n.leafCount = 1;
      leaves.push(n);
      return 1;
    }
    let count = 0;
    for (const c of n.children) count += walk(c);
    n.leafCount = count;
    return count;
  }
  walk(root);

  return { root, leaves, nodes };
}

/** Optional in-place ladderise — order children by their leaf count. */
export function ladderise(tree: PhyloTree, ascending: boolean = true): void {
  function visit(n: PhyloNode): void {
    n.children.sort((a, b) =>
      ascending
        ? (a.leafCount ?? 1) - (b.leafCount ?? 1)
        : (b.leafCount ?? 1) - (a.leafCount ?? 1),
    );
    for (const c of n.children) visit(c);
  }
  visit(tree.root);
  // Re-collect leaves in the new order so y-positions reflect the ladder.
  tree.leaves.length = 0;
  function collect(n: PhyloNode): void {
    if (n.children.length === 0) tree.leaves.push(n);
    else for (const c of n.children) collect(c);
  }
  collect(tree.root);
}

/** Serialise a subtree back to a Newick string (for clade export). */
export function toNewick(root: PhyloNode): string {
  function rec(n: PhyloNode): string {
    let s = '';
    if (n.children.length > 0) {
      s = '(' + n.children.map(rec).join(',') + ')';
    }
    if (n.name != null) s += n.name;
    if (Number.isFinite(n.branchLength)) s += ':' + n.branchLength;
    return s;
  }
  return rec(root) + ';';
}
