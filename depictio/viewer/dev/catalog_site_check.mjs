/**
 * Catalog site: the line diff and the URL arithmetic of the multi-file site.
 *
 * Run: pnpm run check:catalog-site
 */
import { readFileSync } from 'node:fs';
import {
  currentSlot,
  knownSlots,
  moduleUrl,
  openInSlotHref,
  outputFileUrl,
  pickSlot,
  siteFileUrl,
  siteRootUrl,
  slotHref,
} from '../src/catalog-preview/siteTree';
import { BUMP_COLOR, fetchJsonCached } from '../src/catalog-preview/siteData';
import { diffLines, diffRenders, foldUnchanged } from '../src/catalog-preview/lineDiff';
import { firstRender, groupRenders, renderButtonLabel } from '../src/catalog-preview/renderGroups';

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
check('pickSlot none', pickSlot([], []), null);
check('pickSlot ignores a slot absent from versions.json', pickSlot(['v0.9.0'], ['latest', 'v1.22.0']), null);
check('pickSlot skips the unknown one for the known one', pickSlot(['v0.9.0', 'v1.22.0'], ['latest', 'v1.22.0']), 'v1.22.0');
check('pickSlot with no known slots', pickSlot(['v1.22.0'], []), null);
check('knownSlots with latest', knownSlots({ latest: 'latest', versions: ['v1.22.0'] }), ['latest', 'v1.22.0']);
check('knownSlots with "latest": null', knownSlots({ latest: null, versions: ['v1.22.0'] }), ['v1.22.0']);
check('knownSlots without latest key', knownSlots({ versions: ['v1.22.0'] }), ['v1.22.0']);
check('pickSlot never lands on a null latest', pickSlot(['latest', 'v1.22.0'], knownSlots({ latest: null, versions: ['v1.22.0'] })), 'v1.22.0');

console.log('\n6. Fetch cache: successes and 404 only');
const isAny = (v) => true;
const resp = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
async function cacheCase(label, responses, calls, want) {
  const cache = new Map();
  let n = 0;
  const fetcher = async () => {
    const r = responses[Math.min(n++, responses.length - 1)];
    if (r instanceof Error) throw r;
    return r;
  };
  const out = [];
  for (let i = 0; i < calls; i++) out.push(await fetchJsonCached('u', isAny, cache, fetcher));
  check(label, { out, fetches: n }, want);
}
await cacheCase('success is cached', [resp(200, { a: 1 })], 2, { out: [{ a: 1 }, { a: 1 }], fetches: 1 });
await cacheCase('404 is cached', [resp(404)], 2, { out: [null, null], fetches: 1 });
await cacheCase('network error is retried', [new Error('down'), resp(200, { a: 1 })], 2, { out: [null, { a: 1 }], fetches: 2 });
await cacheCase('HTTP 500 is retried', [resp(500), resp(200, { a: 1 })], 2, { out: [null, { a: 1 }], fetches: 2 });
await cacheCase('concurrent callers share one fetch', [resp(200, { a: 1 })], 1, { out: [{ a: 1 }], fetches: 1 });

console.log('\n7. Bump badge colours');
check('downgrade has a theme colour', BUMP_COLOR.downgrade, 'orange');
check('all bumps coloured', ['major', 'minor', 'patch', 'downgrade'].every((b) => BUMP_COLOR[b]), true);

console.log('\n8. Slot URL without its final slash');
// The redirect is the inline classic script of catalog-site.html (the module cannot
// load without the slash), so run that very script against a fake `location`.
const html = readFileSync('catalog-site.html', 'utf8') // cwd is the viewer dir under pnpm run;
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
check('one inline redirect script', inline.length, 1);
check('no publisher-rewritten asset prefix in it', inline[0].includes('./assets/'), false);
const redirect = (pathname, search = '', hash = '') => {
  let to = null;
  new Function('location', inline[0])({ pathname, search, hash, replace: (u) => { to = u; } });
  return to;
};
check('slot without slash', redirect('/catalog/v1.22.0'), '/catalog/v1.22.0/');
check('keeps query and hash', redirect('/catalog/latest', '?theme=dark', '#output=x'), '/catalog/latest/?theme=dark#output=x');
check('slash already there', redirect('/catalog/latest/'), null);
check('index.html left alone', redirect('/catalog/latest/index.html'), null);
check('other file left alone', redirect('/catalog/latest/page.htm'), null);
check('root', redirect('/'), null);
check('prerelease slot without slash', redirect('/catalog/v1.22.0-rc.1'), '/catalog/v1.22.0-rc.1/');
check('versioned slot, numeric tail', redirect('/catalog/v2.0'), '/catalog/v2.0/');

console.log();
console.log('N. Render switcher groups');
{
  const types = ['card', 'interactive', 'figure', 'table', 'advanced_viz', 'card', 'text'];
  check(
    'plots first, then cards, filters, tables, unknown kinds last',
    groupRenders(types).map((g) => [g.key, g.indices]),
    [['plots', [2, 4]], ['cards', [0, 5]], ['filters', [1]], ['tables', [3]], ['other', [6]]],
  );
  check('opens on the first plot', firstRender(types), 2);
  check('no plot: opens on the first render', firstRender(['card', 'table']), 0);
  check('no render', firstRender([]), 0);
  check('one icon per kind', groupRenders(['figure', 'card']).map((g) => g.icon), ['tabler:chart-bar', 'tabler:number']);
  check('a render is named by its title', renderButtonLabel('Cells per cluster', 'bar'), 'Cells per cluster');
  check('no title: the kind', renderButtonLabel('', 'median'), 'median');
  check('a long title is cut', renderButtonLabel('x'.repeat(50), 'bar').length, 36);
}

console.log();
if (failures) {
  console.log(`FAILED (${failures})`);
  process.exit(1);
}
console.log('ALL PASS');
