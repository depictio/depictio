import { describe, expect, it } from 'vitest';
import { stringToJexlExpression } from '@jbrowse/core/util/jexlStrings';
import SimpleFeature from '@jbrowse/core/util/simpleFeature';

import {
  RANK_TRACK_ID,
  lociCondition,
  namesCondition,
  parseLocus,
  pickCondition,
  pickMatchOf,
  layoutRecordIsPicked,
  heightToShowPicked,
  scrollToShowPicked,
  pickRules,
  pickedLabelValue,
  pickedNumberValue,
  pickedRowMatcher,
  rulesSlotValue,
  pickedSlotValue,
} from './pickedColour';

// Compiled the way a config slot compiles its value, with JBrowse's functions.
const evalOn = (expr: string, feature: unknown) =>
  stringToJexlExpression(expr.startsWith('jexl:') ? expr : `jexl:${expr}`).eval({ feature });

describe('parseLocus', () => {
  it('reads a 1-based locus, separators allowed', () => {
    expect(parseLocus('6:1,001-2,000')).toEqual({ chrom: '6', start: 1001, end: 2000 });
  });
  it('is null for anything else', () => {
    expect(parseLocus('chr2')).toBeNull();
    expect(parseLocus('chr2:9-3')).toBeNull();
  });
});

describe('the pick conditions on real features', () => {
  const variant = (refName: string, start: number) =>
    new SimpleFeature({ uniqueId: `${refName}-${start}`, refName, start, end: start + 1 });
  it('picks the variant at the locus, whatever the chr prefix', () => {
    const cond = lociCondition(['21:10942756-10942756'])!;
    expect(evalOn(cond, variant('chr21', 10942755))).toBe(true);
    expect(evalOn(cond, variant('21', 10942755))).toBe(true);
    expect(evalOn(cond, variant('chr21', 10942800))).toBe(false);
    expect(evalOn(cond, variant('chr2', 10942755))).toBe(false);
  });
  it('picks a transcript by its versioned id, and its exons through it', () => {
    const tx = new SimpleFeature({
      uniqueId: 'tx',
      refName: 'chr6',
      start: 10,
      end: 500,
      name: 'ENST00000211379.5',
      subfeatures: [{ uniqueId: 'ex1', refName: 'chr6', start: 10, end: 50, type: 'exon' }],
    });
    const other = new SimpleFeature({ uniqueId: 'o', refName: 'chr6', start: 10, end: 50, name: 'ENST000002113790' });
    const cond = namesCondition(['ENST00000211379'])!;
    expect(evalOn(cond, tx)).toBe(true);
    expect(evalOn(cond, tx.get('subfeatures')[0])).toBe(true);
    expect(evalOn(cond, other)).toBe(false);
  });
  it('lights the transcripts of a gene named by its symbol', () => {
    const tx = new SimpleFeature({
      uniqueId: 'tx2',
      refName: 'chr1',
      start: 1,
      end: 9,
      name: 'ENST00000999999.1',
      geneName: 'PRDM16',
    });
    expect(evalOn(namesCondition(['PRDM16'])!, tx)).toBe(true);
    expect(evalOn(namesCondition(['PRDM1'])!, tx)).toBe(false);
  });
  it('puts a star in front of a picked name', () => {
    const cond = lociCondition(['chr1:5-5'])!;
    const label = pickedLabelValue(cond, "jexl:get(feature,'name') || get(feature,'id')");
    const named = (start: number) =>
      new SimpleFeature({ uniqueId: `n${start}`, refName: 'chr1', start, end: start + 1, name: 'TPTE' });
    expect(evalOn(label, named(4))).toBe('\u2605 TPTE');
    expect(evalOn(label, named(40))).toBe('TPTE');
    const nameless = new SimpleFeature({ uniqueId: 'v', refName: 'chr1', start: 4, end: 5 });
    expect(evalOn(label, nameless)).toBe('\u2605 ');
  });
  it('wraps the original colour, a literal or an expression', () => {
    const cond = lociCondition(['chr1:5-5'])!;
    const hit = variant('chr1', 4);
    const miss = variant('chr1', 90);
    const literal = pickedSlotValue(cond, '#1971c2', 'goldenrod');
    expect(evalOn(literal, hit)).toBe('#1971c2');
    expect(evalOn(literal, miss)).toBe('goldenrod');
    const expr = pickedSlotValue(cond, '#1971c2', "jexl:get(feature,'start') > 50 ? 'red' : 'blue'");
    expect(evalOn(expr, miss)).toBe('red');
    expect(evalOn(expr, hit)).toBe('#1971c2');
  });
});

describe('pickCondition and pickMatchOf', () => {
  it('is null without a pick or with nothing to match', () => {
    expect(pickCondition(null, 'loci')).toBeNull();
    expect(pickCondition({ loci: [], names: ['A'], keys: [] }, 'loci')).toBeNull();
    expect(pickCondition({ loci: ['1:1-2'], names: [], keys: [] }, 'names')).toBeNull();
  });
  it('matches variants and the rank track by position, features by name', () => {
    expect(pickMatchOf('vcf-1', 'VariantTrack')).toBe('loci');
    expect(pickMatchOf(RANK_TRACK_ID, 'FeatureTrack')).toBe('loci');
    expect(pickMatchOf('hg38-genes', 'FeatureTrack')).toBe('names');
    expect(pickMatchOf('bam-1', 'AlignmentsTrack')).toBeNull();
  });
});

