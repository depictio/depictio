/**
 * Catalog site: the line diff and the URL arithmetic of the multi-file site.
 *
 * Run: pnpm run check:catalog-site
 */
import {
  currentSlot,
  moduleUrl,
  openInSlotHref,
  outputFileUrl,
  pickSlot,
  siteFileUrl,
  siteRootUrl,
  slotHref,
} from '../src/catalog-preview/siteTree';
import { diffLines, diffRenders, foldUnchanged } from '../src/catalog-preview/lineDiff';

let failures = 0;
function check(label, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  const ok = g === w;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}`);
  if (!ok) {
    console.log(`      got  ${g}\n      want ${w}`);
    failures++;
  }
}
const sig = (ops) => ops.map((o) => `${o.t === 'same' ? ' ' : o.t === 'add' ? '+' : '-'}${o.text}`);

console.log('1. Line diff');
check('identical', sig(diffLines('a\nb\nc', 'a\nb\nc')), [' a', ' b', ' c']);
check('addition', sig(diffLines('a\nc', 'a\nb\nc')), [' a', '+b', ' c']);
check('removal', sig(diffLines('a\nb\nc', 'a\nc')), [' a', '-b', ' c']);
check('modification', sig(diffLines('a\nx: 1\nc', 'a\nx: 2\nc')), [' a', '-x: 1', '+x: 2', ' c']);
check('empty to text', sig(diffLines('', 'a\nb')), ['+a', '+b']);
check('text to empty', sig(diffLines('a\nb\n', '')), ['-a', '-b']);
check('both empty', sig(diffLines('', '')), []);
check('interleaved', sig(diffLines('a\nb\nc\nd', 'b\nx\nd\ne')), ['-a', ' b', '-c', '+x', ' d', '+e']);
check('reconstructs both sides', (() => {
  const a = 'p\nq\nr\ns\nt';
  const b = 'q\nr\nz\nt\nu';
  const ops = diffLines(a, b);
  return [
    ops.filter((o) => o.t !== 'add').map((o) => o.text).join('\n') === a,
    ops.filter((o) => o.t !== 'del').map((o) => o.text).join('\n') === b,
  ];
})(), [true, true]);

console.log('\n2. Pairing renders by index');
const rd = diffRenders(
  [{ index: 'a', _yaml: 'k: 1' }, { index: 'b', _yaml: 'k: 1' }, { index: 'gone', _yaml: 'z: 1' }],
  [{ index: 'a', _yaml: 'k: 1' }, { index: 'b', _yaml: 'k: 2' }, { index: 'new', _yaml: 'n: 1' }],
);
check('statuses', rd.map((r) => `${r.index}:${r.status}`), ['a:same', 'b:changed', 'new:added', 'gone:removed']);
check('changed ops', sig(rd[1].ops), ['-k: 1', '+k: 2']);

console.log('\n3. Folding unchanged lines');
const long = Array.from({ length: 20 }, (_, i) => `l${i}`);
const f = foldUnchanged(diffLines(long.join('\n'), long.map((l) => (l === 'l10' ? 'X' : l)).join('\n')), 2);
check('fold keeps context', f.map((o) => (o.t === 'fold' ? `~${o.count}` : sig([o])[0])),
  ['~8', ' l8', ' l9', '-l10', '+X', ' l11', ' l12', '~7']);

console.log('\n4. URLs');
const at = 'https://h.example/catalog/latest/index.html?theme=dark#output=x';
check('site root', siteRootUrl(at, 'data/').href, 'https://h.example/catalog/');
check('site root without index.html', siteRootUrl('https://h.example/catalog/v1.22.0/', 'data/').href, 'https://h.example/catalog/');
check('versions.json', siteFileUrl(at, 'data/', 'versions.json'), 'https://h.example/catalog/versions.json');
check('module', moduleUrl(at, 'data/', 'ivar'), 'https://h.example/catalog/modules/ivar.json');
check('dataRef -> objects', outputFileUrl({ output: { id: 'o' }, dataRef: 'abc' }, 'data/', at), 'https://h.example/catalog/objects/abc.json');
check('dataRef on the output', outputFileUrl({ output: { id: 'o', dataRef: 'abc' } }, 'data/', at), 'https://h.example/catalog/objects/abc.json');
check('no dataRef -> data/outputs', outputFileUrl({ output: { id: 'o 1' } }, 'data/', at), 'data/outputs/o%201.json');
check('dataBase without slash', outputFileUrl({ output: { id: 'o' } }, 'data', at), 'data/outputs/o.json');
check('root-served site', siteRootUrl('http://localhost:8000/latest/', 'data/').href, 'http://localhost:8000/');
check('slot keeps query and hash', slotHref(at, 'data/', 'v1.22.0', '?theme=dark', '#output=x'), 'https://h.example/catalog/v1.22.0/?theme=dark#output=x');
check('open in slot (output)', openInSlotHref(at, 'data/', 'v1.22.0', 'dark', { output: 'ivar_variants' }), 'https://h.example/catalog/v1.22.0/?theme=dark#output=ivar_variants');
check('open in slot (tool)', openInSlotHref(at, 'data/', 'v1.22.0', undefined, { tool: 'ivar' }), 'https://h.example/catalog/v1.22.0/#tool=ivar');

console.log('\n5. Slots');
const vs = ['v1.23.0', 'v1.22.0'];
check('slot from path', currentSlot('/catalog/v1.22.0/index.html', vs, '1.23.0'), 'v1.22.0');
check('latest', currentSlot('/catalog/latest/', vs, '1.23.0'), 'latest');
check('fallback on index.version', currentSlot('/somewhere/', vs, '1.23.0'), 'v1.23.0');
check('no match', currentSlot('/somewhere/', vs, '9.9.9'), null);
check('no versions', currentSlot('/final/latest/', [], undefined), 'latest');
check('pickSlot newest', pickSlot(['v1.22.0', 'latest'], ['latest', 'v1.23.0', 'v1.22.0']), 'latest');
check('pickSlot unknown order', pickSlot(['v1.22.0'], []), 'v1.22.0');
check('pickSlot none', pickSlot([], []), null);

console.log();
if (failures) {
  console.log(`FAILED (${failures})`);
  process.exit(1);
}
console.log('ALL PASS');
