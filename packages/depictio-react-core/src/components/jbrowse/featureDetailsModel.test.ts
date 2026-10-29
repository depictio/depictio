import { describe, expect, it } from 'vitest';

import {
  buildFeatureView,
  buildGenotypes,
  countSubfeatures,
  decodeFlags,
  formatConsequence,
  formatFrequency,
  formatLocus,
  formatNumber,
  formatRankScore,
  isFeatureWidgetType,
  parseAnnotationFormat,
  parseAnnotations,
  parseGeneticModels,
  zygosityOf,
} from './featureDetailsModel';

const CSQ_DESC =
  'Consequence annotations from Ensembl VEP. Format: Allele|Consequence|IMPACT|SYMBOL|Gene|HGVSc|HGVSp';

describe('widget types', () => {
  it('knows the feature widgets and nothing else', () => {
    expect(isFeatureWidgetType('BaseFeatureWidget')).toBe(true);
    expect(isFeatureWidgetType('VariantFeatureWidget')).toBe(true);
    expect(isFeatureWidgetType('AlignmentsFeatureWidget')).toBe(true);
    expect(isFeatureWidgetType('AboutWidget')).toBe(false);
    expect(isFeatureWidgetType(undefined)).toBe(false);
  });
});

describe('number formats', () => {
  it('groups integers and trims decimals', () => {
    expect(formatNumber(1234567)).toBe('1,234,567');
    expect(formatNumber(14)).toBe('14');
    expect(formatNumber(12.3456)).toBe('12.35');
    expect(formatNumber(0.12345)).toBe('0.1235');
  });
  it('writes frequencies below 0.001 in scientific notation', () => {
    expect(formatFrequency(0.00012)).toBe('1.2e-4');
    expect(formatFrequency(0.0001)).toBe('1e-4');
    expect(formatFrequency(0.0123)).toBe('0.0123');
    expect(formatFrequency(0.5)).toBe('0.5');
    expect(formatFrequency(0)).toBe('0');
  });
  it('formats a locus 1-based with separators', () => {
    expect(formatLocus('chr1', 1233, 5678)).toBe('chr1:1,234-5,678');
    expect(formatLocus('chr1', 999, 1000)).toBe('chr1:1,000');
  });
});

describe('annotations', () => {
  it('reads the field order from the VCF header', () => {
    expect(parseAnnotationFormat({ INFO: { CSQ: { Description: CSQ_DESC } } }, 'CSQ')).toEqual([
      'Allele', 'Consequence', 'IMPACT', 'SYMBOL', 'Gene', 'HGVSc', 'HGVSp',
    ]);
    expect(
      parseAnnotationFormat(
        { INFO: { ANN: { Description: "Functional annotations: 'Allele | Annotation | Annotation_Impact'" } } },
        'ANN',
      ),
    ).toEqual(['Allele', 'Annotation', 'Annotation_Impact']);
    expect(parseAnnotationFormat({ INFO: { CSQ: { Description: 'no format' } } }, 'CSQ')).toBeUndefined();
    expect(parseAnnotationFormat(undefined, 'CSQ')).toBeUndefined();
  });

  it('parses VEP entries with the header order, deduplicated and most severe first', () => {
    const fields = ['Allele', 'Consequence', 'IMPACT', 'SYMBOL', 'Gene', 'HGVSc', 'HGVSp'];
    const rows = parseAnnotations(
      [
        'T|intron_variant|MODIFIER|NOTCH3|ENSG1|ENST1.1:c.10+5A>T|',
        'T|missense_variant&splice_region_variant|MODERATE|NOTCH3|ENSG1|ENST2.3:c.100A>T|ENSP2.1:p.Lys34Met',
        'T|intron_variant|MODIFIER|NOTCH3|ENSG1|ENST1.1:c.10+5A>T|',
      ],
      'CSQ',
      fields,
    );
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      gene: 'NOTCH3',
      consequence: 'missense variant, splice region variant',
      impact: 'MODERATE',
      impactTone: 'orange',
      hgvsc: 'c.100A>T',
      hgvsp: 'p.Lys34Met',
      hgvspFull: 'ENSP2.1:p.Lys34Met',
    });
    expect(rows[1].impact).toBe('MODIFIER');
  });

  it('falls back to the standard VEP and snpEff orders without a header', () => {
    const vep = parseAnnotations(
      ['A|stop_gained|HIGH|BRCA1|ENSG2|Transcript|ENST3|protein_coding|3/20||ENST3:c.1A>T|ENSP3:p.Gln1Ter'],
      'CSQ',
    );
    expect(vep[0]).toMatchObject({ gene: 'BRCA1', consequence: 'stop gained', impact: 'HIGH', hgvsc: 'c.1A>T' });
    const ann = parseAnnotations(
      ['A|missense_variant|MODERATE|TP53|ENSG3|transcript|ENST4|protein_coding|2/11|c.5G>A|p.Arg2Gln'],
      'ANN',
    );
    expect(ann[0]).toMatchObject({ gene: 'TP53', impact: 'MODERATE', hgvsc: 'c.5G>A', hgvsp: 'p.Arg2Gln' });
  });

  it('writes consequences as words', () => {
    expect(formatConsequence('splice_acceptor_variant&intron_variant')).toBe('splice acceptor variant, intron variant');
  });
});