describe('pickedRowMatcher', () => {
  it('needs every key column, with the same values', () => {
    const match = pickedRowMatcher([{ chrom: '21', pos: 10942756 }])!;
    expect(match({ chrom: '21', pos: 10942756, gene: 'X' })).toBe(true);
    expect(match({ chrom: '21', pos: 1 })).toBe(false);
    // A table without `pos` would otherwise light every row of the contig.
    expect(match({ chrom: '21', gene: 'X' })).toBe(false);
  });
  it('matches a transcript id alone when the row has no coordinates', () => {
    const match = pickedRowMatcher([{ transcript_id: 'ENST1' }])!;
    expect(match({ transcript_id: 'ENST1', chrom: null })).toBe(true);
    expect(match({ transcript_id: 'ENST2' })).toBe(false);
  });
  it('is null without keys', () => {
    expect(pickedRowMatcher([])).toBeNull();
    expect(pickedRowMatcher([{}])).toBeNull();
  });
});

describe('layoutRecordIsPicked and heightToShowPicked', () => {
  it('reads the star off a layout record\'s label', () => {
    const rec = (text: string) => [0, 10, 5, 20, { floatingLabels: [{ text }] }];
    expect(layoutRecordIsPicked(rec('\u2605 PROSER2'))).toBe(true);
    expect(layoutRecordIsPicked(rec('Q86WR7'))).toBe(false);
    expect(layoutRecordIsPicked([0, 1, 2, 3])).toBe(false);
  });
  it('grows a track to show a pick below its height, capped', () => {
    expect(heightToShowPicked([300], 100)).toBe(316);
    expect(heightToShowPicked([40], 100)).toBeNull();
    expect(heightToShowPicked([2000], 100)).toBe(320);
    expect(heightToShowPicked([], 100)).toBeNull();
  });
  it('scrolls a track to a pick laid out below what it shows', () => {
    expect(scrollToShowPicked(900, 912, 0, 320)).toBe(876);
    expect(scrollToShowPicked(100, 112, 0, 320)).toBeNull();
    expect(scrollToShowPicked(10, 22, 400, 320)).toBe(0);
  });
});

describe('pickRules: medals and the primary colour', () => {
  const palette = {
    fill: 'blue',
    light: 'lightblue',
    outline: 'navy',
    medals: ['gold', 'silver', 'bronze'],
  };
  const call = (start: number, rank?: number) =>
    new SimpleFeature({ uniqueId: `c${start}`, refName: 'chr21', start, end: start + 1, ...(rank ? { rank } : {}) });
  it('gives the rank track its medals, and a picked call below them the primary colour', () => {
    const picked = { loci: ['21:501-501', '21:11-11'], names: [], keys: [] };
    const { rules, any } = pickRules(picked, 'loci', RANK_TRACK_ID, palette);
    const fill = rulesSlotValue(rules, 'fill', '#868e96');
    const label = rulesSlotValue(rules, 'label', 'black');
    // A medal colours the star and name, never the box, even when picked.
    expect(evalOn(label, call(10, 1))).toBe('gold');
    expect(evalOn(fill, call(10, 1))).toBe('#868e96');
    expect(evalOn(label, call(20, 3))).toBe('bronze');
    expect(evalOn(fill, call(500, 9))).toBe('blue');
    expect(evalOn(fill, call(900, 12))).toBe('#868e96');
    expect(evalOn(any!, call(900, 12))).toBe(false);
    expect(evalOn(pickedNumberValue(any!, 15, 12), call(10, 1))).toBe(15);
  });
  it('gives the best three calls of the opening their medal on a variant track, in order', () => {
    const picked = { loci: ['21:11-11', '21:21-21', '21:31-31', '21:41-41'], names: [], keys: [], medals: true };
    const { rules } = pickRules(picked, 'loci', 'vcf', palette);
    const fill = rulesSlotValue(rules, 'fill', 'goldenrod');
    const label = rulesSlotValue(rules, 'label', 'black');
    expect([10, 20, 30, 40, 50].map((s) => evalOn(label, call(s)))).toEqual([
      'gold',
      'silver',
      'bronze',
      'navy',
      'black',
    ]);
    expect([10, 40, 50].map((s) => evalOn(fill, call(s)))).toEqual(['goldenrod', 'blue', 'goldenrod']);
  });
  it('stars the gene a picked transcript sits under without colouring it', () => {
    const picked = { loci: [], names: ['ENST1'], keys: [], genes: ['BAG6'] };
    const { rules, any } = pickRules(picked, 'names', 'hg38-genes', palette);
    const gene = new SimpleFeature({ uniqueId: 'g', refName: 'chr6', start: 1, end: 9, name: 'BAG6', type: 'gene' });
    expect(evalOn(any!, gene)).toBe(true);
    expect(evalOn(rulesSlotValue(rules, 'fill', 'goldenrod'), gene)).toBe('goldenrod');
  });
  it('paints a pick in the table the primary colour', () => {
    const { rules } = pickRules({ loci: ['21:11-11'], names: [], keys: [] }, 'loci', 'vcf', palette);
    expect(evalOn(rulesSlotValue(rules, 'outline', ''), call(10))).toBe('navy');
  });
});
