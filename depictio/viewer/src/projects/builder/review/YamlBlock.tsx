/**
 * A small, dependency-free YAML highlighter for the generated template. The
 * server emits plain `yaml.safe_dump` output, which a per-line tokenizer
 * handles cleanly. Colours use CSS `light-dark()` over theme variables, so
 * they read on both schemes without a JS branch.
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

/** A scalar's style by its YAML type: number, bool or null, string. */
function valueStyle(value: string): React.CSSProperties | undefined {
  const t = value.trim();
  if (!t) return undefined;
  if (/^-?\d+(\.\d+)?$/.test(t)) return S.num;
  if (/^(true|false|null|~)$/i.test(t)) return S.bool;
  return S.str;
}

function renderLine(line: string, i: number): React.ReactNode {
  if (/^\s*#/.test(line)) {
    return (
      <div key={i} style={S.comment}>
        {line || ' '}
      </div>
    );
  }
  // `key:` or `- key:`, with an optional inline value.
  const kv = line.match(/^(\s*)(- )?([A-Za-z0-9_.-]+)(:)(\s*)(.*)$/);
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
  // A bare list item, e.g. a path under `ignore:`.
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
  return <div key={i}>{line || ' '}</div>;
}

export const YamlBlock: React.FC<{ code: string; testId?: string }> = ({ code, testId }) => (
  <Code block style={{ lineHeight: 1.55 }} data-testid={testId}>
    {code.split('\n').map(renderLine)}
  </Code>
);
