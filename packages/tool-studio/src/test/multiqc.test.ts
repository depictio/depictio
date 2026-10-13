import { describe, it, expect } from 'vitest';
import { multiqcModuleFor } from '../catalog/multiqc';

// A slice of the vendored index, chosen for the cases that matter: a plain
// name, an underscored one, and a versioned pair MultiQC really does ship
// separately (bowtie1/bowtie2) next to one it does not (kraken).
const MODULES = new Set([
  'salmon',
  'featurecounts',
  'kraken',
  'bowtie1',
  'bowtie2',
  'trim_galore',
  'mosdepth',
]);

const nfcore = (mod: string) => `https://github.com/nf-core/modules/tree/master/modules/nf-core/${mod}`;

describe('multiqcModuleFor', () => {
  it('matches a tool id straight against the index', () => {
    expect(multiqcModuleFor(MODULES, { id: 'salmon' })).toBe('salmon');
  });

  it('matches either half of an nf-core module path', () => {
    // MultiQC calls it "featurecounts"; nf-core files it under subread/.
    expect(multiqcModuleFor(MODULES, { nf_core_url: nfcore('subread/featurecounts') })).toBe(
      'featurecounts',
    );
  });

  it('ignores separators and case', () => {
    expect(multiqcModuleFor(MODULES, { id: 'trimgalore' })).toBe('trim_galore');
    expect(multiqcModuleFor(MODULES, { id: 'Mosdepth' })).toBe('mosdepth');
  });

  it('drops a trailing version digit when there is no exact match', () => {
    expect(multiqcModuleFor(MODULES, { id: 'kraken2' })).toBe('kraken');
  });

  it('prefers the exact versioned module over its stem', () => {
    // The whole point of the guard: bowtie1 and bowtie2 are distinct MultiQC
    // modules, so bowtie2 must not fall back to a "bowtie" stem match.
    expect(multiqcModuleFor(MODULES, { id: 'bowtie2' })).toBe('bowtie2');
    expect(multiqcModuleFor(MODULES, { id: 'bowtie1' })).toBe('bowtie1');
  });

  it('returns null for a tool MultiQC does not parse', () => {
    expect(multiqcModuleFor(MODULES, { id: 'mlst' })).toBeNull();
    expect(multiqcModuleFor(MODULES, { nf_core_url: nfcore('amrfinderplus/run') })).toBeNull();
  });

  it('does not match on a stem too short to mean anything', () => {
    // "2" strips to "", and a one or two letter stem would match half the index.
    expect(multiqcModuleFor(MODULES, { id: '2' })).toBeNull();
  });

  it('is inert until the index has loaded', () => {
    expect(multiqcModuleFor(new Set(), { id: 'salmon' })).toBeNull();
  });
});