describe('inheritance and scores', () => {
  it('turns GeneticModels into chips', () => {
    const chips = parseGeneticModels(['fam1:AR_comp|AD', 'fam1:AD_dn']);
    expect(chips.map((c) => c.text)).toEqual(['Compound heterozygous', 'Dominant', 'Dominant, de novo']);
    expect(chips[2].tone).toBe('red');
    expect(parseGeneticModels(['fam:AR_hom|XR|XD'])[0].text).toBe('Recessive');
    expect(parseGeneticModels(['fam:NA'])).toEqual([]);
  });

  it('merges families sharing a model into one chip hint', () => {
    const chips = parseGeneticModels(['a:AD', 'b:AD']);
    expect(chips).toHaveLength(1);
    expect(chips[0].hint).toBe('a, b');
  });

  it('reads the rank score off its family prefix', () => {
    expect(formatRankScore(['fam:14.0'])).toBe('14');
    expect(formatRankScore(['a:14.0', 'b:9.5'])).toBe('a 14, b 9.5');
    expect(formatRankScore([7])).toBe('7');
    expect(formatRankScore(undefined)).toBeUndefined();
  });
});

describe('genotypes', () => {
  it('classifies zygosity', () => {
    expect(zygosityOf('0/0')).toBe('homref');
    expect(zygosityOf('0|0')).toBe('homref');
    expect(zygosityOf('0/1')).toBe('het');
    expect(zygosityOf('1|0')).toBe('het');
    expect(zygosityOf('1/2')).toBe('het');
    expect(zygosityOf('1/1')).toBe('homalt');
    expect(zygosityOf('./.')).toBe('nocall');
    expect(zygosityOf('.')).toBe('nocall');
  });

  it('builds a row per sample with depth, quality, allele depth and VAF', () => {
    const rows = buildGenotypes({
      proband: { GT: ['0/1'], DP: [40], GQ: [99], AD: [30, 10] },
      mother: { GT: ['0/0'], DP: [2000], GQ: [60], AD: [2000, 0] },
      father: { GT: ['./.'] },
    });
    expect(rows.map((r) => r.sample)).toEqual(['proband', 'mother', 'father']);
    expect(rows[0]).toMatchObject({ zygosityLabel: 'Het', dp: '40', gq: '99', ad: '30,10', vaf: '25%' });
    expect(rows[1]).toMatchObject({ zygosityLabel: 'Hom ref', dp: '2,000', vaf: '0%' });
    expect(rows[2]).toMatchObject({ zygosityLabel: 'No call', ad: '', vaf: '' });
  });
});

describe('alignment flags', () => {
  it('decodes the bits to words', () => {
    expect(decodeFlags(99)).toEqual(['paired', 'proper pair', 'mate reverse strand', 'first in pair']);
    expect(decodeFlags(1024 | 1)).toEqual(['paired', 'duplicate']);
    expect(decodeFlags(0)).toEqual([]);
  });
});

