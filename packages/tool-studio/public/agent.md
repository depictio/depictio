# Driving Tool Studio from a script or an agent

Tool Studio exposes its whole state on `window.toolStudio`, so nothing needs to be
clicked. The UI follows every call, so a person watching sees what happened.

```js
await toolStudio.ready                       // kinds, catalog and indices loaded

// 1. Load a draft (format depictio-tool-studio/draft@1) …
toolStudio.load({
  format: 'depictio-tool-studio/draft@1',
  tool:   { id: 'mytool', name: 'My Tool', description: '…', homepage: 'https://…',
            stage: 'qc', edam_topics: ['topic_0102'] },
  output: { slug: 'results', path_glob: '**/mytool/*.tsv', name: 'Per-sample results' },
  fixture: { fileName: 'results.tsv', content: 'sample\tvalue\nS1\t3\n' },
  renders: [
    { component: 'card', column: 'value', aggregation: 'average' },
    { component: 'figure', visu_type: 'violin', dict_kwargs: { x: 'sample', y: 'value' } },
    { component: 'advanced_viz', kind: 'volcano',
      roles: { feature_id: 'gene', effect_size: 'log2fc', significance: 'pvalue' } },
  ],
})
// … or catalog files (what the Studio exports, or a committed entry):
toolStudio.loadFiles({ 'mytool/module.yaml': '…', 'mytool/results.yaml': '…', 'mytool/results.tsv': '…' })
await toolStudio.loadZip(blob)

// 2. Check it: the same rules as `depictio dev catalog validate`, as data.
await toolStudio.validateAsync()
// → [{ code: 'render.role_dtype', severity: 'error', path: 'renders[2]',
//      step: 2, message: 'Role "effect_size" expects Float32/Float64, but …' }]

// 3. Export.
toolStudio.exportFiles()        // { 'mytool/module.yaml': '…', 'mytool/results.yaml': '…', … }
await toolStudio.exportZip()    // Blob
await toolStudio.link()         // URL with #draft=… (fixture trimmed to 200 rows)
```

A draft can carry several outputs: `moreOutputs: [{ output, fixture, renders }]`;
`outputs()`, `addOutput()` and `switchOutput(i)` manage them (the steps always
edit the active one).

Other calls: `getDraft()`, `addRender(spec) → uid`, `removeRender(uid)`,
`goTo(0..3)`, `reset()`, `validate()` (synchronous, without the fixture
copy check).

## Stable selectors

`data-testid` on: `start`, `import-entry`, `step-0`…`step-3`, `next`,
`next-missing`, `add-to-output`, `outputs-bar`, `output-tab` (with
`data-slug`), `add-output`, `entry-panel`, `entry-file` (with `data-file`),
`toggle-entry-panel`, `diagnostics` (Export step) and `entry-diagnostics`
(entry panel), both with `data-errors` / `data-warnings`, each `diagnostic`
row (with `data-code`, `data-severity`, `data-path`), `preview-filters`,
`export-anyway`, `download`, `open-pr`, `copy-link`,
`download-draft`, `parse-warnings`.

## Diagnostic codes

| code | meaning |
| --- | --- |
| `identity.*` | description/homepage missing, bad bio.tools/nf-core/source URL, bad version or EDAM id |
| `index.*` | nf-core module or EDAM term not in the vendored index |
| `find.*` | no path glob or file name |
| `fixture.*` | missing, no data rows, parse problems (warning), byte-identical to another tool's |
| `schema.module`, `schema.output` | the generated YAML fails the catalog JSON Schema |
| `render.*` | unbound column, role/dtype mismatch, role shape, card layout, id collisions |
| `renders.empty` | no visualization yet |

`depictio dev catalog validate` in CI stays the authoritative check; CI also
proves that every error code above is one the CLI rejects too.
