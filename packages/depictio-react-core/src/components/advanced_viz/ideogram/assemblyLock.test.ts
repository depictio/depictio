import { describe, expect, it } from 'vitest';

import { isAssemblyLocked, pinnedAssembly } from './assemblyLock';

describe('pinnedAssembly', () => {
  it('reads a stated assembly, trimmed', () => {
    expect(pinnedAssembly({ assembly: 'hg38' })).toBe('hg38');
    expect(pinnedAssembly({ assembly: ' mm10 ' })).toBe('mm10');
  });

  it('pins nothing for a blank, a null or an unresolved placeholder', () => {
    for (const assembly of [null, undefined, '', '  ', '{GENOME}', '${GENOME}', 'hg{N}']) {
      expect(pinnedAssembly({ assembly })).toBeNull();
    }
  });
});

describe('isAssemblyLocked', () => {
  it('locks exactly when an assembly is pinned and nothing says otherwise', () => {
    expect(isAssemblyLocked({ assembly: 'hg38' })).toBe(true);
    expect(isAssemblyLocked({})).toBe(false);
    expect(isAssemblyLocked({ assembly: '{GENOME}' })).toBe(false);
    expect(isAssemblyLocked({ assembly: 'hg38', lock_assembly: null })).toBe(true);
  });

  it('obeys lock_assembly either way', () => {
    expect(isAssemblyLocked({ assembly: 'hg38', lock_assembly: false })).toBe(false);
    expect(isAssemblyLocked({ lock_assembly: true })).toBe(true);
  });
});