describe('buildFeatureView: variant', () => {
  const feature = {
    uniqueId: 'abc',
    refName: '19',
    CHROM: '19',
    POS: 15200000,
    start: 15199999,
    end: 15200000,
    type: 'SNV',
    name: 'rs1',
    description: 'SNV from A to T',
    ID: ['rs1'],
    REF: 'A',
    ALT: ['T'],
    QUAL: 812.5,
    FILTER: 'PASS',
    FORMAT: 'GT:DP',
    INFO: {
      CSQ: ['T|missense_variant|MODERATE|NOTCH3|ENSG1|ENST1.1:c.100A>T|ENSP1.1:p.Lys34Met'],
      GeneticModels: ['fam:AR_comp|AD'],
      RankScore: ['fam:14.0'],
      RankScoreNormalized: [0.82],
      GNOMADAF: [0.00004],
      CADD: [27.31],
      MQ: [60],
    },
    samples: { s1: { GT: ['0/1'], DP: [30] } },
  };

  it('builds the header, facts, chips, tables and the leftover fields', () => {
    const v = buildFeatureView(feature, {
      widgetType: 'VariantFeatureWidget',
      descriptions: { INFO: { CSQ: { Description: CSQ_DESC } } },
    });
    expect(v.kind).toBe('variant');
    expect(v.title).toBe('NOTCH3');
    expect(v.subtitle).toBe('rs1');
    expect(v.typeLabel).toBe('SNV');
    expect(v.locus).toBe('19:15,200,000');
    const facts = Object.fromEntries(v.facts.map((f) => [f.label, f]));
    expect(facts.Alleles.value).toBe('A → T');
    expect(facts.Quality.value).toBe('812.5');
    expect(facts.Filter).toMatchObject({ value: 'PASS', tone: 'green' });
    expect(facts['Rank score'].value).toBe('14');
    expect(facts['gnomAD AF'].value).toBe('4e-5');
    expect(facts.CADD.value).toBe('27.31');
    expect(v.chips[0].chips.map((c) => c.text)).toEqual(['Compound heterozygous', 'Dominant']);
    expect(v.annotations).toHaveLength(1);
    expect(v.annotationSource).toBe('CSQ');
    expect(v.genotypes).toHaveLength(1);
    // The unknown key and the untouched raw CSQ string stay reachable.
    const keys = v.fields.map((f) => f.key);
    expect(keys).toContain('MQ');
    expect(keys).toContain('CSQ (raw)');
    expect(keys).not.toContain('RankScore');
    expect(keys).not.toContain('REF');
  });

  it('uses the ID without annotations and flags a failed filter', () => {
    const v = buildFeatureView(
      { ...feature, INFO: {}, FILTER: ['LowQual', 'LowDP'] },
      { widgetType: 'VariantFeatureWidget' },
    );
    expect(v.title).toBe('rs1');
    expect(v.subtitle).toBeUndefined();
    expect(v.facts.find((f) => f.label === 'Filter')).toMatchObject({ value: 'LowQual, LowDP', tone: 'red' });
  });

  it('labels indels from the alleles when the type is missing', () => {
    const base = { refName: '1', start: 9, end: 10, REF: 'A', INFO: {} };
    expect(buildFeatureView({ ...base, ALT: ['AT'] }).typeLabel).toBe('Insertion');
    expect(buildFeatureView({ ...base, REF: 'AT', ALT: ['A'] }).typeLabel).toBe('Deletion');
    expect(buildFeatureView({ ...base, ALT: ['G'] }).typeLabel).toBe('SNV');
  });
});

describe('buildFeatureView: alignment', () => {
  it('shows the read facts, decoded flags and the tags as fields', () => {
    const v = buildFeatureView(
      {
        uniqueId: 'r',
        refName: 'chr2',
        start: 999,
        end: 1149,
        name: 'read/1',
        strand: -1,
        score: 60,
        CIGAR: '150M',
        flags: 1089,
        template_length: -350,
        next_segment_position: 'chr2:1400',
        seq: 'ACGT',
        qual: 'IIII',
        tags: { NM: 0, MD: '150' },
      },
      { widgetType: 'AlignmentsFeatureWidget' },
    );
    expect(v.kind).toBe('alignment');
    expect(v.title).toBe('read/1');
    expect(v.locus).toBe('chr2:1,000-1,149');
    const facts = Object.fromEntries(v.facts.map((f) => [f.label, f.value]));
    expect(facts.Strand).toBe('−');
    expect(facts.MAPQ).toBe('60');
    expect(facts.CIGAR).toBe('150M');
    expect(facts['Insert size']).toBe('350 bp');
    expect(facts.Mate).toBe('chr2:1,400');
    expect(v.chips[0].chips.map((c) => c.text)).toContain('duplicate');
    const keys = v.fields.map((f) => f.key);
    expect(keys).toEqual(expect.arrayContaining(['NM', 'MD', 'seq', 'qual', 'flags']));
  });
});

describe('buildFeatureView: gene', () => {
  const gene = {
    uniqueId: 'g',
    refName: 'chr3',
    start: 99,
    end: 5099,
    strand: 1,
    type: 'gene',
    name: 'TP53',
    biotype: 'protein_coding',
    description: 'tumor protein p53',
    hgnc: 'HGNC:11998',
    subfeatures: [
      {
        type: 'mRNA',
        subfeatures: [{ type: 'exon' }, { type: 'exon' }, { type: 'CDS' }, { type: 'five_prime_UTR' }],
      },
    ],
  };

  it('summarises subfeatures as counts', () => {
    expect(countSubfeatures(gene.subfeatures)).toEqual([
      ['mRNA', 1],
      ['exon', 2],
      ['CDS', 1],
      ['five_prime_UTR', 1],
    ]);
    const v = buildFeatureView(gene);
    expect(v.kind).toBe('feature');
    expect(v.title).toBe('TP53');
    expect(v.typeLabel).toBe('Gene');
    expect(v.description).toBe('tumor protein p53');
    expect(v.chips[0].chips.map((c) => c.text)).toEqual(['1 mRNA', '2 exons', '1 CDS', "1 5' UTR"]);
    const facts = Object.fromEntries(v.facts.map((f) => [f.label, f.value]));
    expect(facts.Strand).toBe('+');
    expect(facts.Biotype).toBe('protein coding');
    expect(facts.Length).toBe('5,000 bp');
    expect(v.fields).toEqual([{ key: 'hgnc', value: 'HGNC:11998' }]);
  });

  it('keeps an alias that carries a different value', () => {
    const v = buildFeatureView({ ...gene, gene_name: 'P53-alias' });
    expect(v.fields.map((f) => f.key)).toContain('gene_name');
  });
});
