/**
 * Minimal, dependency-free YAML syntax highlighter for the generated
 * `depictio_project.yaml` preview. The Project Builder is a single-file offline bundle, so
 * we avoid pulling in a highlighter (highlight.js / shiki); the emitted YAML is
 * regular `yaml.safe_dump` output, which a per-line tokenizer handles cleanly.
 *
 * Colors use CSS `light-dark()` so they read on both the light and dark Code
 * background without a JS theme branch.
 */
import React from 'react';
import { Code } from '@mantine/core';

const S: Record<string, React.CSSProperties> = {
  key: { color: 'light-dark(var(--mantine-color-violet-7), var(--mantine-color-violet-3))' },
  str: { color: 'light-dark(var(--mantine-color-teal-8), var(--mantine-color-teal-3))' },
  num: { color: 'light-dark(var(--mantine-color-orange-8), var(--mantine-color-orange-3))' },
  bool: { color: 'light-dark(var(--mantine-color-grape-7), var(--mantine-color-grape-3))' },
  punct: { color: 'var(--mantine-color-dimmed)' },
  comment: { color: 'var(--mantine-color-dimmed)', fontStyle: 'italic' },
};

/** Style a scalar value by its YAML type (number / bool-null / string). */
function valueStyle(v: string): React.CSSProperties | undefined {
  const t = v.trim();
  if (!t) return undefined;
  if (/^-?\d+(\.\d+)?$/.test(t)) return S.num;
  if (/^(true|false|null|~)$/i.test(t)) return S.bool;
  return S.str;
}

function renderLine(line: string, i: number): React.ReactNode {
  // Whole-line comment.
  if (/^\s*#/.test(line)) {
    return (
      <div key={i} style={S.comment}>
        {line || ' '}
      </div>
    );
  }
  // `key:` or `- key:` with an optional inline value.
  const kv = line.match(/^(\s*)(- )?([A-Za-z0-9_.\-]+)(:)(\s*)(.*)$/);
  if (kv) {
    const [, indent, dash, key, colon, sp, val] = kv;
    return (
      <div key={i}>
        {indent}
        {dash && <span style={S.punct}>{dash}</span>}
        <span style={S.key}>{key}</span>
        <span style={S.punct}>{colon}</span>
        {sp}
        {val && <span style={valueStyle(val)}>{val}</span>}
      </div>
    );
  }
  // Bare list-item scalar, e.g. a filesystem path under `locations:`.
  const li = line.match(/^(\s*)(- )(.*)$/);
  if (li) {
    const [, indent, dash, val] = li;
    return (
      <div key={i}>
        {indent}
        <span style={S.punct}>{dash}</span>
        {val && <span style={valueStyle(val)}>{val}</span>}
      </div>
    );
  }
  return <div key={i}>{line || ' '}</div>;
}

const YamlBlock: React.FC<{ code: string }> = ({ code }) => (
  <Code block style={{ lineHeight: 1.55 }}>
    {code.split('\n').map(renderLine)}
  </Code>
);

export default YamlBlock;
