import { describe, expect, it } from 'vitest';

import {
  folderAncestors,
  folderName,
  folderSource,
  isS3Location,
  middleEllipsis,
  normalizeFolder,
  parentFolder,
  pathBarQuery,
  relativeToFolder,
  relativeToRunFolder,
  shortenFolder,
  shortenHome,
} from './runFolderPaths';

describe('normalizeFolder', () => {
  it('drops the trailing slash of a local folder and keeps the root', () => {
    expect(normalizeFolder('/data/run42/')).toBe('/data/run42');
    expect(normalizeFolder('/data//run42')).toBe('/data/run42');
    expect(normalizeFolder('/')).toBe('/');
    expect(normalizeFolder('  ~/results/ ')).toBe('~/results');
    expect(normalizeFolder('~')).toBe('~');
  });

  it('ends an S3 prefix with exactly one slash and lower-cases the scheme', () => {
    expect(normalizeFolder('s3://bucket/runs')).toBe('s3://bucket/runs/');
    expect(normalizeFolder('S3://bucket//runs///')).toBe('s3://bucket/runs/');
    expect(normalizeFolder('s3://bucket')).toBe('s3://bucket/');
  });

  it('leaves empty input empty', () => {
    expect(normalizeFolder('   ')).toBe('');
  });
});

describe('source, name and parent', () => {
  it('tells S3 from local', () => {
    expect(isS3Location('s3://b/p/')).toBe(true);
    expect(isS3Location(' S3://b')).toBe(true);
    expect(folderSource('/data')).toBe('local');
    expect(folderSource('s3://b/')).toBe('s3');
  });

  it('names a folder by its last segment', () => {
    expect(folderName('/data/run42')).toBe('run42');
    expect(folderName('s3://bucket/results/')).toBe('results');
    expect(folderName('s3://bucket/')).toBe('bucket');
    expect(folderName('/')).toBe('/');
  });

  it('goes one level up and stops at the top', () => {
    expect(parentFolder('/data/run42')).toBe('/data');
    expect(parentFolder('/data')).toBe('/');
    expect(parentFolder('/')).toBeNull();
    expect(parentFolder('~/results')).toBe('~');
    expect(parentFolder('~')).toBeNull();
    expect(parentFolder('s3://bucket/a/b/')).toBe('s3://bucket/a/');
    expect(parentFolder('s3://bucket/a/')).toBe('s3://bucket/');
    expect(parentFolder('s3://bucket/')).toBeNull();
  });
});

describe('folderAncestors', () => {
  it('lists every folder from the root down to the target', () => {
    expect(folderAncestors('/Users/me', '/Users/me/results/run42')).toEqual([
      '/Users/me',
      '/Users/me/results',
      '/Users/me/results/run42',
    ]);
    expect(folderAncestors('s3://b/runs/', 's3://b/runs/2024/run1/')).toEqual([
      's3://b/runs/',
      's3://b/runs/2024/',
      's3://b/runs/2024/run1/',
    ]);
  });

  it('accepts either spelling of the same folder', () => {
    expect(folderAncestors('/Users/me/', '/Users/me')).toEqual(['/Users/me']);
    expect(folderAncestors('s3://b/runs', 's3://b/runs/x')).toEqual([
      's3://b/runs/',
      's3://b/runs/x/',
    ]);
  });

  it('refuses a target outside the root', () => {
    expect(folderAncestors('/Users/me', '/Users/meagain/run')).toBeNull();
    expect(folderAncestors('/Users/me/results', '/Users/me')).toBeNull();
    expect(folderAncestors('s3://b/runs/', '/Users/me')).toBeNull();
  });
});

describe('relativeToFolder', () => {
  it('writes a location relative to the run folder', () => {
    expect(relativeToFolder('/r/run42', '/r/run42/multiqc/multiqc_data')).toBe(
      'multiqc/multiqc_data',
    );
    expect(relativeToFolder('s3://b/run/', 's3://b/run/qiime2/table.tsv')).toBe('qiime2/table.tsv');
    expect(relativeToFolder('s3://b/run/', 's3://b/run')).toBe('');
  });

  it('answers null outside the run folder or for a bare name', () => {
    expect(relativeToFolder('/r/run42', '/r/run43/x')).toBeNull();
    expect(relativeToFolder('s3://b/run/', 's3://other/run/x')).toBeNull();
    expect(relativeToFolder('/r/run42', '')).toBeNull();
  });

  it('matches a ~ run folder against full paths through the home folder', () => {
    expect(relativeToRunFolder('~/results/run42', '/Users/me/results/run42/multiqc')).toBe(
      'multiqc',
    );
    expect(
      relativeToRunFolder('~/results/run42', '/srv/me/results/run42/multiqc', '/srv/me'),
    ).toBe('multiqc');
  });
});

describe('shortening', () => {
  it('writes the home folder as ~', () => {
    expect(shortenHome('/Users/me/results/run42')).toBe('~/results/run42');
    expect(shortenHome('/home/me')).toBe('~');
    expect(shortenHome('/data/me/run')).toBe('/data/me/run');
    expect(shortenHome('/srv/u/x', '/srv/u')).toBe('~/x');
    expect(shortenHome('s3://b/Users/x/')).toBe('s3://b/Users/x/');
  });

  it('cuts the middle on segment boundaries and keeps the last one', () => {
    const long = '~/results/projects/2024/microbiome/ampliseq/run42';
    const short = middleEllipsis(long, 32);
    expect(short.length).toBeLessThanOrEqual(32);
    expect(short.startsWith('~/results/…/')).toBe(true);
    expect(short.endsWith('/ampliseq/run42')).toBe(true);
    expect(middleEllipsis('/a/b', 32)).toBe('/a/b');
  });

  it('keeps the trailing slash of an S3 prefix', () => {
    const short = middleEllipsis('s3://bucket/very/long/path/to/the/run/folder/', 30);
    expect(short.startsWith('s3://bucket/…/')).toBe(true);
    expect(short.endsWith('folder/')).toBe(true);
  });

  it('falls back to a character cut when one segment is too long', () => {
    const short = middleEllipsis('/x/averyveryveryveryveryverylongfoldername', 20);
    expect(short.length).toBe(20);
    expect(short).toContain('…');
  });

  it('combines both', () => {
    expect(shortenFolder('/Users/me/results/run42')).toBe('~/results/run42');
  });
});

describe('pathBarQuery', () => {
  it('lists the folder itself after a trailing slash', () => {
    expect(pathBarQuery('/Users/me/')).toEqual({ parent: '/Users/me', partial: '' });
    expect(pathBarQuery('s3://b/runs/')).toEqual({ parent: 's3://b/runs/', partial: '' });
    expect(pathBarQuery('/')).toEqual({ parent: '/', partial: '' });
  });

  it('filters the parent by the segment being typed', () => {
    expect(pathBarQuery('/Users/me/res')).toEqual({ parent: '/Users/me', partial: 'res' });
    expect(pathBarQuery('~/res')).toEqual({ parent: '~', partial: 'res' });
    expect(pathBarQuery('/Us')).toEqual({ parent: '/', partial: 'Us' });
    expect(pathBarQuery('s3://b/ru')).toEqual({ parent: 's3://b/', partial: 'ru' });
  });

  it('has no parent before the first folder is written', () => {
    expect(pathBarQuery('')).toEqual({ parent: null, partial: '' });
    expect(pathBarQuery('s3://buck')).toEqual({ parent: null, partial: 's3://buck' });
    expect(pathBarQuery('results')).toEqual({ parent: null, partial: 'results' });
  });
});
